# SPDX-License-Identifier: AGPL-3.0-or-later
"""Progress views (spec §8.2, §14.4): confirmed completion is kept apart from pending or
unavailable information, and nothing is called "earned" until a credential has been issued."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from opencredential.authoring.preview import asset_data_url, source_names
from opencredential.db.models import (
    AwardDecision,
    BadgeAsset,
    Course,
    Credential,
    CredentialStatus,
    EligibilityEvaluation,
    Issuer,
    User,
)
from opencredential.eligibility.service import (
    Target,
    compute,
    course_students,
    live_targets_for_course,
)
from opencredential.eligibility.snapshots import approvals_for, load_course
from opencredential.rules import MET, NOT_MET, describe
from opencredential.rules.engine import RuleResult
from opencredential.rules.schema import Group

PENDING_LABELS = {
    "AWAITING_RELEASE": "Awaiting published result",
    "AWAITING_GRADE": "Awaiting marking",
    "GRADE_OUTDATED": "Awaiting marking of your latest submission",
    "AWAITING_APPROVAL": "Awaiting confirmation by course staff",
    "EXCUSED": "Excused: course staff will decide",
    "GRADED_WITHOUT_SUBMISSION": "Course staff will confirm this",
    "DATA_STALE": "Information is being refreshed",
    "DATA_UNAVAILABLE": "Information unavailable",
    "DATA_NOT_SYNCED": "Information unavailable",
}


def requirement_label(result: RuleResult) -> str:
    if result.outcome == MET:
        return "Complete"
    if result.outcome == NOT_MET:
        if result.code == "SCORE_BELOW_THRESHOLD":
            return "Required score not reached"
        if result.code == "APPROVAL_DECLINED":
            return "Not yet confirmed by course staff"
        return "Not yet complete"
    return PENDING_LABELS.get(result.code, "Cannot be confirmed yet")


def _requirements(
    target: Target, results: tuple[RuleResult, ...], names: dict[str, str]
) -> list[dict[str, Any]]:
    out = []
    for rule, res in zip(target.rules.rules, results, strict=True):
        item: dict[str, Any] = {
            "rule_id": res.rule_id,
            "type": res.type,
            "description": describe(rule, names),
            "outcome": res.outcome,
            "status": {"met": "complete", "not_met": "incomplete", "unknown": "pending"}[
                res.outcome
            ],
            "confirmed": res.outcome == MET,
            "label": requirement_label(res),
            "explanation_code": res.code,
            "message": res.message,
            "as_of": res.source.get("fetched_at"),
        }
        if isinstance(rule, Group):
            item["children"] = [
                {
                    "rule_id": c.rule_id,
                    "description": describe(r, names),
                    "outcome": c.outcome,
                    "confirmed": c.outcome == MET,
                    "label": requirement_label(c),
                    "explanation_code": c.code,
                }
                for r, c in zip(rule.rules, res.children, strict=True)
            ]
        out.append(item)
    return out


#: Credential states in which the student no longer holds a valid badge.
WITHDRAWN_STATES = ("revoked", "suspended")


def _award_state(
    db: Session, version_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[str | None, str | None]:
    """The student's award for one badge: ``issued``, ``revoked`` or ``suspended`` with the
    credential id, or the latest decision's status when nothing has been issued."""
    row = db.execute(
        select(Credential.id, CredentialStatus.state)
        .outerjoin(CredentialStatus, CredentialStatus.credential_id == Credential.id)
        .where(
            Credential.version_id == version_id,
            Credential.user_id == user_id,
            Credential.status == "issued",
            Credential.superseded_by_id.is_(None),
        )
    ).first()
    if row is not None:
        # A badge the issuer has withdrawn is not "earned": anyone checking it is told so,
        # and the student must not be shown the opposite.
        return (row.state if row.state in WITHDRAWN_STATES else "issued"), str(row.id)
    decision = db.scalar(
        select(AwardDecision)
        .where(AwardDecision.version_id == version_id, AwardDecision.user_id == user_id)
        .order_by(AwardDecision.decided_at.desc())
        .limit(1)
    )
    return (decision.status if decision else None), None


def badge_status(outcome: str, decision_status: str | None) -> str:
    if decision_status == "issued":
        return "earned"
    if decision_status in WITHDRAWN_STATES:
        return decision_status
    if decision_status in ("ready", "failed"):
        return "awarded"  # decision made; the credential is being issued
    if decision_status == "awaiting_confirmation":
        return "awaiting_confirmation"
    if decision_status == "rejected":
        return "not_awarded"
    if outcome == MET:
        # Requirements met on current data, but no award decision yet (it follows on the next
        # evaluation pass, or from a lecturer for manually awarded badges). Not "earned".
        return "requirements_met"
    return "pending" if outcome == "unknown" else "in_progress"


def learner_achievements(
    db: Session, user_id: uuid.UUID, course_ids: set[uuid.UUID]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for course_id in sorted(course_ids, key=str):
        course = db.get(Course, course_id)
        if course is None:
            continue
        data = load_course(db, course_id)
        names = source_names(db, course_id)
        for target in live_targets_for_course(db, course_id):
            ev = compute(db, target, user_id, data=data)
            decision_status, credential_id = _award_state(db, target.version.id, user_id)
            v = target.version
            asset = db.get(BadgeAsset, v.asset_id) if v.asset_id else None
            issuer = db.get(Issuer, target.definition.issuer_id)
            policy = v.award_policy or target.definition.award_policy
            out.append(
                {
                    "definition_id": str(target.definition.id),
                    "version_id": str(v.id),
                    "course": {"id": str(course.id), "title": course.title},
                    "title": v.title,
                    "short_description": v.short_description,
                    "category": v.category,
                    "issuer": issuer.name if issuer else None,
                    "image": {
                        "data_url": asset_data_url(asset),
                        "alt_text": asset.alt_text if asset else None,
                    },
                    "award_policy": policy,
                    "status": badge_status(ev.outcome, decision_status),
                    "outcome": ev.outcome,
                    "credential_id": credential_id,
                    "progress": {
                        "completed": ev.completed,
                        "total": ev.total,
                        "mode": target.rules.mode,
                    },
                    "requirements": _requirements(target, ev.results, names),
                }
            )
    return out


def course_progress(db: Session, course: Course) -> dict[str, Any]:
    """Learner x badge matrix from the latest *recorded* evaluations (what decisions used)."""
    targets = live_targets_for_course(db, course.id)
    students = course_students(db, course.id)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(students)))}
    version_ids = [t.version.id for t in targets]
    # Only the newest evaluation and decision of each student for each badge: the history of
    # a long-running course is thousands of rows that this screen never shows.
    latest: dict[tuple[uuid.UUID, uuid.UUID], EligibilityEvaluation] = {}
    decisions: dict[tuple[uuid.UUID, uuid.UUID], AwardDecision] = {}
    credentials: dict[tuple[uuid.UUID, uuid.UUID], tuple[uuid.UUID, str]] = {}
    if targets:
        for e in db.scalars(
            select(EligibilityEvaluation)
            .where(EligibilityEvaluation.version_id.in_(version_ids))
            .ext(distinct_on(EligibilityEvaluation.version_id, EligibilityEvaluation.user_id))
            .order_by(
                EligibilityEvaluation.version_id,
                EligibilityEvaluation.user_id,
                EligibilityEvaluation.evaluated_at.desc(),
                EligibilityEvaluation.id.desc(),
            )
        ):
            latest[(e.version_id, e.user_id)] = e
        for d in db.scalars(
            select(AwardDecision)
            .where(AwardDecision.version_id.in_(version_ids))
            .ext(distinct_on(AwardDecision.version_id, AwardDecision.user_id))
            .order_by(
                AwardDecision.version_id,
                AwardDecision.user_id,
                AwardDecision.decided_at.desc(),
                AwardDecision.id.desc(),
            )
        ):
            decisions[(d.version_id, d.user_id)] = d
        for c in db.execute(
            select(Credential.version_id, Credential.user_id, Credential.id, CredentialStatus.state)
            .outerjoin(CredentialStatus, CredentialStatus.credential_id == Credential.id)
            .where(
                Credential.version_id.in_(version_ids),
                Credential.status == "issued",
                Credential.superseded_by_id.is_(None),
            )
        ):
            credentials[(c.version_id, c.user_id)] = (c.id, c.state or "active")
    badges = [
        {
            "definition_id": str(t.definition.id),
            "version_id": str(t.version.id),
            "title": t.version.title,
            "award_policy": t.version.award_policy,
            "rules": [describe(r, source_names(db, course.id)) for r in t.rules.rules],
            "source_flags": sorted({s for s in t.source_status.values() if s != "ok"}),
        }
        for t in targets
    ]
    learners = []
    for uid in sorted(
        students, key=lambda u: (users[u].family_name or "", str(u)) if u in users else ("", str(u))
    ):
        cells = []
        for t in targets:
            ev = latest.get((t.version.id, uid))
            dec = decisions.get((t.version.id, uid))
            cred = credentials.get((t.version.id, uid))
            cells.append(
                {
                    "version_id": str(t.version.id),
                    "outcome": ev.outcome if ev else None,
                    "evaluated_at": ev.evaluated_at if ev else None,
                    "codes": [
                        r["explanation_code"] for r in (ev.detail.get("rules", []) if ev else [])
                    ],
                    "progress": (ev.detail.get("progress") if ev else None),
                    "decision_status": dec.status if dec else None,
                    "decision_id": str(dec.id) if dec else None,
                    # The issued badge, so staff can ask for it to be revoked, and whether
                    # it has been (active, revoked or suspended).
                    "credential_id": str(cred[0]) if cred else None,
                    "credential_state": cred[1] if cred else None,
                }
            )
        u = users.get(uid)
        learners.append(
            {"user_id": str(uid), "name": u.display_name if u else None, "cells": cells}
        )
    approvals = {
        str(t.version.id): {
            str(uid): {rid: a.decision for rid, a in m.items()}
            for uid, m in approvals_for(db, t.version.id).items()
        }
        for t in targets
    }
    return {
        "course": {"id": str(course.id), "title": course.title},
        "badges": badges,
        "learners": learners,
        "approvals": approvals,
    }
