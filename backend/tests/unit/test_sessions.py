# SPDX-License-Identifier: AGPL-3.0-or-later
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from opencredential.authz import sessions
from opencredential.settings import Settings

S = Settings(env="test")
USER, INST = uuid.uuid4(), uuid.uuid4()


def test_round_trip() -> None:
    token, expires = sessions.issue(S, user_id=USER, institution_id=INST, method="dev")
    claims = sessions.verify(S, token)
    assert (claims.user_id, claims.institution_id, claims.method) == (USER, INST, "dev")
    assert claims.expires_at == expires.replace(microsecond=0)


def test_rejects_other_key() -> None:
    token, _ = sessions.issue(S, user_id=USER, institution_id=INST, method="dev")
    other = Settings(env="test", secret_key="another-secret-key-of-sufficient-length-123")
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(other, token)


def test_rejects_expired() -> None:
    expired = Settings(env="test")
    object.__setattr__(expired, "session_ttl_minutes", -1)
    token, _ = sessions.issue(expired, user_id=USER, institution_id=INST, method="dev")
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(S, token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "eyJhbGciOiJub25lIn0.e30."])
def test_rejects_garbage_and_alg_none(token: str) -> None:
    with pytest.raises(sessions.InvalidSession):
        sessions.verify(S, token)


def test_renewal_keeps_identity_and_start_and_extends_expiry() -> None:
    from dataclasses import replace

    course = uuid.uuid4()
    token, _ = sessions.issue(S, user_id=USER, institution_id=INST, method="lti", course_id=course)
    # The same session 20 minutes in: it began earlier and its token has 10 minutes left.
    first = sessions.verify(S, token)
    aged = replace(
        first,
        started_at=first.started_at - timedelta(minutes=20),
        expires_at=first.expires_at - timedelta(minutes=20),
    )
    renewed_token, expires = sessions.renew(S, aged)
    renewed = sessions.verify(S, renewed_token)
    assert (renewed.user_id, renewed.institution_id, renewed.course_id, renewed.method) == (
        USER,
        INST,
        course,
        "lti",
    )
    assert renewed.started_at == aged.started_at
    assert expires > aged.expires_at + timedelta(minutes=15)


def test_renewal_stops_at_the_session_limit() -> None:
    token, _ = sessions.issue(S, user_id=USER, institution_id=INST, method="lti")
    first = sessions.verify(S, token)
    limit = sessions.renewable_until(S, first.started_at)
    # Close to the limit the new token is cut off at the limit, not a full lifetime later.
    near = limit - timedelta(minutes=5)
    _, expires = sessions.renew(S, _aged(first, near), now=near)
    assert expires == limit
    # A token that already runs to the limit, or a session past it, cannot be extended.
    with pytest.raises(sessions.SessionTooOld):
        sessions.renew(S, _aged(first, limit), now=near)
    with pytest.raises(sessions.SessionTooOld):
        sessions.renew(S, _aged(first, limit + timedelta(minutes=1)), now=limit)


def test_renewal_is_off_when_the_limit_is_not_above_the_lifetime() -> None:
    short = Settings(env="test", session_max_minutes=30)
    token, _ = sessions.issue(short, user_id=USER, institution_id=INST, method="lti")
    with pytest.raises(sessions.SessionTooOld):
        sessions.renew(short, sessions.verify(short, token))


def test_tokens_from_before_renewal_count_from_their_issue_time() -> None:
    from joserfc import jwt

    now = int(datetime.now(UTC).timestamp())
    old = jwt.encode(
        {"alg": "HS256"},
        {
            "iss": sessions.ISSUER,
            "aud": sessions.AUDIENCE,
            "sub": str(USER),
            "inst": str(INST),
            "crs": None,
            "amr": "lti",
            "iat": now,
            "exp": now + 600,
        },
        sessions._key(S),
    )
    assert sessions.verify(S, old).started_at == datetime.fromtimestamp(now, UTC)


def _aged(claims: sessions.SessionClaims, expires_at: datetime) -> sessions.SessionClaims:
    """The same session, as if its current token expired at ``expires_at``."""
    from dataclasses import replace

    return replace(claims, expires_at=expires_at)


def test_canvas_admin_flag_survives_renewal_and_defaults_off() -> None:
    from opencredential.lti.claims import is_platform_admin

    assert is_platform_admin(
        ["http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"]
    )
    assert not is_platform_admin(["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"])
    plain, _ = sessions.issue(S, user_id=USER, institution_id=INST, method="lti")
    assert sessions.verify(S, plain).platform_admin is False
    token, _ = sessions.issue(
        S, user_id=USER, institution_id=INST, method="lti", platform_admin=True
    )
    claims = sessions.verify(S, token)
    assert claims.platform_admin is True
    renewed, _ = sessions.renew(S, claims)
    assert sessions.verify(S, renewed).platform_admin is True
