# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organisation structure and delegated administrative permissions (spec §2.3, §2.4, §10.3).

* Institution administrators grant any staff role anywhere, including ``inst_admin``.
* Department administrators grant ``lecturer``, ``course_admin``, ``issuer_manager`` and
  ``dept_admin`` only inside the org units they administer, and only while the institution
  policy ``dept_admins_may_delegate`` is on.
* Student roles come from Canvas enrolments and cannot be granted here.
* Nobody can remove the institution's last administrator.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import Course, Issuer, Membership, OrgUnit, User
from opencredential.errors import Conflict, Forbidden, Invalid, NotFound

ORG_KINDS = ("faculty", "department", "programme", "service", "other")


# ---- org units ------------------------------------------------------------------------------


def org_unit_out(db: Session, unit: OrgUnit) -> dict[str, Any]:
    return {
        "id": str(unit.id),
        "name": unit.name,
        "kind": unit.kind,
        "parent_id": str(unit.parent_id) if unit.parent_id else None,
        "may_issue": unit.may_issue,
        "effective_may_issue": authz.org_unit_may_issue(db, unit.id),
        "status": unit.status,
        "review_policy": dict(unit.review_policy or {}),
        "effective_review": _effective_review_out(db, unit),
    }


def _effective_review_out(db: Session, unit: OrgUnit) -> dict[str, Any]:
    eff = authz.review_settings(db, unit.institution_id, unit.id)
    return {
        **{k: eff[k] for k in authz.AREA_REVIEW_KEYS},
        "sources": {k: str(v) if v else None for k, v in eff["sources"].items()},
    }


def _clean_review_policy(
    db: Session, actor: authz.Actor, unit: OrgUnit, value: Any
) -> dict[str, Any]:
    """Merge a partial review-policy change into ``unit``'s overrides. ``None`` clears a key
    (inherit again). Refuses less strict settings when the institution does not allow them."""
    if not isinstance(value, dict):
        raise Invalid("REVIEW_POLICY_INVALID", "Review settings must be an object.")
    unknown = set(value) - set(authz.AREA_REVIEW_KEYS)
    if unknown:
        raise Invalid(
            "REVIEW_POLICY_INVALID", "Unknown review setting: " + ", ".join(sorted(unknown)) + "."
        )
    policy = authz.institution_policy(db, actor.institution_id)
    base = authz.institution_review_settings(policy)
    merged = dict(unit.review_policy or {})
    for key, v in value.items():
        if v is None:
            merged.pop(key, None)
            continue
        if key == "definition_review":
            if v not in authz.REVIEW_MODES:
                raise Invalid(
                    "REVIEW_POLICY_INVALID",
                    "Review must be one of: " + ", ".join(authz.REVIEW_MODES) + ".",
                )
        elif not isinstance(v, bool):
            raise Invalid("REVIEW_POLICY_INVALID", f"{key} must be true or false.")
        if not policy.get("areas_may_relax_review", False) and authz.relaxes(key, v, base[key]):
            raise Forbidden(
                "REVIEW_RELAX_NOT_ALLOWED",
                "Your institution does not let areas set review less strictly than its own policy.",
            )
        merged[key] = v
    return merged


def list_org_units(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    authz.require_admin(actor)
    scope = authz.admin_org_units(db, actor)
    units = db.scalars(select(OrgUnit).order_by(OrgUnit.name)).all()
    return [{**org_unit_out(db, u), "manageable": scope is None or u.id in scope} for u in units]


def create_org_unit(
    db: Session,
    actor: authz.Actor,
    *,
    name: str,
    kind: str,
    parent_id: uuid.UUID | None,
    request_id: str | None = None,
) -> OrgUnit:
    if parent_id is None:
        authz.require_inst_admin(actor)
    else:
        if db.get(OrgUnit, parent_id) is None:
            raise NotFound("ORG_UNIT_NOT_FOUND", "No such parent unit.")
        authz.require_manage_org_unit(db, actor, parent_id)
    if kind not in ORG_KINDS:
        raise Invalid("KIND_INVALID", f"Kind must be one of: {', '.join(ORG_KINDS)}.")
    name = (name or "").strip()
    if not 2 <= len(name) <= 200:
        raise Invalid("NAME_INVALID", "The name must be 2 to 200 characters.")
    unit = OrgUnit(institution_id=actor.institution_id, name=name, kind=kind, parent_id=parent_id)
    db.add(unit)
    db.flush()
    audit.record(
        db,
        action="org_unit.create",
        resource_type="org_unit",
        resource_id=unit.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"parent_id": str(parent_id) if parent_id else None},
    )
    return unit


def update_org_unit(
    db: Session,
    actor: authz.Actor,
    unit_id: uuid.UUID,
    changes: dict[str, Any],
    request_id: str | None = None,
) -> OrgUnit:
    unit = db.get(OrgUnit, unit_id)
    if unit is None:
        raise NotFound("ORG_UNIT_NOT_FOUND", "No such unit.")
    authz.require_manage_org_unit(db, actor, unit.id)
    if ("may_issue" in changes or "parent_id" in changes) and not actor.is_inst_admin:
        raise Forbidden(
            "FORBIDDEN",
            "Only institution administrators decide which units may issue or move units.",
        )
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not 2 <= len(name) <= 200:
            raise Invalid("NAME_INVALID", "The name must be 2 to 200 characters.")
        unit.name = name
    if "kind" in changes:
        if changes["kind"] not in ORG_KINDS:
            raise Invalid("KIND_INVALID", f"Kind must be one of: {', '.join(ORG_KINDS)}.")
        unit.kind = changes["kind"]
    if "parent_id" in changes:
        parent = changes["parent_id"]
        if parent is not None:
            if parent == unit.id or parent in authz.org_subtree(db, {unit.id}):
                raise Invalid("PARENT_INVALID", "A unit cannot sit inside itself.")
            if db.get(OrgUnit, parent) is None:
                raise NotFound("ORG_UNIT_NOT_FOUND", "No such parent unit.")
        unit.parent_id = parent
    if "may_issue" in changes:
        unit.may_issue = bool(changes["may_issue"])
    if "status" in changes:
        if changes["status"] not in ("active", "archived"):
            raise Invalid("STATUS_INVALID", "Status must be active or archived.")
        unit.status = changes["status"]
    review_change: dict[str, Any] | None = None
    if "review_policy" in changes:
        before = dict(unit.review_policy or {})
        unit.review_policy = _clean_review_policy(db, actor, unit, changes["review_policy"] or {})
        review_change = {"from": before, "to": dict(unit.review_policy)}
    audit.record(
        db,
        action="org_unit.update",
        resource_type="org_unit",
        resource_id=unit.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "fields": sorted(changes),
            **({"may_issue": unit.may_issue} if "may_issue" in changes else {}),
            **({"review_policy": review_change} if review_change is not None else {}),
        },
    )
    return unit


def assign_course(
    db: Session,
    actor: authz.Actor,
    course_id: uuid.UUID,
    org_unit_id: uuid.UUID | None,
    request_id: str | None = None,
) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise NotFound("COURSE_NOT_FOUND", "No such course.")
    if not actor.is_inst_admin:
        authz.require_manage_org_unit(db, actor, course.org_unit_id)
        authz.require_manage_org_unit(db, actor, org_unit_id)
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise NotFound("ORG_UNIT_NOT_FOUND", "No such unit.")
    old = course.org_unit_id
    course.org_unit_id = org_unit_id
    audit.record(
        db,
        action="course.org_unit",
        resource_type="course",
        resource_id=course.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"from": str(old) if old else None, "to": str(org_unit_id) if org_unit_id else None},
    )
    return course


def list_courses(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    authz.require_admin(actor)
    allowed = authz.admin_course_ids(db, actor)
    q = select(Course).order_by(Course.title)
    out = []
    for c in db.scalars(q):
        if allowed is not None and c.id not in allowed:
            continue
        unit = db.get(OrgUnit, c.org_unit_id) if c.org_unit_id else None
        out.append(
            {
                "id": str(c.id),
                "title": c.title,
                "course_code": c.course_code,
                "status": c.status,
                "org_unit_id": str(c.org_unit_id) if c.org_unit_id else None,
                "org_unit_name": unit.name if unit else None,
                "badge_teams": bool(c.badge_teams),
            }
        )
    return out


# ---- memberships ----------------------------------------------------------------------------


def _scope_org_unit(db: Session, scope_type: str, scope_id: uuid.UUID) -> uuid.UUID | None:
    if scope_type == "org_unit":
        if db.get(OrgUnit, scope_id) is None:
            raise NotFound("SCOPE_NOT_FOUND", "No such unit.")
        return scope_id
    if scope_type == "course":
        course = db.get(Course, scope_id)
        if course is None:
            raise NotFound("SCOPE_NOT_FOUND", "No such course.")
        return course.org_unit_id
    if scope_type == "issuer":
        issuer = db.get(Issuer, scope_id)
        if issuer is None:
            raise NotFound("SCOPE_NOT_FOUND", "No such issuer.")
        return issuer.org_unit_id
    if scope_type == "institution":
        return None
    raise Invalid("SCOPE_INVALID", "Unknown scope.")


VALID_SCOPES = {
    "inst_admin": ("institution",),
    "dept_admin": ("org_unit",),
    "issuer_manager": ("issuer",),
    "reviewer": ("org_unit",),
    "lecturer": ("course",),
    "course_admin": ("course",),
}


def _scope_name(db: Session, scope_type: str, scope_id: uuid.UUID) -> str | None:
    model = {"org_unit": OrgUnit, "course": Course, "issuer": Issuer}.get(scope_type)
    if model is None:
        return "Whole institution"
    row = db.get(model, scope_id)
    return getattr(row, "name", None) or getattr(row, "title", None)


def membership_out(db: Session, m: Membership) -> dict[str, Any]:
    user = db.get(User, m.user_id)
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "user_name": user.display_name if user else None,
        "role": m.role,
        "scope_type": m.scope_type,
        "scope_id": str(m.scope_id),
        "scope_name": _scope_name(db, m.scope_type, m.scope_id),
        "source": m.source,
        "expires_at": m.expires_at,
        "granted_at": m.created_at,
    }


def list_staff_memberships(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    """Staff roles the actor can see: all for institution admins, their units for others."""
    authz.require_admin(actor)
    units = authz.admin_org_units(db, actor)
    rows = db.scalars(
        select(Membership)
        .where(Membership.revoked_at.is_(None), Membership.role != "student")
        .order_by(Membership.created_at)
    ).all()
    out = []
    for m in rows:
        if units is not None:
            unit = _scope_org_unit(db, m.scope_type, m.scope_id)
            if unit is None or unit not in units:
                continue
        out.append(membership_out(db, m))
    return out


def search_people(db: Session, actor: authz.Actor, q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Find a person to grant a role to. Names only; no email (spec §15.2 minimisation)."""
    authz.require_admin(actor)
    q = (q or "").strip()
    if len(q) < 2:
        return []
    users = db.scalars(
        select(User)
        .where(User.status == "active", User.display_name.ilike(f"%{q}%"))
        .order_by(User.display_name)
        .limit(limit)
    ).all()
    return [{"id": str(u.id), "display_name": u.display_name} for u in users]


def grant(
    db: Session,
    actor: authz.Actor,
    *,
    user_id: uuid.UUID,
    role: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    expires_at: datetime | None = None,
    request_id: str | None = None,
) -> Membership:
    authz.require_admin(actor)
    if role not in VALID_SCOPES:
        raise Invalid("ROLE_INVALID", "That role cannot be granted here.")
    if scope_type not in VALID_SCOPES[role]:
        raise Invalid("SCOPE_INVALID", f"{role} is granted at {VALID_SCOPES[role][0]} level.")
    if scope_type == "institution":
        scope_id = actor.institution_id
    if scope_id is None:
        raise Invalid("SCOPE_REQUIRED", "Choose where this role applies.")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise NotFound("USER_NOT_FOUND", "No such person.")
    scope_unit = _scope_org_unit(db, scope_type, scope_id)
    rules = authz.institution_policy(db, actor.institution_id)
    if not authz.can_grant(db, actor, role, scope_type, scope_unit, rules):
        raise Forbidden("OUT_OF_SCOPE", "You cannot grant that role there.")
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise Invalid("EXPIRY_INVALID", "The expiry must be in the future.")
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.role == role,
            Membership.scope_type == scope_type,
            Membership.scope_id == scope_id,
            Membership.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    m = Membership(
        institution_id=actor.institution_id,
        user_id=user_id,
        role=role,
        scope_type=scope_type,
        scope_id=scope_id,
        source="grant",
        granted_by=actor.user_id,
        expires_at=expires_at,
    )
    db.add(m)
    db.flush()
    audit.record(
        db,
        action="membership.grant",
        resource_type="membership",
        resource_id=m.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "user_id": str(user_id),
            "role": role,
            "scope_type": scope_type,
            "scope_id": str(scope_id),
        },
    )
    return m


def revoke(
    db: Session, actor: authz.Actor, membership_id: uuid.UUID, request_id: str | None = None
) -> None:
    authz.require_admin(actor)
    m = db.get(Membership, membership_id, with_for_update=True)
    if m is None or m.revoked_at is not None or m.role == "student":
        raise NotFound("NOT_FOUND", "No such role.")
    scope_unit = _scope_org_unit(db, m.scope_type, m.scope_id)
    rules = authz.institution_policy(db, actor.institution_id)
    if not authz.can_grant(db, actor, m.role, m.scope_type, scope_unit, rules):
        raise Forbidden("OUT_OF_SCOPE", "You cannot remove that role.")
    if m.role == "inst_admin":
        remaining = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.role == "inst_admin",
                Membership.revoked_at.is_(None),
                Membership.id != m.id,
            )
        )
        if not remaining:
            raise Conflict(
                "LAST_ADMIN", "Grant another institution administrator before removing this one."
            )
    m.revoked_at = datetime.now(UTC)
    audit.record(
        db,
        action="membership.revoke",
        resource_type="membership",
        resource_id=m.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "user_id": str(m.user_id),
            "role": m.role,
            "scope_type": m.scope_type,
            "scope_id": str(m.scope_id),
        },
    )
