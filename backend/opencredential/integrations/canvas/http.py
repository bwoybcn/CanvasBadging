# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP plumbing for Canvas: pagination, throttling, retries and error mapping (spec §4.4).

Behaviour verified against a local Canvas (2026-04 build), see docs/integrations/canvas.md:

* Pagination is RFC 8288 ``Link`` headers. We follow ``rel="next"`` only when it points at the
  same origin we called, so a tampered header cannot send our token elsewhere.
* Throttling: every response carries ``X-Rate-Limit-Remaining`` and ``X-Request-Cost``. When the
  bucket is exhausted Canvas answers **403** with body ``403 Forbidden (Rate Limit Exceeded)``
  (429 only if the operator enabled ``request_throttle.send_429_response``). Both are treated as
  transient and retried with backoff; we also slow down when the bucket runs low.
* 401 means the token expired or was revoked: the token provider refreshes once, then the call
  fails with :class:`CanvasAuthError` (a permission error: rules stay ``unknown``).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from opencredential.integrations.base import (
    LmsNotFound,
    LmsPermissionError,
    LmsTransientError,
)
from opencredential.logging import get_logger
from opencredential.settings import Settings

log = get_logger("canvas.http")

PER_PAGE = 100
MAX_PAGES = 500
LOW_BUCKET = 50.0


class CanvasAuthError(LmsPermissionError):
    code = "LMS_AUTH"


def rewrite_url(settings: Settings, url: str) -> str:
    """Apply ``OC_CANVAS_URL_REWRITE`` (``from=to[,from=to]``) for server-side calls."""
    rules = settings.canvas_url_rewrite
    if not rules:
        return url
    for rule in rules.split(","):
        src, _, dst = rule.strip().partition("=")
        if src and dst and url.startswith(src.rstrip("/")):
            return dst.rstrip("/") + url[len(src.rstrip("/")) :]
    return url


def host_header(settings: Settings, url: str) -> dict[str, str]:
    """``Host`` header to send when ``url`` is rewritten: Canvas resolves its domain (and
    refuses unknown ones with 403) from the Host header, so keep the public one."""
    if rewrite_url(settings, url) == url:
        return {}
    return {"host": urlsplit(url).netloc}


def url_origin(url: str) -> str:
    """Scheme and host of a URL, for same-site checks before a token is sent."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


def next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip().split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().strip("<>")
        if any(p.strip().replace(" ", "") == 'rel="next"' for p in section[1:]):
            return url
    return None


def _is_throttled(resp: httpx.Response) -> bool:
    if resp.status_code == 429:
        return True
    return resp.status_code == 403 and "rate limit exceeded" in resp.text[:200].lower()


@dataclass
class TokenProvider:
    """Supplies a bearer token; ``refresh`` is called once after a 401."""

    get: Callable[[], str]
    refresh: Callable[[], str] | None = None


class CanvasHttp:
    def __init__(
        self,
        settings: Settings,
        base_url: str,
        tokens: TokenProvider,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=settings.canvas_timeout_seconds,
            transport=transport,
            headers={"accept": "application/json", "user-agent": "OpenCredential"},
            follow_redirects=False,
        )
        self.requests_made = 0
        self.last_remaining: float | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CanvasHttp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- core request with retries --------------------------------------------------------

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
        else:
            url = urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        return url

    def request(
        self, path_or_url: str, params: dict[str, Any] | list[tuple[str, Any]] | None = None
    ) -> httpx.Response:
        url = self._url(path_or_url)
        allowed = {url_origin(self.base_url), url_origin(rewrite_url(self.settings, self.base_url))}
        if url_origin(url) not in allowed:
            raise LmsPermissionError(f"refusing to call {url_origin(url)} with a Canvas token")
        refreshed = False
        attempt = 0
        while True:
            attempt += 1
            token = self.tokens.get()
            try:
                self.requests_made += 1
                resp = self._client.get(
                    rewrite_url(self.settings, url),
                    params=params,
                    headers={"authorization": f"Bearer {token}", **host_header(self.settings, url)},
                )
            except httpx.TimeoutException as exc:
                if self._backoff(attempt, None):
                    continue
                raise LmsTransientError(f"Canvas timed out: {url}") from exc
            except httpx.TransportError as exc:
                if self._backoff(attempt, None):
                    continue
                raise LmsTransientError(f"Canvas unreachable: {exc}") from exc

            self._note_bucket(resp)
            if resp.status_code < 300:
                return resp
            if _is_throttled(resp):
                if self._backoff(attempt, resp.headers.get("retry-after")):
                    continue
                raise LmsTransientError("Canvas rate limit exceeded")
            if resp.status_code == 401:
                if not refreshed and self.tokens.refresh is not None:
                    refreshed = True
                    self.tokens.refresh()
                    continue
                raise CanvasAuthError("Canvas rejected the API token (expired or revoked)")
            if resp.status_code == 403:
                raise LmsPermissionError(f"Canvas denied access to {urlsplit(url).path}")
            if resp.status_code == 404:
                raise LmsNotFound(f"Canvas has no {urlsplit(url).path}")
            if resp.status_code >= 500 or resp.status_code in (408, 409, 425):
                if self._backoff(attempt, resp.headers.get("retry-after")):
                    continue
                raise LmsTransientError(f"Canvas error {resp.status_code}")
            raise LmsPermissionError(f"Canvas answered {resp.status_code} for {urlsplit(url).path}")

    def _backoff(self, attempt: int, retry_after: str | None) -> bool:
        if attempt > self.settings.canvas_max_retries:
            return False
        delay = min(30.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.25)  # noqa: S311
        if retry_after:
            try:
                delay = max(delay, min(60.0, float(retry_after)))
            except ValueError:
                pass
        log.info("canvas.retry", attempt=attempt, delay=round(delay, 2))
        self._sleep(delay)
        return True

    def _note_bucket(self, resp: httpx.Response) -> None:
        raw = resp.headers.get("x-rate-limit-remaining")
        if raw is None:
            return
        try:
            self.last_remaining = float(raw)
        except ValueError:
            return
        if self.last_remaining < LOW_BUCKET:
            # The bucket refills continuously; pausing briefly avoids hitting the wall.
            self._sleep(min(2.0, (LOW_BUCKET - self.last_remaining) / 25))

    # ---- helpers ---------------------------------------------------------------------------

    def get_json(
        self, path: str, params: dict[str, Any] | list[tuple[str, Any]] | None = None
    ) -> Any:
        resp = self.request(path, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise LmsTransientError("Canvas returned a non-JSON body") from exc

    def paginate(
        self, path: str, params: dict[str, Any] | list[tuple[str, Any]] | None = None
    ) -> Iterator[Any]:
        """Yield every element of a paginated list endpoint.

        Raises if any page fails: a partial list must never look complete (ADR-0010)."""
        items = list(params.items()) if isinstance(params, dict) else list(params or [])
        if not any(k == "per_page" for k, _ in items):
            items.append(("per_page", PER_PAGE))
        resp = self.request(path, items)
        pages = 1
        while True:
            try:
                data = resp.json()
            except ValueError as exc:
                raise LmsTransientError("Canvas returned a non-JSON page") from exc
            if not isinstance(data, list):
                raise LmsTransientError(f"expected a list from {path}")
            yield from data
            nxt = next_link(resp.headers.get("link"))
            if not nxt:
                return
            pages += 1
            if pages > MAX_PAGES:
                raise LmsTransientError(f"pagination of {path} exceeded {MAX_PAGES} pages")
            resp = self.request(nxt)
