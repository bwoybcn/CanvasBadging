# SPDX-License-Identifier: AGPL-3.0-or-later
"""Task definitions. Every task must be idempotent (ADR-0011, spec §17.1).

Tenant-scoped tasks carry ``institution_id`` in their arguments and open their DB session with
:func:`opencredential.db.session.tenant_session`. Producers enqueue them transactionally with
:func:`opencredential.jobs.enqueue.defer`, which also adds ``subject_type`` / ``subject_id`` for
the admin job view, so tenant tasks accept those keyword arguments.

Reliability rules applied here:

* Bounded retries with exponential backoff, for transient errors only (``RETRY_TRANSIENT``).
  Permanent failures are recorded and not retried; exhausted jobs stay ``failed`` and are
  listed in the admin failed-job view, from where they can be retried (``/admin/jobs``).
* ``queueing_lock`` stops duplicate waiting jobs for the same course; ``lock`` serialises work on
  the same subject.
* A periodic task re-queues jobs stranded by a crashed worker (stalled heartbeat).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import procrastinate
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from opencredential.db.models import (
    AchievementDefinition,
    Course,
    Institution,
    LtiLaunchState,
    LtiNonceUsed,
)
from opencredential.db.session import tenant_session
from opencredential.eligibility import service as eligibility
from opencredential.integrations.base import LmsError, LmsTransientError
from opencredential.integrations.registry import get_adapter
from opencredential.jobs import enqueue
from opencredential.logging import get_logger
from opencredential.sync import integration_for, record_failed_run, sync_course

log = get_logger("jobs")
blueprint = procrastinate.Blueprint()

RETRY = {"max_attempts": 8, "wait": 5, "exponential_wait": 2}
RETRY_TRANSIENT = procrastinate.RetryStrategy(
    max_attempts=8,
    wait=5,
    exponential_wait=2,
    retry_exceptions={LmsTransientError, OperationalError},
)
#: A job whose worker has not sent a heartbeat for this long is considered stranded.
STALLED_AFTER_SECONDS = 300


@blueprint.task(name="ping", queue="default")
def ping(message: str = "pong") -> str:
    """Health task used by tests and operators to prove the worker consumes the queue."""
    log.info("ping", message=message)
    return message


@blueprint.periodic(cron="*/10 * * * *", periodic_id="purge_lti_state")
@blueprint.task(name="purge_lti_state", queue="maintenance", queueing_lock="purge_lti_state")
def purge_lti_state(timestamp: int) -> int:
    """Delete OIDC state and nonce rows past their TTL (data-model.md retention)."""
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    with tenant_session(None) as db:
        a = db.execute(delete(LtiLaunchState).where(LtiLaunchState.created_at < cutoff))
        b = db.execute(delete(LtiNonceUsed).where(LtiNonceUsed.expires_at < datetime.now(UTC)))
    removed = (a.rowcount or 0) + (b.rowcount or 0)  # type: ignore[attr-defined]
    log.info("purge_lti_state", removed=removed)
    return removed


# ---- Canvas sync and eligibility -----------------------------------------------------------------


@blueprint.task(name="sync_course", queue="sync", retry=RETRY_TRANSIENT)
def sync_course_task(
    institution_id: str, course_id: str, kind: str = "scheduled", **_meta: Any
) -> dict[str, Any]:
    """Refresh one course's snapshot, then re-evaluate its live badges in the same commit."""
    iid, cid = uuid.UUID(institution_id), uuid.UUID(course_id)
    started = datetime.now(UTC)
    try:
        with tenant_session(iid) as db:
            course = db.get(Course, cid)
            if course is None:
                return {"status": "course_missing"}
            adapter = get_adapter(integration_for(db, course), course.canvas_course_id)
            result = sync_course(db, course, adapter, kind=kind, now=started)
            enqueue.defer(
                db,
                enqueue.EVALUATE_COURSE,
                queue="eligibility",
                institution_id=iid,
                args={"course_id": course_id, "triggered_by": "sync"},
                subject_type="course",
                subject_id=cid,
                queueing_lock=f"evaluate_course:{cid}",
            )
        log.info(
            "sync.done",
            course_id=course_id,
            status=result.status,
            learners=result.learners,
            flagged=len(result.flagged_rules),
        )
        return {
            "status": result.status,
            "failed": len(result.failed),
            "flagged_rules": result.flagged_rules,
        }
    except LmsError as exc:
        with tenant_session(iid) as db:
            course = db.get(Course, cid)
            if course is not None:
                record_failed_run(db, course, kind, exc, started)
        log.warning("sync.failed", course_id=course_id, code=exc.code)
        if isinstance(exc, LmsTransientError):
            raise  # bounded retry with backoff
        return {"status": "failed", "code": exc.code}


@blueprint.task(name="evaluate_course", queue="eligibility", retry=RETRY_TRANSIENT)
def evaluate_course_task(
    institution_id: str,
    course_id: str,
    triggered_by: str = "sync",
    version_id: str | None = None,
    **_meta: Any,
) -> dict[str, int]:
    with tenant_session(uuid.UUID(institution_id)) as db:
        counts = eligibility.evaluate_course(
            db,
            uuid.UUID(course_id),
            triggered_by=triggered_by,
            version_id=uuid.UUID(version_id) if version_id else None,
        )
    log.info("eligibility.course", course_id=course_id, **counts)
    return counts


@blueprint.task(name="evaluate_learner", queue="eligibility", retry=RETRY_TRANSIENT)
def evaluate_learner_task(
    institution_id: str,
    definition_id: str,
    user_id: str,
    triggered_by: str = "reeval",
    **_meta: Any,
) -> str | None:
    with tenant_session(uuid.UUID(institution_id)) as db:
        definition = db.get(AchievementDefinition, uuid.UUID(definition_id))
        target = eligibility.live_target(db, definition) if definition else None
        if target is None:
            return None
        record, _ = eligibility.evaluate_and_record(
            db, target, uuid.UUID(user_id), triggered_by=triggered_by
        )
        return record.outcome


@blueprint.periodic(cron="*/30 * * * *", periodic_id="schedule_course_syncs")
@blueprint.task(
    name="schedule_course_syncs", queue="maintenance", queueing_lock="schedule_course_syncs"
)
def schedule_course_syncs(timestamp: int) -> int:
    """ADR-0010: refresh every active course that has a live badge (default every 30 min)."""
    with tenant_session(None) as db:
        institutions = [
            i.id for i in db.scalars(select(Institution).where(Institution.status == "active"))
        ]
    queued = 0
    for iid in institutions:
        with tenant_session(iid) as db:
            course_ids = set(
                db.scalars(
                    select(AchievementDefinition.course_id)
                    .join(Course, Course.id == AchievementDefinition.course_id)
                    .where(
                        AchievementDefinition.state != "archived",
                        AchievementDefinition.current_version_id.is_not(None),
                        Course.status == "active",
                    )
                )
            )
            for cid in course_ids:
                if cid is None:
                    continue
                job = enqueue.defer(
                    db,
                    enqueue.SYNC_COURSE,
                    queue="sync",
                    institution_id=iid,
                    args={"course_id": str(cid), "kind": "scheduled"},
                    subject_type="course",
                    subject_id=cid,
                    queueing_lock=f"sync:{cid}",
                )
                queued += job is not None
    log.info("sync.scheduled", queued=queued)
    return queued


@blueprint.periodic(cron="*/5 * * * *", periodic_id="recover_stalled_jobs")
@blueprint.task(
    name="recover_stalled_jobs",
    queue="maintenance",
    queueing_lock="recover_stalled_jobs",
    pass_context=True,
)
async def recover_stalled_jobs(context: procrastinate.JobContext, timestamp: int) -> int:
    """Spec §17.2: a job stranded by a crashed worker goes back to the queue. Tasks are
    idempotent, so running one again is safe."""
    manager = context.app.job_manager
    stalled = list(await manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER_SECONDS))
    for job in stalled:
        await manager.retry_job(job)
    if stalled:
        log.warning("jobs.stalled_requeued", count=len(stalled))
    return len(stalled)
