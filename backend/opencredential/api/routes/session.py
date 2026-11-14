# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/session``: keep a session alive while someone is working.

The app calls ``POST /api/v1/session/renew`` when the person is active and their token is past
half its life. That stops a long form (the create-badge wizard) being lost to a time-out, while
an idle tab still signs out after ``OC_SESSION_TTL_MINUTES`` and no session outlives
``OC_SESSION_MAX_MINUTES`` from its Canvas launch.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from opencredential.api.deps import ClaimsDep, SettingsDep, TenantDb
from opencredential.api.errors import ApiError
from opencredential.authz import sessions
from opencredential.logging import get_logger

router = APIRouter(prefix="/api/v1/session", tags=["session"])
log = get_logger("session")


class SessionOut(BaseModel):
    token: str
    expires_at: datetime
    #: After this moment the session cannot be extended: open the tool from Canvas again.
    renewable_until: datetime


@router.post(
    "/renew", response_model=SessionOut, summary="Swap a valid session token for a fresh one"
)
def renew(claims: ClaimsDep, settings: SettingsDep, db: TenantDb) -> SessionOut:
    """Needs a token that is still valid. ``TenantDb`` refuses accounts that are no longer active
    (for example after an erasure), so a renewed token is never handed to them."""
    del db  # the dependency's account check is the point
    try:
        token, expires = sessions.renew(settings, claims)
    except sessions.SessionTooOld as exc:
        raise ApiError(
            401,
            "SESSION_TOO_OLD",
            "Your session has reached its time limit",
            "Open Micro-Credentials from Canvas again to carry on.",
        ) from exc
    log.info("session.renewed", method=claims.method)
    return SessionOut(
        token=token,
        expires_at=expires,
        renewable_until=sessions.renewable_until(settings, claims.started_at),
    )
