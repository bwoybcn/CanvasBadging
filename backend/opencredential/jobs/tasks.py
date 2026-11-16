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
from opencredential.db.session import app_engine, tenant_session
from opencredential.eligibility import service as eligibility
from opencredential.integrations.base import LmsError, LmsTransientError
from opencredential.integrations.registry import get_adapter
from opencredential.jobs import enqueue
from opencredential.jobs import health as job_health
from opencredential.jobs.defer import defer
from opencredential.logging import get_logger
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient, SignerUnavailable
from opencredential.sync import (
    integration_for,
    needs_canvas_data,
    record_failed_run,
    sync_course,
)

#: How often courses with only staff-awarded badges refresh their roster.
ROSTER_ONLY_EVERY_HOURS = 6

log = get_logger("jobs")
blueprint = procrastinate.Blueprint()

RETRY = procrastinate.RetryStrategy(max_attempts=8, wait=5, exponential_wait=2)
RETRY_TRANSIENT = procrastinate.RetryStrategy(
    max_attempts=8,
    wait=5,
    exponential_wait=2,
    retry_exceptions={LmsTransientError, OperationalError},
)
#: Signer key retire/destroy: also retry while the signer is unreachable, which is exactly when
#: the durable retry matters (a compromised key must not survive a signer outage).
RETRY_SIGNER = procrastinate.RetryStrategy(
    max_attempts=12,
    wait=5,
    exponential_wait=2,
    retry_exceptions={SignerUnavailable, LmsTransientError, OperationalError},
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


def _refresh_roster(db: Any, integration: Any, course: Course) -> None:
    """Update course members from LTI NRPS before reading progress (W3).

    Skipped for courses never launched from Canvas (no NRPS URL, e.g. the seeded demo course).
    A roster failure keeps the previous roster: progress for those learners is still read, and
    nobody is removed on the strength of a partial answer.
    """
    if not course.lti_nrps_url:
        return
    from opencredential.lti.roster import sync_roster

    try:
        with db.begin_nested():
            res = sync_roster(db, get_settings(), integration, course)
        log.info("sync.roster", course_id=str(course.id), members=res.members)
    except LmsError as exc:
        log.warning("sync.roster_failed", course_id=str(course.id), code=exc.code)


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
            if course.status != "active":
                # Deactivated after the job was queued, or never switched on: no Canvas read,
                # no evaluation, no awards (spec §4.1).
                log.info("sync.skipped_inactive", course_id=course_id, status=course.status)
                return {"status": "course_inactive"}
            integration = integration_for(db, course)
            if kind == "roster":
                # Staff-awarded badges only: keep enrolments current, read no progress data.
                _refresh_roster(db, integration, course)
                log.info("sync.roster_only", course_id=course_id)
                return {"status": "roster_only"}
            adapter = get_adapter(integration, course.canvas_course_id)
            _refresh_roster(db, integration, course)
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
    """ADR-0010: refresh every active course that has a live badge (default every 30 min).

    Courses whose live badges read no Canvas progress (staff-awarded only, as in many recognition
    courses) get a roster-only refresh every six hours instead of a full sync every 30 minutes.
    """
    slot = datetime.fromtimestamp(timestamp, UTC)
    roster_slot = slot.hour % ROSTER_ONLY_EVERY_HOURS == 0 and slot.minute < 30
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
                course = db.get(Course, cid)
                kind = "scheduled"
                if course is not None and not needs_canvas_data(db, course):
                    if not roster_slot:
                        continue
                    kind = "roster"
                job = enqueue.defer(
                    db,
                    enqueue.SYNC_COURSE,
                    queue="sync",
                    institution_id=iid,
                    args={"course_id": str(cid), "kind": kind},
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


@blueprint.periodic(cron="47 1 * * *", periodic_id="check_course_ends")
@blueprint.task(name="check_course_ends", queue="maintenance", queueing_lock="check_course_ends")
def check_course_ends(timestamp: int) -> dict[str, int]:
    """Once a day: notice courses that have ended in Canvas, and archive those that ended longer
    ago than the institution keeps reading them (:mod:`opencredential.sync.lifecycle`). One
    course that cannot be read does not stop the others; it is looked at again tomorrow."""
    from opencredential.sync import lifecycle

    counts = {"checked": 0, lifecycle.ENDED: 0, lifecycle.REOPENED: 0, lifecycle.ARCHIVED: 0}
    for iid in _each_institution():
        with tenant_session(iid) as db:
            course_ids = [c.id for c in lifecycle.courses_to_check(db)]
        for cid in course_ids:
            adapter = None
            try:
                with tenant_session(iid) as db:
                    course = db.get(Course, cid)
                    if course is None:
                        continue
                    adapter = get_adapter(integration_for(db, course), course.canvas_course_id)
                    change = lifecycle.check(db, course, adapter)
            except LmsError as exc:  # no Canvas connection for this course yet
                log.info("course_end.skipped", course_id=str(cid), code=exc.code)
                continue
            except Exception as exc:  # one course must not stop the rest; it is retried tomorrow
                log.warning("course_end.failed", course_id=str(cid), error=type(exc).__name__)
                continue
            finally:
                close = getattr(adapter, "close", None)
                if callable(close):
                    close()
            counts["checked"] += 1
            if change:
                counts[change] += 1
                log.info("course_end.changed", course_id=str(cid), change=change)
    log.info("course_end.checked", **counts)
    return counts


ALERT_EVERY_MINUTES = 10
#: The tick at which the once-a-day reminder goes out (08:00 UTC).
ALERT_REMINDER_SECOND_OF_DAY = 8 * 3600


@blueprint.periodic(cron=f"*/{ALERT_EVERY_MINUTES} * * * *", periodic_id="alert_failed_jobs")
@blueprint.task(name="alert_failed_jobs", queue="maintenance", queueing_lock="alert_failed_jobs")
def alert_failed_jobs(timestamp: int) -> int:
    """Tell the configured chat channel about jobs that failed since the last tick, and once a
    day about failed jobs still waiting. Does nothing unless ``OC_ALERT_WEBHOOK_URL`` is set.
    Returns how many newly failed jobs it reported."""
    settings = get_settings()
    if not settings.alert_webhook_url:
        return 0
    until = datetime.fromtimestamp(timestamp, UTC)
    since = until - timedelta(minutes=ALERT_EVERY_MINUTES)
    with app_engine().connect() as conn:
        state = job_health.snapshot(conn, since=since, until=until)
    reminder = timestamp % 86400 == ALERT_REMINDER_SECOND_OF_DAY
    message = job_health.alert_text(
        state, site=settings.public_base_url, minutes=ALERT_EVERY_MINUTES, reminder=reminder
    )
    if message is None:
        return 0
    job_health.send_alert(settings.alert_webhook_url, message, settings.alert_webhook_format)
    return state.failed_recent_count


# ---- issuance and status (W4) -------------------------------------------------------------


def _signer() -> SignerClient:
    return SignerClient(get_settings())


@blueprint.task(name="issue_credential", queue="issuance", retry=RETRY)
def issue_credential(
    institution_id: str,
    decision_id: str | None = None,
    award_decision_id: str | None = None,
    **_meta: object,
) -> str:
    """Issue the credential for an award decision. Idempotent on the decision; safe to retry.

    Contract with W5 (docs/architecture/w5-delivery.md): deferred with ``decision_id``,
    ``institution_id``, ``subject_type``/``subject_id`` and queueing lock ``issue:{decision_id}``.
    ``award_decision_id`` is accepted as an alias.
    """
    from opencredential.issuance.service import IssuanceError, issue

    did = decision_id or award_decision_id
    if did is None:
        raise ValueError("issue_credential needs decision_id")
    signer = _signer()
    try:
        result = issue(
            uuid.UUID(institution_id),
            uuid.UUID(did),
            signer=signer,
            settings=get_settings(),
        )
    except IssuanceError as exc:
        # Permanent: retrying won't help. The pending row and decision stay for reconciliation.
        log.error("issuance_refused", award_decision_id=did, error=str(exc))
        return "refused"
    finally:
        signer.close()
    if result.status_list_id is not None:
        _publish_if_unpublished(uuid.UUID(institution_id), result.status_list_id)
    return result.outcome


def _publish_if_unpublished(institution_id: uuid.UUID, status_list_id: uuid.UUID) -> None:
    """Publish a brand-new status list straight away.

    Until its list is published, a credential verifies as "Unable to verify", so a student who
    downloads it at once would see that. The first publication therefore happens here, in the
    issuing job; only if it fails is it left to the queued (delayed, retried) job.
    """
    from opencredential.db.models import StatusList
    from opencredential.status.service import publish

    with tenant_session(institution_id) as db:
        sl = db.get(StatusList, status_list_id)
        needed = sl is not None and sl.published_credential is None
    if not needed:
        return
    signer = _signer()
    try:
        with tenant_session(institution_id) as db:
            publish(db, status_list_id, signer, get_settings())
    except Exception:  # any failure falls back to the queued, retried job
        log.warning("status_list_first_publish_deferred", status_list_id=str(status_list_id))
        defer_publish(institution_id, status_list_id)
    finally:
        signer.close()


def defer_publish(institution_id: uuid.UUID, status_list_id: uuid.UUID) -> None:
    """Queue a republish; the queueing lock collapses bursts of revocations into one job."""
    defer(
        "publish_status_list",
        lock=f"publish:{status_list_id}",
        schedule_in={"seconds": 10},
        institution_id=str(institution_id),
        status_list_id=str(status_list_id),
    )


@blueprint.task(name="publish_status_list", queue="status", retry=RETRY)
def publish_status_list(institution_id: str, status_list_id: str) -> None:
    from opencredential.status.service import publish

    signer = _signer()
    try:
        with tenant_session(uuid.UUID(institution_id)) as db:
            publish(db, uuid.UUID(status_list_id), signer, get_settings())
    finally:
        signer.close()


def _each_institution() -> list[uuid.UUID]:
    from opencredential.db.models import Institution

    with tenant_session(None) as db:
        return list(db.scalars(select(Institution.id).where(Institution.status == "active")))


@blueprint.periodic(cron="17 * * * *", periodic_id="republish_status_lists")
@blueprint.task(
    name="republish_status_lists", queue="maintenance", queueing_lock="republish_status_lists"
)
def republish_status_lists(timestamp: int) -> int:
    """Re-sign lists that are unpublished or due (daily), well before their 30-day validUntil."""
    from opencredential.status.service import lists_due

    count = 0
    for iid in _each_institution():
        with tenant_session(iid) as db:
            due = lists_due(db)
        for list_id in due:
            defer_publish(iid, list_id)
            count += 1
    log.info("republish_status_lists", queued=count)
    return count


@blueprint.periodic(cron="*/15 * * * *", periodic_id="reconcile_issuance")
@blueprint.task(name="reconcile_issuance", queue="maintenance", queueing_lock="reconcile_issuance")
def reconcile_issuance(timestamp: int) -> int:
    """Re-queue issuance for credentials stuck in ``pending_signature`` (spec §17.2)."""
    from opencredential.issuance.service import pending

    count = 0
    for iid in _each_institution():
        with tenant_session(iid) as db:
            stuck = [d.id for d in pending(db)]
        for decision_id in stuck:
            defer(
                "issue_credential",
                lock=f"issue:{decision_id}",
                institution_id=str(iid),
                decision_id=str(decision_id),
                subject_type="award_decision",
                subject_id=str(decision_id),
            )
            count += 1
    return count


@blueprint.task(name="signer_key_lifecycle", queue="maintenance", retry=RETRY_SIGNER)
def signer_key_lifecycle(
    key_id: str, action: str, institution_id: str | None = None, **_meta: Any
) -> str:
    """Retire or destroy a key in the signer after the change that needs it has committed.

    Usually already done straight after the commit; this is the durable retry. Idempotent.
    A destruction is recorded on the key (``destroyed_at``) once the signer has confirmed it.
    """
    from opencredential.institutions.keys import apply_in_signer, mark_destroyed

    signer = _signer()
    try:
        apply_in_signer(signer, action, uuid.UUID(key_id))
    finally:
        signer.close()
    if action == "destroy" and institution_id:
        with tenant_session(uuid.UUID(institution_id)) as db:
            mark_destroyed(db, uuid.UUID(key_id), reason="compromise")
    return action


@blueprint.periodic(cron="41 3 * * *", periodic_id="destroy_retired_keys")
@blueprint.task(
    name="destroy_retired_keys", queue="maintenance", queueing_lock="destroy_retired_keys"
)
def destroy_retired_keys(timestamp: int) -> int:
    """Erase private material of keys retired more than 30 days ago (public keys stay).

    Each destruction is recorded on the key and audited, so a key is only destroyed once.
    """
    from opencredential.institutions.keys import keys_due_for_destruction, mark_destroyed

    signer = _signer()
    count = 0
    try:
        for iid in _each_institution():
            with tenant_session(iid) as db:
                ids = [k.id for k in keys_due_for_destruction(db)]
            for key_id in ids:
                signer.destroy_key(key_id)
                with tenant_session(iid) as db:
                    mark_destroyed(db, key_id, reason="retired")
                count += 1
    finally:
        signer.close()
    return count


# ---- retention (W7, spec §12.5) ------------------------------------------------------------


@blueprint.periodic(cron="23 2 * * *", periodic_id="apply_retention")
@blueprint.task(name="apply_retention", queue="maintenance", queueing_lock="apply_retention")
def apply_retention(timestamp: int) -> dict[str, dict[str, int]]:
    """Purge what each institution's retention settings say has expired."""
    from opencredential.governance import retention

    out = {}
    for iid in _each_institution():
        with tenant_session(iid) as db:
            out[str(iid)] = retention.apply(db, iid)
    log.info("retention.applied", institutions=len(out))
    return out
