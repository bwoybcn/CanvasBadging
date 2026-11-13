# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request dependencies: settings, authenticated principal, tenant-scoped DB session."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from opencredential.api.errors import ApiError
from opencredential.authz import policy, sessions
from opencredential.db.session import tenant_session
from opencredential.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def current_claims(request: Request, settings: SettingsDep) -> sessions.SessionClaims:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in through Canvas to continue")
    try:
        return sessions.verify(settings, token)
    except sessions.InvalidSession as exc:
        raise ApiError(401, "SESSION_INVALID", "Your session has expired or is invalid") from exc


ClaimsDep = Annotated[sessions.SessionClaims, Depends(current_claims)]


def tenant_db(claims: ClaimsDep) -> Iterator[Session]:
    """One transaction per request, scoped to the caller's institution (never the body's)."""
    with tenant_session(claims.institution_id) as session:
        yield session


TenantDb = Annotated[Session, Depends(tenant_db)]


def current_actor(claims: ClaimsDep, db: TenantDb) -> policy.Actor:
    """The caller with roles freshly read from ``memberships`` (ADR-0013)."""
    return policy.load_actor(db, claims.user_id, claims.institution_id)


ActorDep = Annotated[policy.Actor, Depends(current_actor)]


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


RequestIdDep = Annotated[str | None, Depends(request_id)]
