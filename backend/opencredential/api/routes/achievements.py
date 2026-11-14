# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/achievements``: badge authoring, review and publication (spec §5, §13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from opencredential.api.deps import ActorDep, RequestIdDep, TenantDb
from opencredential.authoring import preview as preview_mod
from opencredential.authoring import rules_store
from opencredential.authoring import service as authoring
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    DefinitionReview,
    Issuer,
    User,
)
from opencredential.db.models.authoring import ACHIEVEMENT_TYPES
from opencredential.errors import NotFound
from opencredential.rules.schema import RuleSet

router = APIRouter(prefix="/api/v1", tags=["achievements"])


class VersionOut(BaseModel):
    id: uuid.UUID
    version_no: int
    frozen: bool
    title: str
    short_description: str
    description: str
    learning_outcomes: list[str]
    criteria_narrative: str
    category: str
    achievement_type: str
    demonstration_kind: str
    evidence_description: str | None
    validity_days: int | None
    skills: list[dict[str, Any]]
    asset_id: uuid.UUID | None
    award_policy: str | None
    credit_claim_approved: bool
    content_hash: str | None
    published_at: datetime | None


class ReviewOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    reviewer: str | None
    decision: str
    checklist: dict[str, Any]
    comment: str | None
    created_at: datetime
    without_review: bool = False


class Issue(BaseModel):
    field: str
    code: str
    message: str
    severity: str


class ReviewRequirement(BaseModel):
    """How the working version would be reviewed if submitted now."""

    mode: Literal["required", "author_decides", "not_required"]
    area_mode: Literal["required", "author_decides", "not_required"]
    forced_by: Literal["assessed", "credit"] | None = Field(
        default=None, description="The safeguard that makes review required, if any"
    )
    set_by_org_unit_id: str | None = Field(
        default=None, description="The area whose setting applies (null: the institution)"
    )
    self_approval_allowed: bool


class DefinitionOut(BaseModel):
    id: uuid.UUID
    state: str
    course_id: uuid.UUID | None
    issuer: dict[str, Any]
    owner_user_id: uuid.UUID
    award_policy: str
    live_version_id: uuid.UUID | None
    working_version: VersionOut
    rules: dict[str, Any] | None
    readiness: list[Issue]
    reviews: list[ReviewOut]
    can_edit: bool
    can_review: bool
    effective_award_policy: str | None = Field(
        description="What publication would resolve the awarding method to right now"
    )
    review: ReviewRequirement


class DefinitionSummary(BaseModel):
    id: uuid.UUID
    state: str
    course_id: uuid.UUID | None
    title: str
    category: str
    version_no: int
    live_version_id: uuid.UUID | None
    award_policy: str
    updated_at: datetime


class DefinitionList(BaseModel):
    items: list[DefinitionSummary]
    next_cursor: str | None = None


class CreateIn(BaseModel):
    issuer_id: uuid.UUID
    course_id: uuid.UUID | None = None
    fields: authoring.DraftFields = Field(default_factory=authoring.DraftFields)
    rules: RuleSet | None = None
    template_id: uuid.UUID | None = None


class ReviewIn(BaseModel):
    checklist: dict[str, bool] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=4000)
    credit_claim_approved: bool | None = None


class RejectIn(BaseModel):
    comment: str = Field(min_length=5, max_length=4000)
    checklist: dict[str, bool] | None = None


class SubmitIn(BaseModel):
    review: Literal["colleague", "skip"] | None = Field(
        default=None,
        description="Where the area lets the author decide: ask a colleague (default) or skip",
    )


class SubmitOut(BaseModel):
    state: str
    warnings: list[Issue]


def _version_out(v: AchievementVersion) -> VersionOut:
    return VersionOut.model_validate(v, from_attributes=True)


def _out(db: TenantDb, actor: authz.Actor, d: AchievementDefinition) -> DefinitionOut:
    v = authoring.working_version(db, d)
    rules = rules_store.load(db, v.id)
    issuer = db.get(Issuer, d.issuer_id)
    policy = authz.institution_policy(db, actor.institution_id)
    reviews = db.scalars(
        select(DefinitionReview)
        .where(DefinitionReview.definition_id == d.id)
        .order_by(DefinitionReview.created_at)
    ).all()
    names = {
        u.id: u.display_name
        for u in db.scalars(select(User).where(User.id.in_([r.reviewer_id for r in reviews])))
    }
    effective = None
    if rules is not None:
        effective = authoring.resolve_award_policy(v.award_policy, rules, policy)[0]
    return DefinitionOut(
        id=d.id,
        state=d.state,
        course_id=d.course_id,
        issuer={"id": issuer.id, "name": issuer.name, "did": issuer.did} if issuer else {},
        owner_user_id=d.owner_user_id,
        award_policy=d.award_policy,
        live_version_id=d.current_version_id if d.state != "archived" else None,
        working_version=_version_out(v),
        rules=rules.model_dump(mode="json", exclude_none=True) if rules else None,
        readiness=[Issue(**i) for i in authoring.readiness(db, d, v)] if not v.frozen else [],
        reviews=[
            ReviewOut(
                id=r.id,
                version_id=r.version_id,
                reviewer=names.get(r.reviewer_id),
                decision=r.decision,
                checklist=r.checklist,
                comment=r.comment,
                created_at=r.created_at,
                without_review=r.without_review,
            )
            for r in reviews
        ],
        can_edit=authz.can_edit_definition(db, actor, d),
        can_review=authz.can_review(db, actor, d, policy)
        and (actor.user_id != d.owner_user_id or authz.may_approve_own(db, d)),
        effective_award_policy=effective,
        review=ReviewRequirement(**authoring.review_requirement(db, d, v)),
    )


def _get(db: TenantDb, actor: authz.Actor, definition_id: uuid.UUID) -> AchievementDefinition:
    d = authoring.get_definition(db, definition_id)
    policy = authz.institution_policy(db, actor.institution_id)
    course = authz.definition_course(db, d)
    if not (
        authz.can_edit_definition(db, actor, d)
        or authz.can_review(db, actor, d, policy)
        or authz.is_course_staff(db, actor, course)
    ):
        raise NotFound("NOT_FOUND", "No such badge.")
    return d


@router.get("/achievements", response_model=DefinitionList)
def list_achievements(
    db: TenantDb,
    actor: ActorDep,
    course_id: uuid.UUID | None = None,
    state: str | None = None,
    review_queue: bool = Query(False, description="Only badges this user can review now"),
    limit: int = Query(50, ge=1, le=200),
) -> DefinitionList:
    q = select(AchievementDefinition)
    if course_id is not None:
        q = q.where(AchievementDefinition.course_id == course_id)
    if state is not None:
        q = q.where(AchievementDefinition.state == state)
    if review_queue:
        q = q.where(AchievementDefinition.state == "in_review")
    if not actor.is_inst_admin and not review_queue:
        staff_courses = actor.course_ids(authz.COURSE_STAFF)
        visible = [
            AchievementDefinition.owner_user_id == actor.user_id,
            AchievementDefinition.course_id.in_(staff_courses),
        ]
        if actor.has("dept_admin"):
            visible.append(AchievementDefinition.course_id.is_not(None))
            visible.append(AchievementDefinition.course_id.is_(None))
        q = q.where(or_(*visible))
    policy = authz.institution_policy(db, actor.institution_id)
    items = []
    for d in db.scalars(q.order_by(AchievementDefinition.updated_at.desc()).limit(limit * 3)):
        if review_queue:
            if not authz.can_review(db, actor, d, policy) or (
                d.owner_user_id == actor.user_id and not authz.may_approve_own(db, d)
            ):
                continue
        elif not (
            authz.can_edit_definition(db, actor, d)
            or authz.is_course_staff(db, actor, authz.definition_course(db, d))
        ):
            continue
        v = authoring.working_version(db, d)
        items.append(
            DefinitionSummary(
                id=d.id,
                state=d.state,
                course_id=d.course_id,
                title=v.title,
                category=v.category,
                version_no=v.version_no,
                live_version_id=d.current_version_id if d.state != "archived" else None,
                award_policy=d.award_policy,
                updated_at=d.updated_at,
            )
        )
        if len(items) >= limit:
            break
    return DefinitionList(items=items)


@router.post("/achievements", response_model=DefinitionOut, status_code=201)
def create_achievement(
    body: CreateIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = authoring.create(
        db,
        actor,
        issuer_id=body.issuer_id,
        course_id=body.course_id,
        fields=body.fields,
        rules=body.rules,
        template_id=body.template_id,
        request_id=rid,
    )
    return _out(db, actor, d)


@router.get("/achievements/{definition_id}", response_model=DefinitionOut)
def get_achievement(definition_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> DefinitionOut:
    return _out(db, actor, _get(db, actor, definition_id))


@router.patch("/achievements/{definition_id}", response_model=DefinitionOut)
def update_achievement(
    definition_id: uuid.UUID,
    body: authoring.DraftFields,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.update_draft(db, actor, d, body, request_id=rid)
    return _out(db, actor, d)


@router.delete("/achievements/{definition_id}", status_code=204)
def delete_achievement(definition_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> Response:
    authoring.delete_draft(db, actor, _get(db, actor, definition_id))
    return Response(status_code=204)


@router.put("/achievements/{definition_id}/rules", response_model=DefinitionOut)
def put_rules(
    definition_id: uuid.UUID, body: RuleSet, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.set_rules(db, actor, d, body, request_id=rid)
    return _out(db, actor, d)


@router.post("/achievements/{definition_id}/submit", response_model=SubmitOut)
def submit(
    definition_id: uuid.UUID,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    body: SubmitIn | None = None,
) -> SubmitOut:
    d = _get(db, actor, definition_id)
    issues = authoring.submit(db, actor, d, request_id=rid, review=body.review if body else None)
    return SubmitOut(state=d.state, warnings=[Issue(**i) for i in issues])


@router.post("/achievements/{definition_id}/approve", response_model=DefinitionOut)
def approve(
    definition_id: uuid.UUID, body: ReviewIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.approve(
        db,
        actor,
        d,
        checklist=body.checklist,
        comment=body.comment,
        credit_claim_approved=body.credit_claim_approved,
        request_id=rid,
    )
    return _out(db, actor, d)


@router.post("/achievements/{definition_id}/reject", response_model=DefinitionOut)
def reject(
    definition_id: uuid.UUID, body: RejectIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.reject(db, actor, d, comment=body.comment, checklist=body.checklist, request_id=rid)
    return _out(db, actor, d)


@router.post("/achievements/{definition_id}/publish", response_model=DefinitionOut)
def publish(
    definition_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.publish(db, actor, d, request_id=rid)
    return _out(db, actor, d)


@router.post("/achievements/{definition_id}/archive", response_model=DefinitionOut)
def archive(
    definition_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.archive(db, actor, d, request_id=rid)
    return _out(db, actor, d)


@router.post("/achievements/{definition_id}/new-version", response_model=DefinitionOut)
def new_version(
    definition_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> DefinitionOut:
    d = _get(db, actor, definition_id)
    authoring.new_version(db, actor, d, request_id=rid)
    return _out(db, actor, d)


@router.get("/achievements/{definition_id}/preview")
def preview(definition_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    """Non-issued, non-verifiable preview (spec §5.5)."""
    d = _get(db, actor, definition_id)
    return preview_mod.build(db, d, authoring.working_version(db, d))


@router.get("/achievement-versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> VersionOut:
    v = db.get(AchievementVersion, version_id)
    if v is None:
        raise NotFound("NOT_FOUND", "No such version.")
    _get(db, actor, v.definition_id)
    return _version_out(v)


@router.get("/achievement-versions/{version_id}/rules")
def get_version_rules(version_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    v = db.get(AchievementVersion, version_id)
    if v is None:
        raise NotFound("NOT_FOUND", "No such version.")
    _get(db, actor, v.definition_id)
    rules = rules_store.load(db, v.id)
    return {
        "version_id": str(v.id),
        "frozen": v.frozen,
        "rules": rules.model_dump(mode="json", exclude_none=True) if rules else None,
        "source_status": rules_store.source_status(db, v.id),
    }


@router.get("/categories")
def list_categories(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    return {
        "categories": authoring.categories(db, actor.institution_id),
        "competency_categories": sorted(authoring.COMPETENCY_CATEGORIES),
        "demonstration_kinds": authoring.DEMONSTRATION_KINDS,
        "achievement_types": list(ACHIEVEMENT_TYPES),
        "review_checklist": list(authoring.REVIEW_CHECKLIST),
    }
