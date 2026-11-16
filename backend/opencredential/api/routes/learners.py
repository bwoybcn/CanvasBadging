# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/learners/me``: who am I, in which institution, with which roles."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from opencredential.api.deps import ClaimsDep, TenantDb
from opencredential.api.errors import ApiError
from opencredential.authz import policy
from opencredential.db.models import Course, Institution, Membership, User
from opencredential.eligibility import progress
from opencredential.sync import lifecycle

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


class LaunchCourseOut(BaseModel):
    """The Canvas course this session was launched from (LTI sessions only)."""

    id: uuid.UUID
    title: str
    course_code: str | None
    canvas_course_id: str
    status: str
    roles: list[str]
    #: ``lecturer`` view for course staff, ``student`` view otherwise (spec §4.1).
    view: str
    #: When the course ended in Canvas, if it has, and when it stops (or stopped) being read.
    ended_at: datetime | None = None
    read_until: datetime | None = None


class HelpOut(BaseModel):
    """Who to ask for help with badges here, as set by an institution administrator."""

    contact_name: str | None = None
    email: str | None = None
    url: str | None = None


class MeOut(BaseModel):
    id: uuid.UUID
    display_name: str | None
    email: str | None = None
    institution: InstitutionOut
    memberships: list[MembershipOut]
    session_method: str
    launch_course: LaunchCourseOut | None = None
    #: Canvas account administrator without an OpenCredential administrator role: the app
    #: explains how to get one. Grants nothing (ADR-0013).
    canvas_admin_without_access: bool = False
    #: Who to ask for that access (institution administrators' names), only in that case.
    institution_admins: list[str] = []
    #: Whether to offer the Review queue: this person can be the approver of some badge under
    #: the institution's policy. Decided here so the screens keep no role list of their own.
    may_review: bool = False
    help: HelpOut = HelpOut()


@router.get("/me", response_model=MeOut)
def me(claims: ClaimsDep, db: TenantDb) -> MeOut:
    user = db.get(User, claims.user_id)
    institution = db.get(Institution, claims.institution_id)
    if user is None or institution is None or user.status != "active":
        raise ApiError(401, "SESSION_INVALID", "Your account is no longer active")
    rows = db.scalars(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.revoked_at.is_(None),
            # The same rule as ``policy.load_actor``: a role past its end date is not held.
            or_(Membership.expires_at.is_(None), Membership.expires_at > func.now()),
        )
    ).all()
    actor = policy.load_actor(db, user.id, institution.id)
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
    launch_course = None
    if claims.course_id is not None:
        course = db.get(Course, claims.course_id)
        if course is not None:
            roles = sorted(
                m.role for m in rows if m.scope_type == "course" and m.scope_id == course.id
            )
            launch_course = LaunchCourseOut(
                id=course.id,
                title=course.title,
                course_code=course.course_code,
                canvas_course_id=course.canvas_course_id,
                status=course.status,
                roles=roles,
                view="lecturer" if set(roles) & policy.COURSE_STAFF else "student",
                ended_at=course.ended_at,
                read_until=lifecycle.read_until(db, course),
            )
    canvas_admin_without_access = claims.platform_admin and not any(
        m.role == "inst_admin" for m in rows
    )
    institution_admins: list[str] = []
    if canvas_admin_without_access:
        institution_admins = sorted(
            name
            for name in db.scalars(
                select(User.display_name)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    Membership.institution_id == claims.institution_id,
                    Membership.role == "inst_admin",
                    Membership.revoked_at.is_(None),
                    User.status == "active",
                )
            )
            if name
        )
    return MeOut(
        id=user.id,
        canvas_admin_without_access=canvas_admin_without_access,
        institution_admins=institution_admins,
        display_name=user.display_name,
        email=user.email,
        launch_course=launch_course,
        institution=InstitutionOut(
            id=institution.id,
            slug=institution.slug,
            name=institution.name,
            is_demo=institution.is_demo,
        ),
        memberships=memberships,
        session_method=claims.method,
        help=HelpOut(
            contact_name=institution.help_contact_name,
            email=institution.help_email,
            url=institution.help_url,
        ),
        may_review=policy.may_review_some(actor, policy.institution_policy(db, institution.id)),
    )


@router.get("/me/achievements")
def my_achievements(claims: ClaimsDep, db: TenantDb) -> list[dict[str, Any]]:
    """Badges available in my courses with per-requirement progress (spec §8.1-8.2).

    Computed from the latest synced Canvas data without recording anything. ``confirmed`` marks
    requirements the data confirms; pending ones say what they are waiting for.
    """
    actor = policy.load_actor(db, claims.user_id, claims.institution_id)
    return progress.learner_achievements(db, actor.user_id, actor.course_ids({"student"}))
