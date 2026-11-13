# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/learners/me``: who am I, in which institution, with which roles."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from opencredential.api.deps import ClaimsDep, TenantDb
from opencredential.api.errors import ApiError
from opencredential.db.models import Course, Institution, Membership, User

router = APIRouter(prefix="/api/v1/learners", tags=["learners"])


class MembershipOut(BaseModel):
    role: str
    scope_type: str
    scope_id: uuid.UUID
    scope_name: str | None


class InstitutionOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    is_demo: bool


class MeOut(BaseModel):
    id: uuid.UUID
    display_name: str | None
    institution: InstitutionOut
    memberships: list[MembershipOut]
    session_method: str


@router.get("/me", response_model=MeOut)
def me(claims: ClaimsDep, db: TenantDb) -> MeOut:
    user = db.get(User, claims.user_id)
    institution = db.get(Institution, claims.institution_id)
    if user is None or institution is None or user.status != "active":
        raise ApiError(401, "SESSION_INVALID", "Your account is no longer active")
    rows = db.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.revoked_at.is_(None))
    ).all()
    course_ids = [m.scope_id for m in rows if m.scope_type == "course"]
    course_names = {
        c.id: c.title for c in db.scalars(select(Course).where(Course.id.in_(course_ids)))
    }
    memberships = [
        MembershipOut(
            role=m.role,
            scope_type=m.scope_type,
            scope_id=m.scope_id,
            scope_name=(
                course_names.get(m.scope_id)
                if m.scope_type == "course"
                else institution.name
                if m.scope_type == "institution"
                else None
            ),
        )
        for m in rows
    ]
    return MeOut(
        id=user.id,
        display_name=user.display_name,
        institution=InstitutionOut(
            id=institution.id,
            slug=institution.slug,
            name=institution.name,
            is_demo=institution.is_demo,
        ),
        memberships=memberships,
        session_method=claims.method,
    )
