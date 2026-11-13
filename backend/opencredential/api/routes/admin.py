# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institution awarding/approval policy, failed jobs and data freshness (spec §6.5, §10, §17).

W7 builds the full administration area; this router carries the pieces the rules engine and
job reliability need now: the institution-wide default for score-based badges (Gary's decision,
ADR-0017), the review policy, the failed-job view with retry, and stale-course detection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, text

from opencredential import audit
from opencredential.api.deps import ActorDep, RequestIdDep, TenantDb
from opencredential.authz import policy as authz
from opencredential.db.models import AchievementDefinition, Course, Institution, background_jobs
from opencredential.errors import Conflict, NotFound
from opencredential.sync import sync_state

router = APIRouter(prefix="/api/v1", tags=["administration"])


class AwardPolicyIn(BaseModel):
    score_rules_default_policy: Literal["automatic", "lecturer_confirmed"] | None = None
    score_rules_force_confirmation: bool | None = None
    definitions_require_approval: bool | None = None
    self_approval_allowed: bool | None = None
    manual_awards_require_second_approval: bool | None = None
    max_snapshot_age_minutes: int | None = None


POLICY_KEYS = tuple(AwardPolicyIn.model_fields)


@router.get("/institutions/current/policy")
def get_policy(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    policy = authz.institution_policy(db, actor.institution_id)
    return {k: policy.get(k) for k in POLICY_KEYS}


@router.patch("/institutions/current/policy")
def update_policy(
    body: AwardPolicyIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    inst = db.get(Institution, actor.institution_id)
    assert inst is not None
    changes = body.model_dump(exclude_none=True)
    if (
        "max_snapshot_age_minutes" in changes
        and not 15 <= changes["max_snapshot_age_minutes"] <= 1440
    ):
        from opencredential.errors import Invalid

        raise Invalid("POLICY_INVALID", "Maximum data age must be between 15 and 1440 minutes.")
    inst.policy = {**(inst.policy or {}), **changes}
    audit.record(
        db,
        action="institution.policy_update",
        resource_type="institution",
        resource_id=inst.id,
        institution_id=inst.id,
        actor_user_id=actor.user_id,
        request_id=rid,
        data={"changes": changes},
    )
    policy = authz.institution_policy(db, actor.institution_id)
    return {k: policy.get(k) for k in POLICY_KEYS}


@router.get("/admin/jobs")
def list_jobs(
    db: TenantDb,
    actor: ActorDep,
    status: Literal["failed", "todo", "doing", "succeeded", "cancelled", "aborted"] = "failed",
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Failed-job view (spec §17.1 "dead-letter or failed-job handling")."""
    authz.require_inst_admin(actor)
    rows = db.execute(
        select(background_jobs)
        .where(background_jobs.c.status == status)
        .order_by(background_jobs.c.id.desc())
        .limit(limit)
    ).mappings()
    return [
        {
            "id": r["id"],
            "task": r["task_name"],
            "queue": r["queue_name"],
            "status": r["status"],
            "attempts": r["attempts"],
            "scheduled_at": r["scheduled_at"],
            "subject_type": r["subject_type"],
            "subject_id": r["subject_id"],
        }
        for r in rows
    ]


@router.post("/admin/jobs/{job_id}/retry")
def retry_job(job_id: int, db: TenantDb, actor: ActorDep, rid: RequestIdDep) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    row = db.execute(
        select(background_jobs.c.status).where(background_jobs.c.id == job_id)
    ).first()  # visible only if the job belongs to this institution
    if row is None:
        raise NotFound("NOT_FOUND", "No such job.")
    if row[0] != "failed":
        raise Conflict("INVALID_STATE", "Only failed jobs can be retried.")
    db.execute(
        text("SELECT jobs.procrastinate_retry_job_v2(:id, :at, NULL, NULL, NULL)"),
        {"id": job_id, "at": datetime.now(UTC)},
    )
    audit.record(
        db,
        action="job.retry",
        resource_type="background_job",
        resource_id=str(job_id),
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=rid,
    )
    return {"id": job_id, "status": "todo"}


@router.get("/admin/data-freshness")
def data_freshness(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    """Courses with live badges whose Canvas data is older than the policy allows (stale data
    detection, spec §17.1). Rules on stale data evaluate to ``unknown``, so nothing is issued."""
    authz.require_inst_admin(actor)
    policy = authz.institution_policy(db, actor.institution_id)
    max_age = timedelta(minutes=int(policy.get("max_snapshot_age_minutes", 120)))
    course_ids = set(
        db.scalars(
            select(AchievementDefinition.course_id).where(
                AchievementDefinition.state != "archived",
                AchievementDefinition.current_version_id.is_not(None),
                AchievementDefinition.course_id.is_not(None),
            )
        )
    )
    now = datetime.now(UTC)
    out = []
    for cid in course_ids:
        course = db.get(Course, cid) if cid else None
        if cid is None or course is None:
            continue
        state = sync_state(db, cid)
        last = state["last_success_at"]
        out.append(
            {
                "course_id": str(cid),
                "title": course.title,
                **state,
                "stale": last is None or now - last > max_age,
            }
        )
    return sorted(out, key=lambda r: (not r["stale"], r["title"]))
