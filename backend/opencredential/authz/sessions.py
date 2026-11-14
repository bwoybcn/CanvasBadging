# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived bearer session tokens (HS256 JWT via joserfc).

The token carries only identifiers. Roles are always re-read from the database, so revoking a
membership takes effect on the next request rather than at token expiry.

A token lasts ``session_ttl_minutes``. While someone is working, the app swaps it for a fresh
one (:func:`renew`), so a long form is not lost to a time-out. A session can never outlive
``session_max_minutes`` from its Canvas launch: after that the person opens the tool from Canvas
again. A token that is left idle still expires after ``session_ttl_minutes``.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from opencredential.settings import Settings

ISSUER = "opencredential"
AUDIENCE = "opencredential-api"


class InvalidSession(Exception):
    pass


class SessionTooOld(Exception):
    """The session has reached ``session_max_minutes`` and cannot be extended further."""


@dataclass(frozen=True)
class SessionClaims:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    course_id: uuid.UUID | None
    method: str  # "lti" | "dev"
    expires_at: datetime
    #: When the session began (the Canvas launch). Renewed tokens keep the original value.
    started_at: datetime


def _key(settings: Settings) -> OctKey:
    return OctKey.import_key(settings.secret_key.get_secret_value().encode())


def issue(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    method: str,
    course_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    expires = now + timedelta(minutes=settings.session_ttl_minutes)
    if started_at is not None:
        # A renewed token never runs past the session's absolute limit.
        expires = min(expires, renewable_until(settings, started_at))
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "inst": str(institution_id),
        "crs": str(course_id) if course_id else None,
        "amr": method,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "auth_time": int((started_at or now).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode({"alg": "HS256"}, claims, _key(settings))
    return token, expires


def renewable_until(settings: Settings, started_at: datetime) -> datetime:
    """The latest moment any token of a session that began at ``started_at`` may be valid."""
    return started_at + timedelta(minutes=settings.session_max_minutes)


def renew(
    settings: Settings, claims: SessionClaims, now: datetime | None = None
) -> tuple[str, datetime]:
    """A fresh token for the same person, institution and course as ``claims``.

    The caller has already verified the current token (it is unexpired and correctly signed) and
    checked that the account is still active. Raises :class:`SessionTooOld` once the session has
    run for ``session_max_minutes``.
    """
    now = now or datetime.now(UTC)
    limit = renewable_until(settings, claims.started_at)
    # Nothing to gain once the current token already runs to the limit (or renewal is off).
    if now >= limit or claims.expires_at >= limit:
        raise SessionTooOld
    return issue(
        settings,
        user_id=claims.user_id,
        institution_id=claims.institution_id,
        method=claims.method,
        course_id=claims.course_id,
        started_at=claims.started_at,
        now=now,
    )


def verify(settings: Settings, token: str) -> SessionClaims:
    try:
        decoded = jwt.decode(token, _key(settings), algorithms=["HS256"])
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": ISSUER},
            aud={"essential": True, "value": AUDIENCE},
            exp={"essential": True},
            sub={"essential": True},
        ).validate(decoded.claims)
        c = decoded.claims
        return SessionClaims(
            user_id=uuid.UUID(c["sub"]),
            institution_id=uuid.UUID(c["inst"]),
            course_id=uuid.UUID(c["crs"]) if c.get("crs") else None,
            method=str(c.get("amr", "")),
            expires_at=datetime.fromtimestamp(int(c["exp"]), UTC),
            # Tokens issued before renewal existed carry no ``auth_time``: they began at ``iat``.
            started_at=datetime.fromtimestamp(int(c.get("auth_time") or c["iat"]), UTC),
        )
    except (JoseError, KeyError, ValueError, TypeError) as exc:
        raise InvalidSession(str(exc)) from exc
