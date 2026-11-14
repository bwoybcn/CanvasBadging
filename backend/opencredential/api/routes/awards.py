# SPDX-License-Identifier: AGPL-3.0-or-later
"""Evaluations, lecturer approvals and award decisions (spec §6.4-6.6, §13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from opencredential.api.deps import ActorDep, RequestIdDep, TenantDb
from opencredential.authoring import service as authoring
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    AwardDecision,
    EligibilityEvaluation,
    User,
)
from opencredential.eligibility import bulk
from opencredential.eligibility import service as eligibility
from opencredential.errors import Conflict, Invalid, NotFound

router = APIRouter(prefix="/api/v1", tags=["eligibility and awards"])

MAX_SYNC_EVALUATIONS = 50


class EvaluateIn(BaseModel):
    definition_id: uuid.UUID
    user_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class EvaluationOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    user_id: uuid.UUID
    outcome: str
    detail: dict[str, Any]
    inputs_hash: str
    triggered_by: str
    evaluated_at: datetime


class DecisionOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    definition_id: uuid.UUID
    badge_title: str
    user_id: uuid.UUID
    learner_name: str | None
    kind: str
    status: str
    evaluation_id: uuid.UUID | None
    justification: str | None
    evidence: list[dict[str, Any]]
    rejection_reason: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime
    idempotency_key: str
    current_eligibility: dict[str, Any] | None = None


class RuleApprovalIn(BaseModel):
    user_id: uuid.UUID
    rule_id: uuid.UUID
    decision: str = Field(pattern="^(approve|decline)$")
    note: str | None = Field(default=None, max_length=2000)


class ConfirmIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class Evidence(BaseModel):
    kind: str = Field(
        pattern="^(completion_record|assessment_result|evaluation_statement|"
        "artefact|lecturer_confirmation)$"
    )
    narrative: str = Field(min_length=1, max_length=2000)
    url: str | None = Field(default=None, max_length=1000, pattern=r"^https://")
    public: bool = False


class ManualAwardIn(BaseModel):
    definition_id: uuid.UUID
    user_id: uuid.UUID
    justification: str = Field(max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)


class BulkAwardIn(BaseModel):
    definition_id: uuid.UUID
    identifiers: list[str] = Field(
        min_length=1,
        max_length=bulk.MAX_IDENTIFIERS,
        description="Student ID numbers (SIS user ids) or university emails. Each item may also "
        "hold several, separated by new lines, commas, semicolons or tabs.",
    )
    justification: str = Field(max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    confirm: bool = Field(default=False, description="false: preview only. true: make the awards.")


class BulkRowOut(BaseModel):
    identifier: str
    status: str = Field(
        description="will_award, awarded, awaiting_confirmation, already_awarded, "
        "pending_confirmation, not_found (no student in the badge's course matches), "
        "duplicate or failed"
    )
    user_id: uuid.UUID | None = None
    learner_name: str | None = None
    decision_id: uuid.UUID | None = None
    message: str | None = None


class BulkAwardOut(BaseModel):
    committed: bool
    second_approval: bool = Field(
        default=False,
        description="true: each award waits for a second member of staff to confirm it.",
    )
    counts: dict[str, int]
    rows: list[BulkRowOut]


def _decision_out(db: TenantDb, d: AwardDecision, with_eligibility: bool = False) -> DecisionOut:
    v = db.get(AchievementVersion, d.version_id)
    u = db.get(User, d.user_id)
    assert v is not None
    current = None
    if with_eligibility:
        e = eligibility.latest_evaluation(db, d.version_id, d.user_id)
        if e is not None:
            current = {
                "outcome": e.outcome,
                "evaluated_at": e.evaluated_at.isoformat(),
                "rules": e.detail.get("rules", []),
            }
    return DecisionOut(
        id=d.id,
        version_id=d.version_id,
        definition_id=v.definition_id,
        badge_title=v.title,
        user_id=d.user_id,
        learner_name=u.display_name if u else None,
        kind=d.kind,
        status=d.status,
        evaluation_id=d.evaluation_id,
        justification=d.justification,
        evidence=d.evidence,
        rejection_reason=d.rejection_reason,
        decided_by=d.decided_by,
        decided_at=d.decided_at,
        idempotency_key=d.idempotency_key,
        current_eligibility=current,
    )


def _definition(
    db: TenantDb, actor: authz.Actor, definition_id: uuid.UUID
) -> AchievementDefinition:
    d = authoring.get_definition(db, definition_id)
    eligibility.require_award_staff(db, actor, d)
    return d


@router.post("/evaluations")
def run_evaluation(body: EvaluateIn, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    """Manual re-evaluation (spec §6.4). Small batches run now; larger ones are queued."""
    d = _definition(db, actor, body.definition_id)
    target = eligibility.live_target(db, d)
    if target is None:
        raise Conflict("NOT_LIVE", "Only published badges can be evaluated.")
    users = body.user_ids
    if users is None:
        users = eligibility.course_students(db, d.course_id) if d.course_id else []
    if len(users) > MAX_SYNC_EVALUATIONS and d.course_id is not None:
        from opencredential.jobs import enqueue

        job = enqueue.defer(
            db,
            enqueue.EVALUATE_COURSE,
            queue="eligibility",
            institution_id=actor.institution_id,
            args={
                "course_id": str(d.course_id),
                "triggered_by": "manual",
                "version_id": str(target.version.id),
            },
            subject_type="course",
            subject_id=d.course_id,
        )
        return {"queued": True, "job_id": job, "results": []}
    students = set(eligibility.course_students(db, d.course_id)) if d.course_id else None
    results = []
    for uid in users:
        if students is not None and uid not in students:
            raise Invalid("LEARNER_NOT_IN_COURSE", f"{uid} is not a student in this course.")
        record, decision = eligibility.evaluate_and_record(
            db, target, uid, triggered_by="manual", actor_user_id=actor.user_id
        )
        results.append(
            {
                "user_id": str(uid),
                "evaluation_id": str(record.id),
                "outcome": record.outcome,
                "detail": record.detail,
                "decision_status": decision.status if decision else None,
            }
        )
    return {"queued": False, "job_id": None, "results": results}


@router.get("/evaluations", response_model=list[EvaluationOut])
def evaluation_history(
    db: TenantDb,
    actor: ActorDep,
    definition_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[EligibilityEvaluation]:
    d = authoring.get_definition(db, definition_id)
    if user_id != actor.user_id:
        eligibility.require_award_staff(db, actor, d)
    versions = select(AchievementVersion.id).where(AchievementVersion.definition_id == d.id)
    q = select(EligibilityEvaluation).where(EligibilityEvaluation.version_id.in_(versions))
    if user_id is not None:
        q = q.where(EligibilityEvaluation.user_id == user_id)
    return list(db.scalars(q.order_by(EligibilityEvaluation.evaluated_at.desc()).limit(limit)))


@router.post("/achievements/{definition_id}/approvals")
def approve_requirement(
    definition_id: uuid.UUID,
    body: RuleApprovalIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
) -> dict[str, Any]:
    """Rule E: confirm (or decline) a lecturer-confirmation requirement for one learner."""
    d = authoring.get_definition(db, definition_id)
    record, decision = eligibility.record_rule_approval(
        db,
        actor,
        d,
        rule_id=body.rule_id,
        user_id=body.user_id,
        decision=body.decision,
        note=body.note,
        request_id=rid,
    )
    return {
        "evaluation_id": str(record.id),
        "outcome": record.outcome,
        "detail": record.detail,
        "decision_status": decision.status if decision else None,
    }


@router.get("/awards", response_model=list[DecisionOut])
def list_awards(
    db: TenantDb,
    actor: ActorDep,
    status: str | None = "awaiting_confirmation",
    course_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    kind: str | None = Query(None, pattern="^(automatic|confirmed|manual)$"),
    limit: int = Query(100, ge=1, le=500),
) -> list[DecisionOut]:
    q = (
        select(AwardDecision, AchievementDefinition)
        .join(AchievementVersion, AchievementVersion.id == AwardDecision.version_id)
        .join(AchievementDefinition, AchievementDefinition.id == AchievementVersion.definition_id)
    )
    if status:
        q = q.where(AwardDecision.status == status)
    if course_id:
        q = q.where(AchievementDefinition.course_id == course_id)
    if definition_id:
        q = q.where(AchievementDefinition.id == definition_id)
    if kind:
        q = q.where(AwardDecision.kind == kind)
    scope = authz.award_list_scope(db, actor)
    if scope is not None:
        q = q.where(scope)
    out = []
    for decision, definition in db.execute(q.order_by(AwardDecision.decided_at).limit(limit)):
        # The SQL scope already applies this rule; the per-row check stays as a safety net.
        if not authz.can_award_definition(db, actor, definition):
            continue
        out.append(_decision_out(db, decision, with_eligibility=True))
    return out


def _decision(db: TenantDb, decision_id: uuid.UUID) -> AwardDecision:
    d = db.get(AwardDecision, decision_id)
    if d is None:
        raise NotFound("NOT_FOUND", "No such award.")
    return d


@router.get("/awards/{decision_id}", response_model=DecisionOut)
def get_award(decision_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> DecisionOut:
    d = _decision(db, decision_id)
    v = db.get(AchievementVersion, d.version_id)
    assert v is not None
    if d.user_id != actor.user_id:
        definition = authoring.get_definition(db, v.definition_id)
        eligibility.require_award_staff(db, actor, definition)
    return _decision_out(db, d, with_eligibility=True)


@router.post("/awards/{decision_id}/confirm", response_model=DecisionOut)
def confirm_award(
    decision_id: uuid.UUID, body: ConfirmIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DecisionOut:
    d = eligibility.confirm_award(db, actor, decision_id, note=body.note, request_id=rid)
    return _decision_out(db, d)


@router.post("/awards/{decision_id}/reject", response_model=DecisionOut)
def reject_award(
    decision_id: uuid.UUID, body: RejectIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DecisionOut:
    d = eligibility.reject_award(db, actor, decision_id, reason=body.reason, request_id=rid)
    return _decision_out(db, d)


@router.post("/awards/manual", response_model=DecisionOut, status_code=201)
def manual_award(
    body: ManualAwardIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DecisionOut:
    d = authoring.get_definition(db, body.definition_id)
    decision, _created = eligibility.manual_award(
        db,
        actor,
        d,
        user_id=body.user_id,
        justification=body.justification,
        evidence=[e.model_dump() for e in body.evidence],
        request_id=rid,
    )
    return _decision_out(db, decision)


@router.post("/awards/bulk", response_model=BulkAwardOut)
def bulk_award(body: BulkAwardIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep) -> BulkAwardOut:
    """Award a published badge to a list of learners in its course, previewing first."""
    d = authoring.get_definition(db, body.definition_id)
    result = bulk.award_list(
        db,
        actor,
        d,
        identifiers=body.identifiers,
        justification=body.justification,
        evidence=[e.model_dump() for e in body.evidence],
        confirm=body.confirm,
        request_id=rid,
    )
    return BulkAwardOut(
        committed=result.committed,
        second_approval=result.second_approval,
        counts=result.counts(),
        rows=[BulkRowOut(**r.__dict__) for r in result.rows],
    )
