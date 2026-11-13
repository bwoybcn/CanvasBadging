# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scoped role checks (ADR-0013). Every route asks this module; nothing bypasses it.

Roles are always read from ``memberships`` for the current request, so a revoked role stops
working immediately. Scopes:

* ``inst_admin`` (institution): everything in the tenant.
* ``dept_admin`` (org unit): review, awards and progress for courses and issuers in that org
  unit or any org unit below it.
* ``lecturer`` / ``course_admin`` (course): author, award and view progress in that course.
* ``student`` (course): own progress only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.db.models import (
    AchievementDefinition,
    Course,
    Institution,
    Issuer,
    IssuerDelegation,
    Membership,
    OrgUnit,
)
from opencredential.db.models.tenancy import DEFAULT_POLICY
from opencredential.errors import Forbidden

COURSE_STAFF = {"lecturer", "course_admin"}


@dataclass
class Actor:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    memberships: list[tuple[str, str, uuid.UUID]] = field(default_factory=list)

    def has(
        self, role: str, scope_type: str | None = None, scope_id: uuid.UUID | None = None
    ) -> bool:
        return any(
            r == role
            and (scope_type is None or st == scope_type)
            and (scope_id is None or sid == scope_id)
            for r, st, sid in self.memberships
        )

    @property
    def is_inst_admin(self) -> bool:
        return self.has("inst_admin", "institution")

    def course_roles(self, course_id: uuid.UUID) -> set[str]:
        return {r for r, st, sid in self.memberships if st == "course" and sid == course_id}

    def course_ids(self, roles: set[str]) -> set[uuid.UUID]:
        return {sid for r, st, sid in self.memberships if st == "course" and r in roles}


def load_actor(db: Session, user_id: uuid.UUID, institution_id: uuid.UUID) -> Actor:
    rows = db.execute(
        select(Membership.role, Membership.scope_type, Membership.scope_id).where(
            Membership.user_id == user_id, Membership.revoked_at.is_(None)
        )
    ).all()
    return Actor(user_id, institution_id, [(r, st, sid) for r, st, sid in rows])


def institution_policy(db: Session, institution_id: uuid.UUID) -> dict[str, Any]:
    inst = db.get(Institution, institution_id)
    return {**DEFAULT_POLICY, **(inst.policy if inst else {})}


def _org_chain(db: Session, org_unit_id: uuid.UUID | None) -> list[uuid.UUID]:
    """``org_unit_id`` and its ancestors (bounded, cycle-safe)."""
    chain: list[uuid.UUID] = []
    current = org_unit_id
    while current is not None and current not in chain and len(chain) < 16:
        chain.append(current)
        unit = db.get(OrgUnit, current)
        current = unit.parent_id if unit else None
    return chain


def is_dept_admin_over(db: Session, actor: Actor, org_unit_id: uuid.UUID | None) -> bool:
    return any(actor.has("dept_admin", "org_unit", ou) for ou in _org_chain(db, org_unit_id))


# ---- course-level ------------------------------------------------------------------------------


def is_course_staff(db: Session, actor: Actor, course: Course | None) -> bool:
    if actor.is_inst_admin:
        return True
    if course is None:
        return False
    if actor.course_roles(course.id) & COURSE_STAFF:
        return True
    return is_dept_admin_over(db, actor, course.org_unit_id)


def require_course_staff(db: Session, actor: Actor, course: Course | None) -> None:
    if not is_course_staff(db, actor, course):
        raise Forbidden("FORBIDDEN", "Only staff for this course can do that.")


def is_student_in(actor: Actor, course_id: uuid.UUID) -> bool:
    return "student" in actor.course_roles(course_id)


# ---- definitions ---------------------------------------------------------------------------------


def definition_course(db: Session, definition: AchievementDefinition) -> Course | None:
    return db.get(Course, definition.course_id) if definition.course_id else None


def can_edit_definition(db: Session, actor: Actor, definition: AchievementDefinition) -> bool:
    if actor.user_id == definition.owner_user_id or actor.is_inst_admin:
        return True
    course = definition_course(db, definition)
    if course is not None:
        return is_course_staff(db, actor, course)
    issuer = db.get(Issuer, definition.issuer_id)
    return is_dept_admin_over(db, actor, issuer.org_unit_id if issuer else None)


def require_edit(db: Session, actor: Actor, definition: AchievementDefinition) -> None:
    if not can_edit_definition(db, actor, definition):
        raise Forbidden("FORBIDDEN", "You cannot change this badge.")


def can_review(
    db: Session, actor: Actor, definition: AchievementDefinition, policy: dict[str, Any]
) -> bool:
    roles = set(policy.get("approver_roles") or ["dept_admin", "inst_admin"])
    if "inst_admin" in roles and actor.is_inst_admin:
        return True
    if "dept_admin" in roles:
        course = definition_course(db, definition)
        issuer = db.get(Issuer, definition.issuer_id)
        units = [course.org_unit_id if course else None, issuer.org_unit_id if issuer else None]
        if any(is_dept_admin_over(db, actor, u) for u in units if u):
            return True
    if "lecturer" in roles:
        return can_edit_definition(db, actor, definition)
    return False


def require_review(
    db: Session, actor: Actor, definition: AchievementDefinition, policy: dict[str, Any]
) -> None:
    if not can_review(db, actor, definition, policy):
        raise Forbidden("FORBIDDEN", "You are not an approver for this badge.")
    if actor.user_id == definition.owner_user_id and not policy.get("self_approval_allowed"):
        raise Forbidden(
            "SELF_APPROVAL_NOT_ALLOWED",
            "Your institution requires someone else to approve badges you created.",
        )


# ---- issuers -------------------------------------------------------------------------------------


def usable_issuers(db: Session, actor: Actor, course: Course | None) -> list[Issuer]:
    """Issuers this actor may author under for ``course`` (spec §2.2: no impersonation)."""
    issuers = db.scalars(select(Issuer).where(Issuer.status == "active")).all()
    if actor.is_inst_admin:
        return list(issuers)
    org_chain = _org_chain(db, course.org_unit_id) if course else []
    delegations = db.scalars(
        select(IssuerDelegation).where(IssuerDelegation.revoked_at.is_(None))
    ).all()
    allowed = set()
    for d in delegations:
        if (d.scope_type == "course" and course is not None and d.scope_id == course.id) or (
            d.scope_type == "org_unit" and d.scope_id in org_chain
        ):
            allowed.add(d.issuer_id)
    for i in issuers:
        if is_dept_admin_over(db, actor, i.org_unit_id):
            allowed.add(i.id)
    return [i for i in issuers if i.id in allowed]


def require_issuer(
    db: Session, actor: Actor, issuer_id: uuid.UUID, course: Course | None
) -> Issuer:
    for issuer in usable_issuers(db, actor, course):
        if issuer.id == issuer_id:
            return issuer
    raise Forbidden(
        "ISSUER_NOT_DELEGATED",
        "This issuer has not been delegated to your course or department.",
    )


# ---- institution -------------------------------------------------------------------------------


def require_inst_admin(actor: Actor) -> None:
    if not actor.is_inst_admin:
        raise Forbidden("FORBIDDEN", "Only institution administrators can do that.")
