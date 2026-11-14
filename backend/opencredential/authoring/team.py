# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge teams in shared courses (extracurricular badges, PR 3 of 4).

A recognition course for a library or a faculty's CPD has many staff. With the course's
``badge_teams`` switch on, each badge is edited and awarded only by its owner, its team and
administrators over the course; other staff in the course can still see it. Team members must be
staff (lecturer or course admin) in the badge's course.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementTeamMember,
    Course,
    Membership,
    User,
)
from opencredential.errors import Forbidden, Invalid, NotFound

TEAM_ROLES = ("editor", "awarder")


def _course(db: Session, definition: AchievementDefinition) -> Course:
    course = authz.definition_course(db, definition)
    if course is None:
        raise Invalid("COURSE_REQUIRED", "Badge teams apply to badges in a Canvas course.")
    return course


def course_staff(db: Session, course_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Membership.user_id)
            .where(
                Membership.scope_type == "course",
                Membership.scope_id == course_id,
                Membership.role.in_(tuple(authz.COURSE_STAFF)),
                Membership.revoked_at.is_(None),
            )
            .distinct()
        )
    )


def team_out(db: Session, actor: authz.Actor, definition: AchievementDefinition) -> dict[str, Any]:
    course = authz.definition_course(db, definition)
    rows = db.scalars(
        select(AchievementTeamMember).where(AchievementTeamMember.definition_id == definition.id)
    ).all()

    def name(uid: uuid.UUID) -> str | None:
        u = db.get(User, uid)
        return u.display_name if u else None

    members = [
        {
            "user_id": str(definition.owner_user_id),
            "name": name(definition.owner_user_id),
            "role": "owner",
        },
        *({"user_id": str(r.user_id), "name": name(r.user_id), "role": r.role} for r in rows),
    ]
    on_team = {definition.owner_user_id, *(r.user_id for r in rows)}
    candidates = (
        [
            {"user_id": str(uid), "name": name(uid)}
            for uid in course_staff(db, course.id)
            if uid not in on_team
        ]
        if course is not None
        else []
    )
    return {
        "enabled": bool(course and course.badge_teams),
        "members": members,
        "candidates": sorted(candidates, key=lambda c: (c["name"] or "").lower()),
        "can_manage": authz.can_edit_definition(db, actor, definition),
    }


def set_member(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    user_id: uuid.UUID,
    role: str,
    request_id: str | None = None,
) -> None:
    authz.require_edit(db, actor, definition)
    course = _course(db, definition)
    if role not in TEAM_ROLES:
        raise Invalid("ROLE_INVALID", "Choose editor or awarder.")
    if user_id == definition.owner_user_id:
        raise Invalid("OWNER_ALWAYS_ON_TEAM", "The badge's owner is always on its team.")
    if user_id not in course_staff(db, course.id):
        raise Invalid("NOT_COURSE_STAFF", "Only staff in this course can join a badge's team.")
    row = db.scalar(
        select(AchievementTeamMember).where(
            AchievementTeamMember.definition_id == definition.id,
            AchievementTeamMember.user_id == user_id,
        )
    )
    if row is None:
        db.add(
            AchievementTeamMember(
                institution_id=actor.institution_id,
                definition_id=definition.id,
                user_id=user_id,
                role=role,
                added_by=actor.user_id,
            )
        )
    elif row.role == role:
        return
    else:
        row.role = role
    audit.record(
        db,
        action="achievement.team_set",
        resource_type="achievement_definition",
        resource_id=definition.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"user_id": str(user_id), "role": role},
    )


def remove_member(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    user_id: uuid.UUID,
    request_id: str | None = None,
) -> None:
    authz.require_edit(db, actor, definition)
    row = db.scalar(
        select(AchievementTeamMember).where(
            AchievementTeamMember.definition_id == definition.id,
            AchievementTeamMember.user_id == user_id,
        )
    )
    if row is None:
        raise NotFound("NOT_FOUND", "That person is not on this badge's team.")
    db.delete(row)
    audit.record(
        db,
        action="achievement.team_remove",
        resource_type="achievement_definition",
        resource_id=definition.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"user_id": str(user_id)},
    )


def set_course_badge_teams(
    db: Session, actor: authz.Actor, course: Course, enabled: bool, request_id: str | None = None
) -> Course:
    """Any lecturer or admin can switch badge teams on; only an administrator over the course can
    switch them off again, since that opens every badge to every member of staff."""
    is_admin = actor.is_inst_admin or authz.is_dept_admin_over(db, actor, course.org_unit_id)
    is_staff = bool(actor.course_roles(course.id) & authz.COURSE_STAFF)
    if not (is_admin or is_staff):
        raise Forbidden("FORBIDDEN", "Only staff in this course can change this.")
    if not enabled and course.badge_teams and not is_admin:
        raise Forbidden(
            "BADGE_TEAMS_ADMIN_ONLY",
            "Only an administrator can switch badge teams off, because that lets every member "
            "of staff in the course edit and award every badge.",
        )
    if course.badge_teams != enabled:
        course.badge_teams = enabled
        audit.record(
            db,
            action="course.badge_teams",
            resource_type="course",
            resource_id=course.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"enabled": enabled},
        )
    return course
