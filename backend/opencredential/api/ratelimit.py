# SPDX-License-Identifier: AGPL-3.0-or-later
"""A basic per-client request limit for the routes anyone on the internet can reach.

Two groups of routes are limited, each with its own allowance per client address:

* ``verify``: everything that runs a verification without a session (``POST /api/v1/verify``,
  a share page and its machine-readable result). Each one checks a signature, calls the signer
  and may fetch a status list or DID document from another host, on a threadpool of about forty
  threads that every other request shares.
* ``signin``: the LTI login and launch steps and the development sign-in. Each login writes a
  row before anybody has proved who they are.

Signed-in routes are not limited here: they need a session, and Canvas sync has its own limit
per course.

This is the second line, not the first. The count is kept in the memory of one API process, so
with several processes (``OC_API_WORKERS``) a client may get up to that many times the
allowance, and a flood from many addresses is not slowed at all. The reverse proxy carries the
real limit (docs/security/security-guide.md); this one makes an installation whose proxy limit
was forgotten degrade politely instead of stalling.

The client address is ``request.client.host``. Behind a proxy that is only right when uvicorn
trusts the proxy's ``X-Forwarded-For`` (``OC_FORWARDED_ALLOW_IPS``); otherwise every visitor
shares the proxy's address and its one allowance.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from opencredential.api.errors import problem
from opencredential.logging import get_logger
from opencredential.lti import pages

log = get_logger("ratelimit")

WINDOW_SECONDS = 60.0
#: Above this many remembered clients, the ones idle for a full window are forgotten.
MAX_TRACKED = 20_000

MESSAGE = "Too many requests from your network just now. Wait a minute, then try again."


def group_for(method: str, path: str) -> str | None:
    """The limited group a request belongs to, or ``None`` when it is not limited."""
    if path == "/api/v1/verify":
        return "verify" if method == "POST" else None
    if path.startswith("/verify/") and method == "GET":
        # /verify/<share id> and /verify/<share id>/verification.json run a verification.
        # credential.json only reads the stored file, and /verify itself is a static form.
        rest = path[len("/verify/") :].strip("/")
        if rest and (("/" not in rest) or rest.endswith("/verification.json")):
            return "verify"
        return None
    if path in ("/lti/login", "/lti/launch", "/dev/login"):
        return "signin"
    return None


@dataclass
class _Bucket:
    tokens: float
    updated: float


class Limiter:
    """Token bucket per (group, client): ``per_minute`` requests at once, refilled evenly."""

    def __init__(self, limits: dict[str, int], clock: Callable[[], float] = time.monotonic):
        self.limits = {group: n for group, n in limits.items() if n > 0}
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def check(self, group: str, client: str) -> float:
        """Take one request from the client's allowance.

        Returns 0 when the request may go ahead, otherwise the seconds until one may.
        """
        limit = self.limits.get(group)
        if limit is None:
            return 0.0
        now = self._clock()
        rate = limit / WINDOW_SECONDS
        key = (group, client)
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= MAX_TRACKED:
                self._forget_idle(now)
            bucket = self._buckets[key] = _Bucket(tokens=float(limit), updated=now)
        else:
            bucket.tokens = min(float(limit), bucket.tokens + (now - bucket.updated) * rate)
            bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return 0.0
        return (1.0 - bucket.tokens) / rate

    def _forget_idle(self, now: float) -> None:
        # A bucket untouched for a whole window is full again, so forgetting it loses nothing.
        idle = [k for k, b in self._buckets.items() if now - b.updated >= WINDOW_SECONDS]
        for k in idle:
            del self._buckets[k]
        if len(self._buckets) >= MAX_TRACKED:
            # Still full of active clients: a flood from very many addresses. Start again
            # rather than grow without bound; the proxy limit is what handles this case.
            self._buckets.clear()
            log.warning("ratelimit.reset", reason="too many active client addresses")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limiter: Limiter) -> None:
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        group = group_for(request.method, request.url.path)
        if group is None:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        wait = self.limiter.check(group, client)
        if wait <= 0:
            return await call_next(request)
        retry_after = str(max(1, math.ceil(wait)))
        log.warning("ratelimit.refused", group=group, path=request.url.path)
        response: Response
        if request.url.path.startswith("/lti/"):
            # A person arriving from Canvas reads this, not a program.
            response = pages.error(
                "RATE_LIMITED", MESSAGE, 429, getattr(request.state, "request_id", None)
            )
        else:
            response = problem(request, 429, "RATE_LIMITED", "Too many requests", MESSAGE)
        response.headers["Retry-After"] = retry_after
        response.headers["Cache-Control"] = "no-store"
        return response
