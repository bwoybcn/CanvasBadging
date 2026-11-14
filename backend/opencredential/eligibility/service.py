# SPDX-License-Identifier: AGPL-3.0-or-later
"""Eligibility evaluation and award decisions (spec §6.4-6.6, §17, ADR-0012, ADR-0017).

Flow for one learner and one live badge version:

1. Build a snapshot and run the pure engine.
2. Record an ``EligibilityEvaluation`` when the outcome or its inputs changed (or on explicit
   re-evaluation), so the history shows every change with its sources.
3. If the outcome is ``met``, apply the version's awarding policy:

   * ``automatic``: create an ``AwardDecision`` in status ``ready`` and enqueue
     ``oc:issue_credential`` in the same transaction.
   * ``lecturer_confirmed``: create a decision in ``awaiting_confirmation``; a lecturer confirms
     (only if the learner is *still* eligible) or rejects it.
   * ``manual``: nothing automatic; awards are made with :func:`manual_award` and a written
     justification.

At most one live decision exists per learner, version and issuance sequence (unique index), and
the decision's ``idempotency_key`` is deterministic, so replays never create a second award. Keys
and inserts both come from :mod:`opencredential.issuance.decisions`, the only place decisions
are created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authoring import rules_store
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    AwardDecision,
    AwardRule,
    AwardRuleSet,
    Course,
    EligibilityEvaluation,
    ManualRuleApproval,
    Membership,
    User,
)
from opencredential.eligibility.snapshots import CourseData, approvals_for, load_course, snapshot
from opencredential.errors import Conflict, Forbidden, Invalid, NotFound
from opencredential.issuance import decisions
from opencredential.jobs import enqueue
from opencredential.rules import MET, Evaluation, RuleSet, evaluate

MIN_JUSTIFICATION = 20


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Target:
    """A live badge version ready for evaluation."""

    definition: AchievementDefinition
    version: AchievementVersion
    rules: RuleSet
    source_status: dict[str, str]


def live_target(db: Session, definition: AchievementDefinition) -> Target | None:
    if definition.state == "archived" or definition.current_version_id is None:
        return None
    version = db.get(AchievementVersion, definition.current_version_id)
    if version is None or not version.frozen:
        return None
    rules = rules_store.load(db, version.id)
    if rules is None:
        return None
    return Target(definition, version, rules, rules_store.source_status(db, version.id))


def live_targets_for_course(db: Session, course_id: uuid.UUID) -> list[Target]:
    defs = db.scalars(
        select(AchievementDefinition).where(
            AchievementDefinition.course_id == course_id,
            AchievementDefinition.state != "archived",
            AchievementDefinition.current_version_id.is_not(None),
        )
    ).all()
    return [t for d in defs if (t := live_target(db, d)) is not None]


def course_students(db: Session, course_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Membership.user_id).where(
                Membership.scope_type == "course",
                Membership.scope_id == course_id,
                Membership.role == "student",
                Membership.revoked_at.is_(None),
            )
        )
    )


def compute(
    db: Session,
    target: Target,
    user_id: uuid.UUID,
    *,
    data: CourseData | None = None,
    approvals: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Evaluation:
    """Evaluate without writing anything (used by progress views and previews)."""
    if data is None:
        data = load_course(db, target.definition.course_id)
    if approvals is None:
        approvals = approvals_for(db, target.version.id, [user_id]).get(user_id, {})
    policy = authz.institution_policy(db, target.definition.institution_id)
    snap = snapshot(
        data,
        user_id,
        approvals=approvals,
        rule_source_status=target.source_status,
        max_age_minutes=int(policy.get("max_snapshot_age_minutes", 120)),
        now=now,
    )
    return evaluate(target.rules, snap)


def latest_evaluation(
    db: Session, version_id: uuid.UUID, user_id: uuid.UUID
) -> EligibilityEvaluation | None:
    return db.scalar(
        select(EligibilityEvaluation)
        .where(
            EligibilityEvaluation.version_id == version_id, EligibilityEvaluation.user_id == user_id
        )
        .order_by(EligibilityEvaluation.evaluated_at.desc(), EligibilityEvaluation.id.desc())
        .limit(1)
    )


def evaluate_and_record(
    db: Session,
    target: Target,
    user_id: uuid.UUID,
    *,
    triggered_by: str,
    data: CourseData | None = None,
    approvals: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> tuple[EligibilityEvaluation, AwardDecision | None]:
    ev = compute(db, target, user_id, data=data, approvals=approvals)
    previous = latest_evaluation(db, target.version.id, user_id)
    if (
        previous is not None
        and previous.inputs_hash == ev.inputs_hash
        and previous.outcome == ev.outcome
        and triggered_by in ("sync", "reeval")
    ):
        record = previous  # nothing changed: no new history row for a routine pass
    else:
        detail = ev.as_detail()
        detail["triggered_by_user"] = str(actor_user_id) if actor_user_id else None
        record = EligibilityEvaluation(
            institution_id=target.definition.institution_id,
            version_id=target.version.id,
            user_id=user_id,
            outcome=ev.outcome,
            detail=detail,
            inputs_hash=ev.inputs_hash,
            triggered_by=triggered_by,
            evaluated_at=_now(),
        )
        db.add(record)
        db.flush()
        if previous is not None and previous.outcome != ev.outcome:
            audit.record(
                db,
                action="eligibility.changed",
                resource_type="eligibility_evaluation",
                resource_id=record.id,
                institution_id=target.definition.institution_id,
                actor_user_id=actor_user_id,
                actor_kind="user" if actor_user_id else "system",
                data={
                    "from": previous.outcome,
                    "to": ev.outcome,
                    "version_id": str(target.version.id),
                    "user_id": str(user_id),
                },
            )
    decision = apply_award_policy(db, target, user_id, record) if ev.outcome == MET else None
    return record, decision


def _existing_decision(
    db: Session, version_id: uuid.UUID, user_id: uuid.UUID, seq: int = 1, *, live_only: bool = False
) -> AwardDecision | None:
    q = select(AwardDecision).where(
        AwardDecision.version_id == version_id,
        AwardDecision.user_id == user_id,
        AwardDecision.issuance_seq == seq,
    )
    if live_only:
        q = q.where(AwardDecision.status != "rejected")
    return db.scalar(q.order_by(AwardDecision.decided_at.desc()).limit(1))


def _request_issuance(db: Session, decision: AwardDecision) -> None:
    enqueue.defer(
        db,
        enqueue.ISSUE_CREDENTIAL,
        queue="issuance",
        institution_id=decision.institution_id,
        args={"decision_id": str(decision.id)},
        subject_type="award_decision",
        subject_id=decision.id,
        queueing_lock=f"issue:{decision.id}",
        lock=f"issue:{decision.user_id}:{decision.version_id}",
    )


def apply_award_policy(
    db: Session, target: Target, user_id: uuid.UUID, evaluation: EligibilityEvaluation
) -> AwardDecision | None:
    version = target.version
    policy = version.award_policy or target.definition.award_policy
    if policy == "manual":
        return None
    # Any decision at all (including a rejected one) stops automatic re-creation: a lecturer's
    # rejection is final for the automatic path; a later manual award is still possible.
    existing = _existing_decision(db, version.id, user_id)
    if existing is not None:
        return existing
    kind, status = (
        ("automatic", "ready") if policy == "automatic" else ("confirmed", "awaiting_confirmation")
    )
    decision, created = decisions.decide(
        db,
        institution_id=target.definition.institution_id,
        user_id=user_id,
        version_id=version.id,
        kind=kind,
        evaluation_id=evaluation.id,
        status=status,
        now=_now(),
        record_audit=False,
    )
    if not created:
        return decision  # a concurrent worker already decided
    audit.record(
        db,
        action=f"award.{status}",
        resource_type="award_decision",
        resource_id=decision.id,
        institution_id=decision.institution_id,
        actor_kind="system",
        data={
            "version_id": str(version.id),
            "user_id": str(user_id),
            "kind": kind,
            "evaluation_id": str(evaluation.id),
        },
    )
    if status == "ready":
        _request_issuance(db, decision)
    return decision


# ---- course-wide evaluation (jobs) -------------------------------------------------------------


def evaluate_course(
    db: Session,
    course_id: uuid.UUID,
    *,
    triggered_by: str = "sync",
    version_id: uuid.UUID | None = None,
) -> dict[str, int]:
    data = load_course(db, course_id)
    students = course_students(db, course_id)
    counts = {"evaluated": 0, "met": 0, "decisions": 0}
    for target in live_targets_for_course(db, course_id):
        if version_id is not None and target.version.id != version_id:
            continue
        approvals = approvals_for(db, target.version.id, students)
        for uid in students:
            record, decision = evaluate_and_record(
                db,
                target,
                uid,
                triggered_by=triggered_by,
                data=data,
                approvals=approvals.get(uid, {}),
            )
            counts["evaluated"] += 1
            counts["met"] += record.outcome == MET
            counts["decisions"] += decision is not None
    return counts


# ---- staff actions -----------------------------------------------------------------------------


def _definition_for_version(db: Session, version_id: uuid.UUID) -> AchievementDefinition:
    version = db.get(AchievementVersion, version_id)
    if version is None:
        raise NotFound("NOT_FOUND", "No such badge version.")
    definition = db.get(AchievementDefinition, version.definition_id)
    assert definition is not None
    return definition


def require_award_staff(db: Session, actor: authz.Actor, definition: AchievementDefinition) -> None:
    course = db.get(Course, definition.course_id) if definition.course_id else None
    if course is not None:
        authz.require_course_staff(db, actor, course)
    elif not authz.can_edit_definition(db, actor, definition):
        raise Forbidden("FORBIDDEN", "You cannot award this badge.")


def _require_learner(db: Session, definition: AchievementDefinition, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise NotFound("LEARNER_NOT_FOUND", "No such learner.")
    if definition.course_id is not None and user_id not in course_students(
        db, definition.course_id
    ):
        raise Invalid(
            "LEARNER_NOT_IN_COURSE", "This person is not a student in the badge's course."
        )
    return user


def record_rule_approval(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    *,
    rule_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
    note: str | None,
    request_id: str | None = None,
) -> tuple[EligibilityEvaluation, AwardDecision | None]:
    """Rule E: a lecturer confirms (or declines) a manual requirement for one learner."""
    require_award_staff(db, actor, definition)
    target = live_target(db, definition)
    if target is None:
        raise Conflict("NOT_LIVE", "This badge is not published.")
    rule = db.scalar(
        select(AwardRule)
        .join(AwardRuleSet, AwardRuleSet.id == AwardRule.rule_set_id)
        .where(
            AwardRule.id == rule_id,
            AwardRuleSet.version_id == target.version.id,
            AwardRule.type == "manual_approval",
        )
    )
    if rule is None:
        raise NotFound("RULE_NOT_FOUND", "That requirement is not a lecturer confirmation.")
    if decision not in ("approve", "decline"):
        raise Invalid("DECISION_INVALID", "Choose approve or decline.")
    _require_learner(db, definition, user_id)
    db.add(
        ManualRuleApproval(
            institution_id=actor.institution_id,
            version_id=target.version.id,
            rule_id=rule.id,
            user_id=user_id,
            decision=decision,
            note=(note or "").strip() or None,
            decided_by=actor.user_id,
            decided_at=_now(),
        )
    )
    db.flush()
    audit.record(
        db,
        action=f"rule_approval.{decision}",
        resource_type="award_rule",
        resource_id=rule.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"user_id": str(user_id), "version_id": str(target.version.id)},
    )
    return evaluate_and_record(
        db, target, user_id, triggered_by="manual", actor_user_id=actor.user_id
    )


def confirm_award(
    db: Session,
    actor: authz.Actor,
    decision_id: uuid.UUID,
    *,
    note: str | None = None,
    request_id: str | None = None,
) -> AwardDecision:
    decision = db.get(AwardDecision, decision_id, with_for_update=True)
    if decision is None:
        raise NotFound("NOT_FOUND", "No such award.")
    definition = _definition_for_version(db, decision.version_id)
    require_award_staff(db, actor, definition)
    if decision.status in ("ready", "issued"):
        return decision  # idempotent replay
    if decision.status != "awaiting_confirmation":
        raise Conflict("INVALID_STATE", f"This award is {decision.status}.")
    if decision.kind == "manual":
        # Second approval of a manual award (institution policy): a different person.
        if decision.decided_by == actor.user_id:
            raise Forbidden(
                "SECOND_APPROVER_REQUIRED",
                "A different member of staff must approve this manual award.",
            )
    else:
        target = live_target(db, definition)
        if target is None or target.version.id != decision.version_id:
            raise Conflict("NOT_LIVE", "This badge version is no longer being awarded.")
        record, _ = evaluate_and_record(
            db, target, decision.user_id, triggered_by="manual", actor_user_id=actor.user_id
        )
        if record.outcome != MET:
            raise Conflict(
                "ELIGIBILITY_CHANGED",
                "The learner no longer meets the requirements on current Canvas data.",
                "; ".join(
                    r["message"] for r in record.detail.get("rules", []) if r["outcome"] != MET
                ),
            )
        decision.evaluation_id = record.id
        decision.decided_by = actor.user_id
        decision.decided_at = _now()
    decision.status = "ready"
    audit.record(
        db,
        action="award.confirm",
        resource_type="award_decision",
        resource_id=decision.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"note": bool(note), "kind": decision.kind},
    )
    _request_issuance(db, decision)
    return decision


def reject_award(
    db: Session,
    actor: authz.Actor,
    decision_id: uuid.UUID,
    *,
    reason: str,
    request_id: str | None = None,
) -> AwardDecision:
    decision = db.get(AwardDecision, decision_id, with_for_update=True)
    if decision is None:
        raise NotFound("NOT_FOUND", "No such award.")
    definition = _definition_for_version(db, decision.version_id)
    require_award_staff(db, actor, definition)
    if decision.status == "rejected":
        return decision
    if decision.status != "awaiting_confirmation":
        raise Conflict("INVALID_STATE", f"This award is {decision.status} and cannot be rejected.")
    if not reason or len(reason.strip()) < 5:
        raise Invalid("REASON_REQUIRED", "Give a reason for not awarding this badge.")
    decision.status = "rejected"
    decision.rejection_reason = reason.strip()
    audit.record(
        db,
        action="award.reject",
        resource_type="award_decision",
        resource_id=decision.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
    )
    return decision


def manual_award(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    *,
    user_id: uuid.UUID,
    justification: str,
    evidence: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> tuple[AwardDecision, bool]:
    """Spec §6.5(3): award with a written justification. Returns ``(decision, created)``."""
    require_award_staff(db, actor, definition)
    target = live_target(db, definition)
    if target is None:
        raise Conflict("NOT_LIVE", "Only published badges can be awarded.")
    justification = (justification or "").strip()
    if len(justification) < MIN_JUSTIFICATION:
        raise Invalid(
            "JUSTIFICATION_REQUIRED",
            f"Explain why this badge is awarded (at least {MIN_JUSTIFICATION} characters).",
        )
    _require_learner(db, definition, user_id)
    existing = _existing_decision(db, target.version.id, user_id, live_only=True)
    if existing is not None:
        if existing.kind == "manual" and existing.justification == justification:
            return existing, False  # idempotent replay of the same request
        if existing.status == "awaiting_confirmation":
            raise Conflict(
                "AWARD_PENDING_CONFIRMATION",
                "This learner already has an award waiting for confirmation. Confirm that instead.",
            )
        raise Conflict("ALREADY_AWARDED", "This learner already has this badge.")
    policy = authz.institution_policy(db, actor.institution_id)
    second = bool(policy.get("manual_awards_require_second_approval"))
    # Each earlier rejected manual award is an earlier attempt: a corrected award after a
    # rejection needs a key of its own, or it would collide with the rejected one.
    rejected = (
        db.scalar(
            select(func.count())
            .select_from(AwardDecision)
            .where(
                AwardDecision.version_id == target.version.id,
                AwardDecision.user_id == user_id,
                AwardDecision.issuance_seq == 1,
                AwardDecision.kind == "manual",
                AwardDecision.status == "rejected",
            )
        )
        or 0
    )
    decision, created = decisions.decide(
        db,
        institution_id=actor.institution_id,
        user_id=user_id,
        version_id=target.version.id,
        kind="manual",
        justification=justification,
        evidence=evidence,
        decided_by=actor.user_id,
        status="awaiting_confirmation" if second else "ready",
        attempt=rejected,
        now=_now(),
        record_audit=False,
    )
    if not created:
        if decision.kind == "manual" and decision.justification == justification:
            return decision, False  # a concurrent replay of the same request won the race
        raise Conflict("ALREADY_AWARDED", "This learner already has this badge.")
    audit.record(
        db,
        action="award.manual",
        resource_type="award_decision",
        resource_id=decision.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "version_id": str(target.version.id),
            "user_id": str(user_id),
            "second_approval_required": second,
            "evidence_items": len(decision.evidence),
        },
    )
    if decision.status == "ready":
        _request_issuance(db, decision)
    return decision, True
