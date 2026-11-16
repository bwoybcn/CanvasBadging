# SPDX-License-Identifier: AGPL-3.0-or-later
"""What happens to a course here once it has ended in Canvas (spec §12.5).

A course used to be read from Canvas for ever: nothing noticed that it had ended, so students'
progress and submissions were refreshed every 30 minutes for years, and the retention rule
"delete snapshots a year after the course ends" never had an end to count from. Now, once a day:

1. **Ended.** Canvas says the course is concluded (by hand, deleted, or past the end date of the
   course or its term). ``courses.ended_at`` records when. The course is still read, so marks
   released after the end date still count towards badges.
2. **Archived.** ``sync_days_after_course_end`` later (default 60 days) the course's status
   becomes ``archived``: it is no longer read from Canvas and nothing more is evaluated or
   awarded from Canvas data. Badges already issued are untouched, and staff can still award by
   hand.
3. **Snapshots deleted.** ``snapshot_days_after_course_end`` after the course ended (default
   365 days) the retention job deletes the stored progress and submissions.

If Canvas says the course is running again (the end date was moved, or it was un-concluded),
``ended_at`` is cleared. An archived course can be switched on again by course staff, but only
while Canvas says it is running.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import Course, Institution, SyncRun
from opencredential.db.models.tenancy import DEFAULT_RETENTION
from opencredential.integrations.base import (
    CourseLifecycle,
    CourseStateRecord,
    LmsAdapter,
    LmsError,
    LmsNotFound,
)
from opencredential.logging import get_logger

log = get_logger("sync.lifecycle")

ENDED, REOPENED, ARCHIVED = "ended", "reopened", "archived"


def sync_days_after_end(db: Session, course: Course) -> int:
    inst = db.get(Institution, course.institution_id)
    retention = {**DEFAULT_RETENTION, **((inst.retention if inst else None) or {})}
    return int(retention["sync_days_after_course_end"])


def read_until(db: Session, course: Course) -> datetime | None:
    """When an ended course stops being read from Canvas, or ``None`` if it has not ended."""
    if course.ended_at is None:
        return None
    return course.ended_at + timedelta(days=sync_days_after_end(db, course))


def courses_to_check(db: Session) -> list[Course]:
    """Courses of the current institution that are, or have been, read from Canvas and are not
    archived yet. Courses that were launched once but never switched on hold no Canvas data,
    so they are left alone."""
    was_read = exists().where(SyncRun.course_id == Course.id)
    return list(
        db.scalars(
            select(Course)
            .where(Course.status != "archived", or_(Course.status == "active", was_read))
            .order_by(Course.id)
        )
    )


def _state(course: Course, adapter: LmsAdapter) -> CourseStateRecord | None:
    """The course's state in the LMS, or ``None`` when it cannot be told (the adapter cannot
    say, or the LMS could not be reached: nothing is decided on a failed read)."""
    if not isinstance(adapter, CourseLifecycle):
        return None
    try:
        return adapter.course_state(course.canvas_course_id)
    except LmsNotFound:
        # The course no longer exists in the LMS.
        return CourseStateRecord(concluded=True)
    except LmsError as exc:
        log.warning("course_state_failed", course_id=str(course.id), code=exc.code)
        return None


def check(
    db: Session, course: Course, adapter: LmsAdapter, *, now: datetime | None = None
) -> str | None:
    """Bring one course in line with its state in the LMS. Returns what changed (``ended``,
    ``reopened`` or ``archived``) or ``None``. Idempotent."""
    if course.status == "archived":
        return None
    state = _state(course, adapter)
    if state is None:
        return None
    now = now or datetime.now(UTC)

    def record(action: str, **data: object) -> None:
        audit.record(
            db,
            action=action,
            resource_type="course",
            resource_id=course.id,
            institution_id=course.institution_id,
            actor_kind="system",
            data=data or None,
        )

    if not state.concluded:
        if course.ended_at is None:
            return None
        course.ended_at = None
        record("course.reopened")
        return REOPENED

    changed = None
    # The date Canvas holds wins, and is followed if it moves; without one, the day the end
    # was first noticed.
    ended = min(state.ended_at, now) if state.ended_at else (course.ended_at or now)
    if course.ended_at is None:
        record("course.ended", ended_at=ended.isoformat())
        changed = ENDED
    course.ended_at = ended
    days = sync_days_after_end(db, course)
    if now - course.ended_at >= timedelta(days=days):
        was = course.status
        course.status = "archived"
        course.archived_at = now
        record("course.archive", ended_at=course.ended_at.isoformat(), was=was, after_days=days)
        return ARCHIVED
    return changed


def running_again(course: Course, adapter: LmsAdapter) -> bool:
    """Whether an archived course is running in the LMS again, so it may be switched back on."""
    state = _state(course, adapter)
    return state is not None and not state.concluded
