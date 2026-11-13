# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn a validated launch into OpenCredential records: user, Canvas identities, course and
course memberships (spec §4.1, §12.2, ADR-0013).

* Users are found by the LTI ``sub`` for this Canvas integration, never by email.
* Course roles come only from the signed launch (or NRPS). Roles held through LTI that Canvas no
  longer reports for this course are revoked; roles granted in the app are never touched.
* A course row is created on first launch and stays ``inactive`` until staff activate it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import Course, ExternalIdentity, Membership, User
from opencredential.lti.claims import LaunchData

LTI_SOURCES = ("lti", "nrps")


@dataclass(frozen=True)
class Provisioned:
    user_id: uuid.UUID
    course_id: uuid.UUID
    course_roles: frozenset[str]
    created_user: bool
    created_course: bool


def find_user(db: Session, integration_id: uuid.UUID, kind: str, value: str) -> uuid.UUID | None:
    return db.scalar(
        select(ExternalIdentity.user_id).where(
            ExternalIdentity.canvas_integration_id == integration_id,
            ExternalIdentity.kind == kind,
            ExternalIdentity.value == value,
        )
    )


def link_identity(
    db: Session,
    institution_id: uuid.UUID,
    integration_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    value: str | None,
) -> None:
    if not value:
        return
    row = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.canvas_integration_id == integration_id,
            ExternalIdentity.kind == kind,
            ExternalIdentity.value == value,
        )
    )
    if row is None:
        # A user has one value per kind; replace a stale one (e.g. a merged Canvas account).
        old = db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.canvas_integration_id == integration_id,
                ExternalIdentity.kind == kind,
                ExternalIdentity.user_id == user_id,
            )
        )
        if old is not None:
            old.value = value
        else:
            db.add(
                ExternalIdentity(
                    institution_id=institution_id,
                    canvas_integration_id=integration_id,
                    user_id=user_id,
                    kind=kind,
                    value=value,
                )
            )
    elif row.user_id != user_id:
        raise ValueError(f"{kind} already belongs to another user")


def upsert_user(
    db: Session,
    institution_id: uuid.UUID,
    integration_id: uuid.UUID,
    *,
    sub: str,
    canvas_user_id: str | None,
    name: str | None,
    given_name: str | None,
    family_name: str | None,
    email: str | None,
    verified_by: str,
) -> tuple[User, bool]:
    user_id = find_user(db, integration_id, "lti_sub", sub)
    created = False
    if user_id is None and canvas_user_id:
        user_id = find_user(db, integration_id, "canvas_user_id", canvas_user_id)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        user = User(institution_id=institution_id, status="active")
        db.add(user)
        db.flush()
        created = True
    if user.status == "deleted":
        raise PermissionError("USER_ERASED")
    # Canvas is the source of truth for names and email; only overwrite with real values.
    if name:
        user.display_name = name
    if given_name:
        user.given_name = given_name
    if family_name:
        user.family_name = family_name
    if email:
        user.email, user.email_verified_by = email, verified_by
    link_identity(db, institution_id, integration_id, user.id, "lti_sub", sub)
    link_identity(db, institution_id, integration_id, user.id, "canvas_user_id", canvas_user_id)
    return user, created


def upsert_course(
    db: Session,
    institution_id: uuid.UUID,
    integration_id: uuid.UUID,
    launch: LaunchData,
) -> tuple[Course, bool]:
    canvas_course_id = launch.canvas_course_id or f"lti:{launch.context_id}"
    course = db.scalar(
        select(Course).where(
            Course.canvas_integration_id == integration_id,
            Course.canvas_course_id == canvas_course_id,
        )
    )
    if course is None:
        course = db.scalar(
            select(Course).where(
                Course.canvas_integration_id == integration_id,
                Course.lti_context_id == launch.context_id,
            )
        )
    created = False
    if course is None:
        course = Course(
            institution_id=institution_id,
            canvas_integration_id=integration_id,
            canvas_course_id=canvas_course_id,
            title=launch.context_title or launch.context_label or "Untitled course",
            status="inactive",
        )
        db.add(course)
        created = True
    elif course.lti_context_id and course.lti_context_id != launch.context_id:
        raise PermissionError("COURSE_CONTEXT_CONFLICT")
    course.lti_context_id = launch.context_id
    if launch.canvas_course_id and course.canvas_course_id.startswith("lti:"):
        course.canvas_course_id = launch.canvas_course_id
    if launch.context_title:
        course.title = launch.context_title
    if launch.context_label:
        course.course_code = launch.context_label
    if launch.nrps_url:
        course.lti_nrps_url = launch.nrps_url
    course.lti_resource_link_id = launch.resource_link_id
    db.flush()
    return course, created


def set_course_roles(
    db: Session,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    roles: frozenset[str] | set[str],
    *,
    source: str,
    now: datetime | None = None,
) -> tuple[set[str], set[str]]:
    """Make the user's Canvas-derived roles in this course exactly ``roles``.

    Returns ``(added, revoked)``. Rows granted in the app (``source='grant'``) are left alone.
    """
    now = now or datetime.now(UTC)
    current = list(
        db.scalars(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.scope_type == "course",
                Membership.scope_id == course_id,
                Membership.revoked_at.is_(None),
            )
        )
    )
    have = {m.role for m in current}
    added: set[str] = set()
    revoked: set[str] = set()
    for role in sorted(set(roles) - have):
        db.add(
            Membership(
                institution_id=institution_id,
                user_id=user_id,
                scope_type="course",
                scope_id=course_id,
                role=role,
                source=source,
            )
        )
        added.add(role)
    for m in current:
        if m.role not in roles and m.source in LTI_SOURCES:
            m.revoked_at = now
            revoked.add(m.role)
    return added, revoked


def provision_launch(
    db: Session,
    institution_id: uuid.UUID,
    integration_id: uuid.UUID,
    launch: LaunchData,
    *,
    request_id: str | None = None,
) -> Provisioned:
    user, created_user = upsert_user(
        db,
        institution_id,
        integration_id,
        sub=launch.subject,
        canvas_user_id=launch.canvas_user_id,
        name=launch.name,
        given_name=launch.given_name,
        family_name=launch.family_name,
        email=launch.email,
        verified_by="lti",
    )
    course, created_course = upsert_course(db, institution_id, integration_id, launch)
    added, revoked = set_course_roles(
        db, institution_id, user.id, course.id, launch.course_roles, source="lti"
    )
    audit.record(
        db,
        action="session.lti_launch",
        resource_type="course",
        resource_id=course.id,
        institution_id=institution_id,
        actor_user_id=user.id,
        request_id=request_id,
        data={
            "roles": sorted(launch.course_roles),
            "roles_added": sorted(added),
            "roles_revoked": sorted(revoked),
            "deployment_id": launch.deployment_id,
            "new_user": created_user,
            "new_course": created_course,
            "test_user": launch.is_test_user,
        },
    )
    return Provisioned(
        user_id=user.id,
        course_id=course.id,
        course_roles=launch.course_roles,
        created_user=created_user,
        created_course=created_course,
    )
