# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform (Canvas) JWKS fetching with caching and ``kid`` rotation (ADR-0008).

Keys are cached per JWKS URL for ``CACHE_SECONDS``. A token whose ``kid`` is not in the cache
triggers one refetch (Canvas rotates its LTI keys monthly), rate-limited so that a flood of
forged tokens with random ``kid`` values cannot turn us into a request amplifier.
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


class JwksUnavailable(Exception):
    pass


@dataclass
class _Entry:
    keys: KeySet
    fetched: float
    kids: set[str] = field(default_factory=set)


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
        new = self._fetch(settings, url)
        with self._lock:
            self._entries[url] = new
        return new.keys


#: Process-wide cache used by the launch endpoint. Tests replace its transport.
platform_jwks = JwksCache()
