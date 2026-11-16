# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform (Canvas) JWKS fetching with caching and ``kid`` rotation (ADR-0008).

Keys are cached per JWKS URL for ``CACHE_SECONDS``. A token whose ``kid`` is not in the cache
triggers one refetch (Canvas rotates its LTI keys monthly), rate-limited so that a flood of
forged tokens with random ``kid`` values cannot turn us into a request amplifier.

If Canvas cannot be reached when the hour is up, the keys already held keep working for up to
``MAX_STALE_SECONDS`` (for a token signed with a key we know), so a short Canvas outage does
not stop everyone from opening the tool. A key we have never seen is still refused.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from joserfc.jwk import KeySet

from opencredential.integrations.canvas.http import host_header, rewrite_url
from opencredential.settings import Settings

CACHE_SECONDS = 3600
MIN_REFETCH_SECONDS = 30
#: How long keys that could not be refreshed may still be used.
MAX_STALE_SECONDS = 24 * 3600


class JwksUnavailable(Exception):
    pass


@dataclass
class _Entry:
    keys: KeySet
    fetched: float
    kids: set[str] = field(default_factory=set)
    #: When a refresh last failed (monotonic), so a platform that is down is not hammered.
    failed: float | None = None


class JwksCache:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._transport = transport

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _fetch(self, settings: Settings, url: str) -> _Entry:
        try:
            with httpx.Client(
                timeout=settings.canvas_timeout_seconds, transport=self._transport
            ) as client:
                resp = client.get(
                    rewrite_url(settings, url),
                    headers={"accept": "application/json", **host_header(settings, url)},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JwksUnavailable(f"could not fetch platform keys from {url}: {exc}") from exc
        keys = [k for k in data.get("keys", []) if k.get("kty") == "RSA"]
        if not keys:
            raise JwksUnavailable(f"no RSA keys published at {url}")
        keyset = KeySet.import_key_set({"keys": keys})
        return _Entry(keyset, time.monotonic(), {str(k.get("kid")) for k in keys if k.get("kid")})

    def get(self, settings: Settings, url: str, kid: str | None) -> KeySet:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(url)
        fresh = entry is not None and now - entry.fetched < CACHE_SECONDS
        known = entry is not None and (kid is None or kid in entry.kids)
        if fresh and known:
            assert entry is not None
            return entry.keys
        if entry is not None and fresh and now - entry.fetched < MIN_REFETCH_SECONDS:
            return entry.keys  # unknown kid, but we just fetched: do not hammer the platform
        usable = entry is not None and known and now - entry.fetched < MAX_STALE_SECONDS
        if (
            entry is not None
            and usable
            and entry.failed is not None
            and now - entry.failed < MIN_REFETCH_SECONDS
        ):
            return entry.keys  # the platform was down a moment ago: do not ask again yet
        try:
            new = self._fetch(settings, url)
        except JwksUnavailable:
            if entry is None or not usable:
                raise
            # Canvas could not be reached, but the token names a key we already hold.
            entry.failed = now
            return entry.keys
        with self._lock:
            self._entries[url] = new
        return new.keys


#: Process-wide cache used by the launch endpoint. Tests replace its transport.
platform_jwks = JwksCache()
