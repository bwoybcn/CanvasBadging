# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log browsing and export (spec §10.6).

Every row shows actor, action, affected resource and time. Staff actors are named; learners are
never named here (their pseudonymous id is enough for an investigation, and the personal-data
export can resolve it). ``data`` is passed through only for keys on an allow-list, so free text
that slipped into an event never reaches the screen or a CSV.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.authz import policy as authz
from opencredential.db.models import AuditEvent, Membership, User

#: Spec §10.6 categories → the action names that implement them.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Issuer creation and authority": ("issuer.",),
    "Badge definitions": (
        "achievement.create",
        "achievement.edit",
        "achievement.submit",
        "achievement.new_version",
        "achievement.archive",
        "achievement.restore",
        "achievement.delete_draft",
    ),
    "Definition approval": ("achievement.approve", "achievement.reject"),
    "Publication": ("achievement.publish",),
    "Award-rule changes": ("rules.", "rule.", "rule_approval."),
    "Manual awards": ("award.manual", "award.confirm", "award.reject"),
    "Automated awards": (
        "award.decide",
        "award.ready",
        "award.awaiting_confirmation",
        "award.duplicate",
        "credential.issue",
    ),
    "Revocations": ("credential.revoke", "revocation."),
    "Permission changes": ("membership.", "org_unit.", "course.org_unit"),
    "Key management": ("issuer_key.",),
    "Policy and configuration": (
        "institution.",
        "template.",
        "course.activate",
        "course.deactivate",
    ),
    "Personal data and retention": ("privacy.", "retention."),
    "Operations": (
        "job.",
        "reconciliation.",
        "course.sync_requested",
        "course.report_export",
        "eligibility.",
        "session.",
        "asset.",
    ),
}

#: ``data`` keys safe to show (ids, codes, counts, booleans). Anything else is dropped.
SAFE_DATA_KEYS = {
    "kind",
    "version_id",
    "issuance_seq",
    "course_id",
    "issuer_id",
    "reason_code",
    "changes",
    "role",
    "scope_type",
    "scope_id",
    "status",
    "level",
    "retired_key_id",
    "request_id",
    "second_approval_required",
    "evidence_items",
    "counts",
    "fields",
    "org_unit_id",
    "parent_id",
    "may_issue",
    "template_id",
    "credential_id",
    "decision_id",
    "outcome",
    "note",
    "from",
    "to",
    "user_id",
    "grants_revoked",
    "removed",
}


def category_of(action: str) -> str:
    for name, prefixes in CATEGORIES.items():
        if any(action == p or (p.endswith(".") and action.startswith(p)) for p in prefixes):
            return name
    return "Other"


def _safe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (data or {}).items() if k in SAFE_DATA_KEYS}


def query(
    db: Session,
    actor: authz.Actor,
    *,
    category: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    q = select(AuditEvent).where(AuditEvent.institution_id == actor.institution_id)
    if category:
        prefixes = CATEGORIES.get(category, ())
        conds = [
            AuditEvent.action.startswith(p) if p.endswith(".") else AuditEvent.action == p
            for p in prefixes
        ]
        if not conds:
            return {"items": [], "next_before": None}
        from sqlalchemy import or_

        q = q.where(or_(*conds))
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if resource_type:
        q = q.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        q = q.where(AuditEvent.resource_id == resource_id)
    if actor_user_id:
        q = q.where(AuditEvent.actor_user_id == actor_user_id)
    if since:
        q = q.where(AuditEvent.at >= datetime.combine(since, time.min, tzinfo=UTC))
    if until:
        q = q.where(
            AuditEvent.at < datetime.combine(until, time.min, tzinfo=UTC) + timedelta(days=1)
        )
    if before_id:
        q = q.where(AuditEvent.id < before_id)
    events = list(db.scalars(q.order_by(AuditEvent.id.desc()).limit(limit + 1)))
    more = len(events) > limit
    events = events[:limit]
    names = _staff_names(db, {e.actor_user_id for e in events if e.actor_user_id})
    items = [
        {
            "id": str(e.id),
            "at": e.at,
            "category": category_of(e.action),
            "action": e.action,
            "actor_kind": e.actor_kind,
            "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
            "actor_name": names.get(e.actor_user_id) if e.actor_user_id else None,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "request_id": e.request_id,
            "data": _safe(e.data),
        }
        for e in events
    ]
    return {"items": items, "next_before": items[-1]["id"] if more and items else None}


def _staff_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Display names only for people who hold (or held) a staff role; learners stay ids."""
    if not ids:
        return {}
    staff = set(
        db.scalars(
            select(Membership.user_id).where(
                Membership.user_id.in_(ids), Membership.role != "student"
            )
        )
    )
    rows = db.execute(select(User.id, User.display_name).where(User.id.in_(staff)))
    return {uid: name or "(no name)" for uid, name in rows}


AUDIT_COLUMNS = (
    "at",
    "category",
    "action",
    "actor_kind",
    "actor_name",
    "actor_user_id",
    "resource_type",
    "resource_id",
    "request_id",
    "data",
)
