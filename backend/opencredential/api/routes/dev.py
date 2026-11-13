# SPDX-License-Identifier: AGPL-3.0-or-later
"""Development-only login (spec §20 Phase 1 "local authentication for development").

This router is never mounted when ``OC_ENV=production``; there is no setting that re-enables it.
Real users always arrive through the Canvas LTI 1.3 launch (W3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from opencredential import audit
from opencredential.api.deps import SettingsDep
from opencredential.api.errors import ApiError
from opencredential.authz import sessions
from opencredential.db.models import Institution, Membership, User
from opencredential.db.session import tenant_session

router = APIRouter(prefix="/dev", tags=["development only"])


class DevUser(BaseModel):
    id: uuid.UUID
    display_name: str | None
    roles: list[str]


class DevLoginRequest(BaseModel):
    institution: str
    user_id: uuid.UUID


class DevLoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user_id: uuid.UUID
    institution_id: uuid.UUID


def _demo_institution_id(slug: str) -> uuid.UUID:
    with tenant_session(None) as db:
        inst = db.scalar(select(Institution).where(Institution.slug == slug))
    if inst is None or not inst.is_demo:
        # Only seeded demonstration tenants accept development login.
        raise ApiError(404, "NOT_FOUND", "No demonstration institution with that slug")
    return inst.id


@router.get("/institutions/{slug}/users", response_model=list[DevUser])
def list_dev_users(slug: str) -> list[DevUser]:
    institution_id = _demo_institution_id(slug)
    with tenant_session(institution_id) as db:
        users = db.scalars(select(User).where(User.status == "active").order_by(User.family_name))
        result = []
        for u in users:
            roles = db.scalars(
                select(Membership.role)
                .where(Membership.user_id == u.id, Membership.revoked_at.is_(None))
                .distinct()
            ).all()
            result.append(DevUser(id=u.id, display_name=u.display_name, roles=sorted(roles)))
    return result


@router.post("/login", response_model=DevLoginResponse)
def dev_login(body: DevLoginRequest, request: Request, settings: SettingsDep) -> DevLoginResponse:
    institution_id = _demo_institution_id(body.institution)
    with tenant_session(institution_id) as db:
        user = db.get(User, body.user_id)
        if user is None or user.status != "active":
            raise ApiError(404, "NOT_FOUND", "No such user in this institution")
        audit.record(
            db,
            action="session.dev_login",
            resource_type="user",
            resource_id=user.id,
            institution_id=institution_id,
            actor_user_id=user.id,
            request_id=getattr(request.state, "request_id", None),
        )
    token, expires = sessions.issue(
        settings, user_id=body.user_id, institution_id=institution_id, method="dev"
    )
    return DevLoginResponse(
        token=token, expires_at=expires, user_id=body.user_id, institution_id=institution_id
    )
