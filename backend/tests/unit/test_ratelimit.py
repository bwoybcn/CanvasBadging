# SPDX-License-Identifier: AGPL-3.0-or-later
"""The in-app request limit for public and sign-in routes (whole-product review, finding 5)."""

from __future__ import annotations

import pytest

from opencredential.api.ratelimit import MAX_TRACKED, Limiter, group_for


@pytest.mark.parametrize(
    ("method", "path", "group"),
    [
        ("POST", "/api/v1/verify", "verify"),
        ("GET", "/verify/abc123", "verify"),
        ("GET", "/verify/abc123/verification.json", "verify"),
        ("POST", "/lti/login", "signin"),
        ("GET", "/lti/login", "signin"),
        ("POST", "/lti/launch", "signin"),
        ("POST", "/dev/login", "signin"),
        # Cheap or cacheable public reads, and everything behind a session, are not limited.
        ("GET", "/verify", None),
        ("GET", "/verify/abc123/credential.json", None),
        ("GET", "/verify-assets/check.js", None),
        ("GET", "/status/demo/0190aaaa-0000-7000-8000-000000000000", None),
        ("GET", "/issuers/demo/did.json", None),
        ("GET", "/lti/jwks", None),
        ("GET", "/api/v1/learners/me", None),
        ("GET", "/healthz", None),
    ],
)
def test_only_public_verification_and_sign_in_are_limited(method, path, group):
    assert group_for(method, path) == group


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_client_gets_its_allowance_then_waits_and_others_are_unaffected():
    clock = Clock()
    limiter = Limiter({"verify": 6, "signin": 0}, clock)
    assert [limiter.check("verify", "10.0.0.1") for _ in range(6)] == [0.0] * 6
    wait = limiter.check("verify", "10.0.0.1")
    assert wait == pytest.approx(10.0)  # six a minute is one every ten seconds
    # another address, and another group for the same address, have their own allowance
    assert limiter.check("verify", "10.0.0.2") == 0.0
    assert limiter.check("signin", "10.0.0.1") == 0.0  # 0 means "not limited"
    clock.now += 10.0
    assert limiter.check("verify", "10.0.0.1") == 0.0
    assert limiter.check("verify", "10.0.0.1") > 0
    clock.now += 600.0  # a long quiet spell never banks more than one minute's allowance
    assert [limiter.check("verify", "10.0.0.1") for _ in range(6)] == [0.0] * 6
    assert limiter.check("verify", "10.0.0.1") > 0


def test_memory_stays_bounded_under_a_flood_of_addresses():
    clock = Clock()
    limiter = Limiter({"verify": 5}, clock)
    for n in range(MAX_TRACKED + 50):
        limiter.check("verify", f"client-{n}")
    assert len(limiter._buckets) <= MAX_TRACKED
    # idle clients are forgotten first: after a quiet minute the table empties on the next new one
    clock.now += 61.0
    limiter.check("verify", "new-a")
    for n in range(MAX_TRACKED):
        limiter.check("verify", f"again-{n}")
    assert len(limiter._buckets) <= MAX_TRACKED
