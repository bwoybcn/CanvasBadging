# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transactional enqueue (ADR-0011): a job is deferred in the *same* transaction as the business
write that causes it, so a rollback never leaves an orphan job and a commit never loses one.

This calls procrastinate's own ``procrastinate_defer_jobs_v1`` SQL function through the
caller's SQLAlchemy session. Tasks are addressed by name, so a producer does not need to import
the task's implementation (for example ``oc:issue_credential``, owned by the issuance module).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ISSUE_CREDENTIAL = "oc:issue_credential"
SYNC_COURSE = "oc:sync_course"
EVALUATE_COURSE = "oc:evaluate_course"
EVALUATE_LEARNER = "oc:evaluate_learner"


def defer(
    db: Session,
    task_name: str,
    *,
    queue: str,
    institution_id: uuid.UUID,
    args: dict[str, Any],
    subject_type: str | None = None,
    subject_id: str | uuid.UUID | None = None,
    queueing_lock: str | None = None,
    lock: str | None = None,
) -> int | None:
    """Defer ``task_name`` inside ``db``'s transaction.

    Returns the job id, or ``None`` when ``queueing_lock`` shows an identical job is already
    waiting (which is the idempotent outcome, not an error).
    """
    payload = {
        **args,
        "institution_id": str(institution_id),
        "subject_type": subject_type,
        "subject_id": str(subject_id) if subject_id is not None else None,
    }
    try:
        with db.begin_nested():
            return db.execute(
                text(
                    "SELECT (jobs.procrastinate_defer_jobs_v1(ARRAY[ROW(:queue, :task, 0, :lock,"
                    " :qlock, CAST(:args AS jsonb), NULL)::jobs.procrastinate_job_to_defer_v1]))[1]"
                ),
                {
                    "queue": queue,
                    "task": task_name,
                    "lock": lock,
                    "qlock": queueing_lock,
                    "args": json.dumps(payload, default=str),
                },
            ).scalar_one()
    except IntegrityError:
        if queueing_lock is None:
            raise
        return None
