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

from sqlalchemy import ColumnElement, and_, false, or_, select
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
    from sqlalchemy import func, or_

    rows = db.execute(
        select(Membership.role, Membership.scope_type, Membership.scope_id).where(
            Membership.user_id == user_id,
            Membership.revoked_at.is_(None),
            or_(Membership.expires_at.is_(None), Membership.expires_at > func.now()),
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
    """Issuers this actor may author under for ``course`` (spec §2.2: no impersonation).

    Only active issuers in org units that may issue (spec §10.3), and none at all for a course
    in a department that may not issue.
    """
    if course is not None and not org_unit_may_issue(db, course.org_unit_id):
        return []
    issuers = [
        i
        for i in db.scalars(select(Issuer).where(Issuer.status == "active")).all()
        if org_unit_may_issue(db, i.org_unit_id)
    ]
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


# ---- W7: governance ----------------------------------------------------------------------------

#: Roles a policy may name as definition approvers or credential revokers.
APPROVER_ROLES = ("lecturer", "dept_admin", "inst_admin")
REVOKER_ROLES = ("lecturer", "issuer_manager", "dept_admin", "inst_admin")
#: Roles a department administrator may delegate inside their own org units (spec §2.3).
DEPT_GRANTABLE = ("lecturer", "course_admin", "issuer_manager", "dept_admin")
#: Roles granted in OpenCredential itself. Students come from Canvas enrolments only.
GRANTABLE = (*DEPT_GRANTABLE, "inst_admin")


def is_admin(actor: Actor) -> bool:
    """Any administrative role: institution admin, or department admin somewhere."""
    return actor.is_inst_admin or actor.has("dept_admin", "org_unit")


def require_admin(actor: Actor) -> None:
    if not is_admin(actor):
        raise Forbidden("FORBIDDEN", "Only administrators can do that.")


def org_subtree(db: Session, roots: set[uuid.UUID]) -> set[uuid.UUID]:
    """``roots`` and every org unit below them."""
    units = db.execute(select(OrgUnit.id, OrgUnit.parent_id)).all()
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for uid, parent in units:
        children.setdefault(parent, []).append(uid)
    out: set[uuid.UUID] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


def admin_org_units(db: Session, actor: Actor) -> set[uuid.UUID] | None:
    """Org units this actor administers (``None`` means the whole institution)."""
    if actor.is_inst_admin:
        return None
    roots = {sid for r, st, sid in actor.memberships if r == "dept_admin" and st == "org_unit"}
    return org_subtree(db, roots) if roots else set()


def admin_course_ids(db: Session, actor: Actor) -> set[uuid.UUID] | None:
    """Courses inside this actor's administrative scope (``None`` means all)."""
    units = admin_org_units(db, actor)
    if units is None:
        return None
    if not units:
        return set()
    return set(db.scalars(select(Course.id).where(Course.org_unit_id.in_(units))))


def award_list_scope(db: Session, actor: Actor) -> ColumnElement[bool] | None:
    """SQL filter on ``AchievementDefinition`` for the awards a staff member may list.

    The same rule as the per-row check in the awards list: course badges need course staff
    (or a department admin over the course); badges without a course need their owner or a
    department admin over the issuer. ``None`` means no filter (institution admin). Applying
    it in SQL keeps ``limit`` honest: other courses' awards no longer use up the page.
    """
    if actor.is_inst_admin:
        return None
    units = admin_org_units(db, actor) or set()
    courses = set(actor.course_ids(COURSE_STAFF)) | (admin_course_ids(db, actor) or set())
    course_clause = AchievementDefinition.course_id.in_(courses) if courses else false()
    standalone = [AchievementDefinition.owner_user_id == actor.user_id]
    if units:
        standalone.append(
            AchievementDefinition.issuer_id.in_(
                select(Issuer.id).where(Issuer.org_unit_id.in_(units))
            )
        )
    return or_(
        and_(AchievementDefinition.course_id.is_not(None), course_clause),
        and_(AchievementDefinition.course_id.is_(None), or_(*standalone)),
    )


def can_manage_org_unit(db: Session, actor: Actor, org_unit_id: uuid.UUID | None) -> bool:
    if actor.is_inst_admin:
        return True
    return org_unit_id is not None and is_dept_admin_over(db, actor, org_unit_id)


def require_manage_org_unit(db: Session, actor: Actor, org_unit_id: uuid.UUID | None) -> None:
    if not can_manage_org_unit(db, actor, org_unit_id):
        raise Forbidden("OUT_OF_SCOPE", "That is outside the part of the institution you manage.")


def org_unit_may_issue(db: Session, org_unit_id: uuid.UUID | None) -> bool:
    """Spec §10.3: a unit can issue only if it and every unit above it may (and are active)."""
    for uid in _org_chain(db, org_unit_id):
        unit = db.get(OrgUnit, uid)
        if unit is None or not unit.may_issue or unit.status != "active":
            return False
    return True


def require_issuing_allowed(db: Session, issuer: Issuer, course: Course | None) -> None:
    if not org_unit_may_issue(db, issuer.org_unit_id):
        raise Forbidden(
            "ISSUING_NOT_ALLOWED",
            "This issuer belongs to a department that is not allowed to issue credentials.",
        )
    if course is not None and not org_unit_may_issue(db, course.org_unit_id):
        raise Forbidden(
            "ISSUING_NOT_ALLOWED",
            "This course belongs to a department that is not allowed to issue credentials.",
        )


def can_grant(
    db: Session,
    actor: Actor,
    role: str,
    scope_type: str,
    scope_org_unit: uuid.UUID | None,
    policy: dict[str, Any],
) -> bool:
    """Who may grant ``role`` at a scope whose org unit is ``scope_org_unit`` (spec §2.3/§2.4)."""
    if role not in GRANTABLE:
        return False
    if actor.is_inst_admin:
        return True
    if role not in DEPT_GRANTABLE or not policy.get("dept_admins_may_delegate", True):
        return False
    if scope_type == "institution":
        return False
    return scope_org_unit is not None and is_dept_admin_over(db, actor, scope_org_unit)


def can_revoke(
    db: Session,
    actor: Actor,
    issuer: Issuer,
    course: Course | None,
    policy: dict[str, Any],
) -> bool:
    """Spec §10.3 "who may revoke credentials": roles in ``policy["revokers"]``, each within the
    scope it holds. Institution administrators can always revoke."""
    if actor.is_inst_admin:
        return True
    roles = set(policy.get("revokers") or ["inst_admin"])
    if "dept_admin" in roles:
        units = [issuer.org_unit_id, course.org_unit_id if course else None]
        if any(u and is_dept_admin_over(db, actor, u) for u in units):
            return True
    if "issuer_manager" in roles and actor.has("issuer_manager", "issuer", issuer.id):
        return True
    return bool(
        "lecturer" in roles and course is not None and actor.course_roles(course.id) & COURSE_STAFF
    )
