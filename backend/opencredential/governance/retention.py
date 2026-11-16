# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configurable retention (spec §12.5). Run daily by the ``apply_retention`` job and on demand.

What is purged, per institution settings:

* Canvas progress and submission snapshots for courses that ended in Canvas longer ago than
  ``snapshot_days_after_course_end`` (and are archived here: :mod:`opencredential.sync.lifecycle`
  notices the end and archives the course ``sync_days_after_course_end`` later).
* Submissions held for an assignment that no live badge rule uses any more, in any course.
* Eligibility evaluations older than ``evaluation_days`` that no award relies on.
* Failed background jobs older than ``failed_job_days``.
* Audit events older than ``audit_event_years`` (minimum one year, enforced in the database).

Never purged: issued credentials, their status and status lists, and award decisions. They are
needed for as long as anyone may verify a credential.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    AwardDecision,
    Course,
    EligibilityEvaluation,
    Institution,
    LmsModuleProgress,
    LmsSubmission,
)
from opencredential.db.models.tenancy import DEFAULT_RETENTION
from opencredential.sync import prune_unused_submissions


def _n(result: Any) -> int:
    """Rows affected by a DML statement."""
    return int(getattr(result, "rowcount", 0) or 0)


def apply(
    db: Session,
    institution_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    inst = db.get(Institution, institution_id)
    assert inst is not None
    r = {**DEFAULT_RETENTION, **(inst.retention or {})}
    now = now or datetime.now(UTC)
    counts: dict[str, int] = {}

    snapshot_cutoff = now - timedelta(days=int(r["snapshot_days_after_course_end"]))
    # Counted from when the course ended in Canvas. Courses archived before that was recorded
    # fall back to when they were archived or last changed.
    ended_at = func.coalesce(Course.ended_at, Course.archived_at, Course.updated_at)
    ended = select(Course.id).where(Course.status == "archived", ended_at < snapshot_cutoff)
    counts["module_progress"] = _n(
        db.execute(delete(LmsModuleProgress).where(LmsModuleProgress.course_id.in_(ended)))
    )
    counts["submissions"] = _n(
        db.execute(delete(LmsSubmission).where(LmsSubmission.course_id.in_(ended)))
    )
    counts["unused_submissions"] = prune_unused_submissions(db)

    eval_cutoff = now - timedelta(days=int(r["evaluation_days"]))
    referenced = select(AwardDecision.evaluation_id).where(AwardDecision.evaluation_id.is_not(None))
    counts["evaluations"] = _n(
        db.execute(
            delete(EligibilityEvaluation).where(
                EligibilityEvaluation.evaluated_at < eval_cutoff,
                EligibilityEvaluation.id.not_in(referenced),
            )
        )
    )

    job_cutoff = now - timedelta(days=int(r["failed_job_days"]))
    counts["failed_jobs"] = _n(
        db.execute(
            text(
                "DELETE FROM jobs.procrastinate_jobs WHERE status = 'failed'"
                " AND args->>'institution_id' = :iid"
                " AND COALESCE(scheduled_at, '-infinity') < :cutoff"
                " AND NOT EXISTS (SELECT 1 FROM jobs.procrastinate_events e"
                "   WHERE e.job_id = procrastinate_jobs.id AND e.at >= :cutoff)"
            ),
            {"iid": str(institution_id), "cutoff": job_cutoff},
        )
    )

    counts["audit_events"] = int(
        db.execute(
            text("SELECT app.purge_audit_events(:iid, :years)"),
            {"iid": institution_id, "years": int(r["audit_event_years"])},
        ).scalar()
        or 0
    )
    audit.record(
        db,
        action="retention.apply",
        resource_type="institution",
        resource_id=institution_id,
        institution_id=institution_id,
        actor_user_id=actor_user_id,
        actor_kind="user" if actor_user_id else "system",
        data={"removed": counts},
    )
    return counts
