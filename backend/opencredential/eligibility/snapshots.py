# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build :class:`LearnerSnapshot` objects from the ``lms_*`` tables (read side of ADR-0010).

:class:`CourseData` loads a course once so that evaluating every learner for every badge is a
handful of queries rather than one per learner per rule.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.db.models import (
    LmsAssignment,
    LmsModule,
    LmsModuleProgress,
    LmsSubmission,
    ManualRuleApproval,
    SyncRun,
)
from opencredential.rules.snapshot import (
    Approval,
    AssignmentInfo,
    LearnerSnapshot,
    ModuleInfo,
    ModuleProgress,
    Submission,
)


@dataclass
class CourseData:
    course_id: uuid.UUID | None
    modules: dict[str, ModuleInfo]
    assignments: dict[str, AssignmentInfo]
    progress: dict[uuid.UUID, dict[str, ModuleProgress]]
    submissions: dict[uuid.UUID, dict[str, Submission]]
    synced_at: datetime | None
    failed: dict[str, list[str]]

    @classmethod
    def empty(cls) -> CourseData:
        return cls(None, {}, {}, {}, {}, None, {})


def _latest_run(db: Session, course_id: uuid.UUID, statuses: tuple[str, ...]) -> SyncRun | None:
    return db.scalar(
        select(SyncRun)
        .where(SyncRun.course_id == course_id, SyncRun.status.in_(statuses))
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )


def load_course(db: Session, course_id: uuid.UUID | None) -> CourseData:
    if course_id is None:
        return CourseData.empty()
    modules = {
        m.canvas_module_id: ModuleInfo(
            m.canvas_module_id, m.name, m.workflow_state, m.has_requirements, m.fetched_at
        )
        for m in db.scalars(select(LmsModule).where(LmsModule.course_id == course_id))
    }
    assignments = {
        a.canvas_assignment_id: AssignmentInfo(
            a.canvas_assignment_id,
            a.name,
            a.points_possible,
            a.published,
            a.deleted,
            a.fetched_at,
            a.submissions_synced,
        )
        for a in db.scalars(select(LmsAssignment).where(LmsAssignment.course_id == course_id))
    }
    progress: dict[uuid.UUID, dict[str, ModuleProgress]] = {}
    for p in db.scalars(select(LmsModuleProgress).where(LmsModuleProgress.course_id == course_id)):
        progress.setdefault(p.user_id, {})[p.canvas_module_id] = ModuleProgress(
            p.canvas_module_id, p.state, p.completed_at, p.fetched_at
        )
    submissions: dict[uuid.UUID, dict[str, Submission]] = {}
    for s in db.scalars(select(LmsSubmission).where(LmsSubmission.course_id == course_id)):
        submissions.setdefault(s.user_id, {})[s.canvas_assignment_id] = Submission(
            s.canvas_assignment_id,
            s.workflow_state,
            s.submitted_at,
            s.score,
            s.excused,
            s.posted_at,
            s.grade_matches_current_submission,
            s.missing,
            s.fetched_at,
        )
    # The latest usable run and the latest failed run, looked up directly: however many
    # failures follow the last good run, the newest failure is still seen.
    ok = _latest_run(db, course_id, ("ok", "partial"))
    last_failure = _latest_run(db, course_id, ("failed",))
    failed: dict[str, list[str]] = {}
    if ok is not None and last_failure is not None and last_failure.started_at > ok.started_at:
        # The latest attempt failed entirely: keep the earlier data but treat it as unavailable
        # for everyone, so nothing is issued from a snapshot we just failed to refresh.
        failed = {"*": ["modules", "submissions"]}
    elif ok is not None and ok.error:
        failed = dict(ok.error.get("failed", {}))
    return CourseData(
        course_id,
        modules,
        assignments,
        progress,
        submissions,
        ok.finished_at if ok else None,
        failed,
    )


def approvals_for(
    db: Session, version_id: uuid.UUID, user_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, dict[str, Approval]]:
    q = select(ManualRuleApproval).where(ManualRuleApproval.version_id == version_id)
    if user_ids is not None:
        q = q.where(ManualRuleApproval.user_id.in_(user_ids))
    out: dict[uuid.UUID, dict[str, Approval]] = {}
    for a in db.scalars(q.order_by(ManualRuleApproval.decided_at, ManualRuleApproval.id)):
        out.setdefault(a.user_id, {})[str(a.rule_id)] = Approval(
            str(a.rule_id), a.decision, a.decided_at, str(a.decided_by)
        )
    return out


def snapshot(
    data: CourseData,
    user_id: uuid.UUID,
    *,
    approvals: dict[str, Approval],
    rule_source_status: dict[str, str],
    max_age_minutes: int,
    now: datetime | None = None,
) -> LearnerSnapshot:
    unavailable = set(data.failed.get(str(user_id), [])) | set(data.failed.get("*", []))
    return LearnerSnapshot(
        learner_ref=str(user_id),
        now=now or datetime.now(UTC),
        max_age=timedelta(minutes=max_age_minutes),
        modules=data.modules,
        module_progress=data.progress.get(user_id, {}),
        assignments=data.assignments,
        submissions=data.submissions.get(user_id, {}),
        approvals=approvals,
        unavailable=frozenset(unavailable),
        synced_at=data.synced_at,
        rule_source_status=rule_source_status,
    )
