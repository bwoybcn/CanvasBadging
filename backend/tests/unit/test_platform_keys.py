# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas's signing keys are cached for an hour. When the hour is up and Canvas cannot be
reached, the keys already held keep working for a day, so a short Canvas outage does not stop
everyone opening Badges (whole-product review, 16 Nov 2026, finding 19)."""

from __future__ import annotations

import httpx
import pytest
from joserfc.jwk import RSAKey

from opencredential.lti import platform_keys
from opencredential.lti.platform_keys import JwksCache, JwksUnavailable
from opencredential.settings import get_settings

URL = "https://canvas.example/api/lti/security/jwks"
KEY = RSAKey.generate_key(2048, auto_kid=True)


class Canvas:
    def __init__(self) -> None:
        self.up = True
        self.hits = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.hits += 1
            if not self.up:
                return httpx.Response(503)
            return httpx.Response(200, json={"keys": [KEY.as_dict(private=False)]})

        return httpx.MockTransport(handler)


def _age(cache: JwksCache, seconds: float) -> None:
    cache._entries[URL].fetched -= seconds


def test_known_key_still_works_when_canvas_is_down_after_the_hour() -> None:
    canvas = Canvas()
    cache = JwksCache(canvas.transport())
    settings = get_settings()
    keys = cache.get(settings, URL, KEY.kid)
    assert canvas.hits == 1

    canvas.up = False
    _age(cache, platform_keys.CACHE_SECONDS + 5)
    assert cache.get(settings, URL, KEY.kid) is keys  # served from what we hold
    assert canvas.hits == 2
    # A platform that is down is not asked again on every launch.
    assert cache.get(settings, URL, KEY.kid) is keys
    assert canvas.hits == 2

    # Canvas comes back: the next refresh (after the short pause) replaces the held keys.
    canvas.up = True
    cache._entries[URL].failed -= platform_keys.MIN_REFETCH_SECONDS + 1  # type: ignore[operator]
    assert cache.get(settings, URL, KEY.kid) is not keys
    assert canvas.hits == 3


def test_a_key_never_seen_is_refused_while_canvas_is_down() -> None:
    canvas = Canvas()
    cache = JwksCache(canvas.transport())
    settings = get_settings()
    cache.get(settings, URL, KEY.kid)
    canvas.up = False
    _age(cache, platform_keys.MIN_REFETCH_SECONDS + 5)
    with pytest.raises(JwksUnavailable):
        cache.get(settings, URL, "a-kid-we-never-saw")


def test_held_keys_are_not_trusted_for_ever() -> None:
    canvas = Canvas()
    cache = JwksCache(canvas.transport())
    settings = get_settings()
    cache.get(settings, URL, KEY.kid)
    canvas.up = False
    _age(cache, platform_keys.MAX_STALE_SECONDS + 5)
    with pytest.raises(JwksUnavailable):
        cache.get(settings, URL, KEY.kid)


def test_nothing_held_and_canvas_down_is_an_error() -> None:
    canvas = Canvas()
    canvas.up = False
    with pytest.raises(JwksUnavailable):
        JwksCache(canvas.transport()).get(get_settings(), URL, KEY.kid)
