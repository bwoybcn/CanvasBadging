# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived bearer session tokens (HS256 JWT via joserfc).

The token carries only identifiers. Roles are always re-read from the database, so revoking a
membership takes effect on the next request rather than at token expiry.
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


@dataclass(frozen=True)
class SessionClaims:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    course_id: uuid.UUID | None
    method: str  # "lti" | "dev"
    expires_at: datetime


def _key(settings: Settings) -> OctKey:
    return OctKey.import_key(settings.secret_key.get_secret_value().encode())


def issue(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    method: str,
    course_id: uuid.UUID | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.session_ttl_minutes)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "inst": str(institution_id),
        "crs": str(course_id) if course_id else None,
        "amr": method,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode({"alg": "HS256"}, claims, _key(settings))
    return token, expires


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
        )
    except (JoseError, KeyError, ValueError, TypeError) as exc:
        raise InvalidSession(str(exc)) from exc
