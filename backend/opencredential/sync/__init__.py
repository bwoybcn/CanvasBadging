# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas → snapshot synchronisation (ADR-0010, spec §4.4, §6.4, §17.1).

``sync_course`` reads one course through an :class:`LmsAdapter` and upserts the ``lms_*``
snapshot rows the rules engine evaluates. It never decides anything itself, and it is safe to
run repeatedly (idempotent upserts keyed by Canvas ids).

* Partial failure: a learner whose progress cannot be read is listed in the run's
  ``error.failed`` map; the snapshot loader turns that into ``DATA_UNAVAILABLE`` (``unknown``)
  for that learner only.
* Source changes: a module or assignment used by a *live* badge that disappears, loses its
  completion requirements or changes points possible flags the rule (``source_status``) and is
  audited. Affected rules evaluate to ``unknown`` until a lecturer reviews the badge, so
  issuance pauses rather than silently changing meaning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    AchievementDefinition,
    AwardRule,
    AwardRuleSet,
    CanvasIntegration,
    Course,
    ExternalIdentity,
    LmsAssignment,
    LmsModule,
    LmsModuleProgress,
    LmsSubmission,
    Membership,
    SyncRun,
    User,
)
from opencredential.integrations.base import LmsAdapter, LmsError, LmsTransientError
from opencredential.logging import get_logger

log = get_logger("sync")


@dataclass
class SyncResult:
    run_id: uuid.UUID
    status: str
    learners: int = 0
    failed: dict[str, list[str]] = field(default_factory=dict)
    flagged_rules: list[str] = field(default_factory=list)
    changed: bool = False


def course_learners(db: Session, course: Course) -> dict[uuid.UUID, str | None]:
    """Active students of ``course`` → their LMS user id (``None`` if unknown)."""
    rows = db.execute(
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.scope_type == "course",
            Membership.scope_id == course.id,
            Membership.role == "student",
            Membership.revoked_at.is_(None),
            User.is_test_user.is_(False),  # Canvas's Student View test user
        )
    ).all()
    ids = [r[0] for r in rows]
    lms = dict(
        db.execute(
            select(ExternalIdentity.user_id, ExternalIdentity.value).where(
                ExternalIdentity.user_id.in_(ids),
                ExternalIdentity.kind == "canvas_user_id",
                ExternalIdentity.canvas_integration_id == course.canvas_integration_id,
            )
        ).all()
    )
    return {uid: lms.get(uid) for uid in ids}


#: Rule types whose answer comes from Canvas progress data (modules, submissions, scores).
#: ``manual_approval`` and ``group`` read nothing from Canvas themselves.
CANVAS_DATA_RULES = frozenset(
    {"module_completed", "modules_completed", "assignment_submitted", "assignment_score"}
)


def needs_canvas_data(db: Session, course: Course) -> bool:
    """Whether any live badge in ``course`` has a rule that reads Canvas progress. Courses whose
    badges are only awarded by staff (manual awards, list awards, staff approval), such as many
    recognition courses, need their roster kept fresh but not a full progress sync."""
    return any(r.type in CANVAS_DATA_RULES for r in _live_rules(db, course))


def _live_rules(db: Session, course: Course) -> list[AwardRule]:
    return list(
        db.scalars(
            select(AwardRule)
            .join(AwardRuleSet, AwardRuleSet.id == AwardRule.rule_set_id)
            .join(
                AchievementDefinition,
                AchievementDefinition.current_version_id == AwardRuleSet.version_id,
            )
            .where(
                AchievementDefinition.course_id == course.id,
                AchievementDefinition.state != "archived",
            )
        )
    )


def _flag(
    rule: AwardRule, status: str, reason: str, changes: list[tuple[AwardRule, str, str]]
) -> None:
    if rule.source_status == "ok" or (status == "source_missing" and rule.source_status != status):
        rule.source_status = status
        changes.append((rule, status, reason))


def sync_course(
    db: Session,
    course: Course,
    adapter: LmsAdapter,
    *,
    kind: str = "scheduled",
    now: datetime | None = None,
) -> SyncResult:
    """Synchronise one course. Raises :class:`LmsTransientError` for whole-course failures so the
    job can retry; the caller records the failed run in a separate transaction."""
    now = now or datetime.now(UTC)
    run = SyncRun(
        institution_id=course.institution_id,
        course_id=course.id,
        kind=kind,
        started_at=now,
        status="running",
    )
    db.add(run)
    db.flush()
    ref = course.canvas_course_id
    result = SyncResult(run_id=run.id, status="ok")

    # ---- course structure (whole-course failure raises) ----------------------------------
    modules = {m.module_id: m for m in adapter.list_modules(ref)}
    assignments = {a.assignment_id: a for a in adapter.list_assignments(ref)}

    old_modules = {
        m.canvas_module_id: m
        for m in db.scalars(select(LmsModule).where(LmsModule.course_id == course.id))
    }
    old_assignments = {
        a.canvas_assignment_id: a
        for a in db.scalars(select(LmsAssignment).where(LmsAssignment.course_id == course.id))
    }
    changes: list[tuple[AwardRule, str, str]] = []
    live = _live_rules(db, course)

    def rules_using(kind_: str, ref_id: str) -> list[AwardRule]:
        out = []
        for r in live:
            p = r.params
            if kind_ == "module" and (
                p.get("module_id") == ref_id or ref_id in p.get("module_ids", [])
            ):
                out.append(r)
            if kind_ == "assignment" and p.get("assignment_id") == ref_id:
                out.append(r)
        return out

    for mid, rec in modules.items():
        row = old_modules.get(mid)
        if row is None:
            db.add(
                LmsModule(
                    institution_id=course.institution_id,
                    course_id=course.id,
                    canvas_module_id=mid,
                    name=rec.name,
                    requirement_type=rec.requirement_type,
                    has_requirements=rec.has_requirements,
                    workflow_state=rec.workflow_state,
                    fetched_at=now,
                )
            )
            continue
        if row.has_requirements and not rec.has_requirements:
            for r in rules_using("module", mid):
                _flag(
                    r, "source_changed", f"module {mid} lost its completion requirements", changes
                )
        # A module that reappears keeps its flag: a lecturer still reviews (no silent un-flag).
        row.name, row.requirement_type = rec.name, rec.requirement_type
        row.has_requirements, row.workflow_state, row.fetched_at = (
            rec.has_requirements,
            rec.workflow_state,
            now,
        )
    for mid, row in old_modules.items():
        if mid not in modules and row.workflow_state != "deleted":
            row.workflow_state, row.fetched_at = "deleted", now
            for r in rules_using("module", mid):
                _flag(r, "source_missing", f"module {mid} was removed from Canvas", changes)

    for aid, arec in assignments.items():
        a = old_assignments.get(aid)
        if a is None:
            db.add(
                LmsAssignment(
                    institution_id=course.institution_id,
                    course_id=course.id,
                    canvas_assignment_id=aid,
                    name=arec.name,
                    points_possible=arec.points_possible,
                    published=arec.published,
                    deleted=False,
                    fetched_at=now,
                )
            )
            continue
        if a.points_possible != arec.points_possible and not a.deleted:
            for r in rules_using("assignment", aid):
                if r.type == "assignment_score":
                    _flag(
                        r,
                        "source_changed",
                        f"assignment {aid} points possible changed from {a.points_possible} "
                        f"to {arec.points_possible}",
                        changes,
                    )
        a.name, a.points_possible, a.published, a.deleted, a.fetched_at = (
            arec.name,
            arec.points_possible,
            arec.published,
            False,
            now,
        )
    for aid, a in old_assignments.items():
        if aid not in assignments and not a.deleted:
            a.deleted, a.fetched_at = True, now
            for r in rules_using("assignment", aid):
                _flag(r, "source_missing", f"assignment {aid} was removed from Canvas", changes)
    db.flush()

    # ---- learners ------------------------------------------------------------------------
    learners = course_learners(db, course)
    result.learners = len(learners)
    failed: dict[str, list[str]] = {}
    by_lms = {lms: uid for uid, lms in learners.items() if lms}
    for uid, lms in learners.items():
        if lms is None:
            failed[str(uid)] = ["modules", "submissions"]

    progress_rows = {
        (p.user_id, p.canvas_module_id): p
        for p in db.scalars(
            select(LmsModuleProgress).where(LmsModuleProgress.course_id == course.id)
        )
    }
    for lms, uid in by_lms.items():
        try:
            records = adapter.list_module_progress(ref, lms)
        except LmsTransientError:
            raise
        except LmsError as exc:
            failed.setdefault(str(uid), []).append("modules")
            log.warning("sync.progress_failed", course_id=str(course.id), code=exc.code)
            continue
        for prec in records:
            prow = progress_rows.get((uid, prec.module_id))
            if prow is None:
                db.add(
                    LmsModuleProgress(
                        institution_id=course.institution_id,
                        course_id=course.id,
                        user_id=uid,
                        canvas_module_id=prec.module_id,
                        state=prec.state,
                        completed_at=prec.completed_at,
                        fetched_at=now,
                    )
                )
                result.changed = True
            else:
                if (prow.state, prow.completed_at) != (prec.state, prec.completed_at):
                    result.changed = True
                prow.state, prow.completed_at, prow.fetched_at = prec.state, prec.completed_at, now

    sub_rows = {
        (s.user_id, s.canvas_assignment_id): s
        for s in db.scalars(select(LmsSubmission).where(LmsSubmission.course_id == course.id))
    }
    try:
        subs = adapter.list_submissions(ref, list(assignments), list(by_lms)) if by_lms else []
    except LmsTransientError:
        raise
    except LmsError as exc:
        log.warning("sync.submissions_failed", course_id=str(course.id), code=exc.code)
        subs = []
        for uid in by_lms.values():
            failed.setdefault(str(uid), []).append("submissions")
    for srec in subs:
        suid = by_lms.get(srec.lms_user_id)
        if suid is None:
            continue
        values = {
            "workflow_state": srec.workflow_state,
            "submitted_at": srec.submitted_at,
            "score": srec.score,
            "excused": srec.excused,
            "posted_at": srec.posted_at,
            "grade_matches_current_submission": srec.grade_matches_current_submission,
            "missing": srec.missing,
            "late": srec.late,
        }
        row2 = sub_rows.get((suid, srec.assignment_id))
        if row2 is None:
            db.add(
                LmsSubmission(
                    institution_id=course.institution_id,
                    course_id=course.id,
                    user_id=suid,
                    canvas_assignment_id=srec.assignment_id,
                    fetched_at=now,
                    **values,
                )
            )
            result.changed = True
        else:
            if any(getattr(row2, k) != v for k, v in values.items()):
                result.changed = True
            for k, v in values.items():
                setattr(row2, k, v)
            row2.fetched_at = now

    # ---- finish --------------------------------------------------------------------------
    for rule, status, reason in changes:
        result.flagged_rules.append(str(rule.id))
        audit.record(
            db,
            action="rule.source_flagged",
            resource_type="award_rule",
            resource_id=rule.id,
            institution_id=course.institution_id,
            actor_kind="system",
            data={"status": status, "reason": reason, "course_id": str(course.id)},
        )
    result.failed = failed
    result.status = "partial" if failed else "ok"
    run.status = result.status
    run.finished_at = datetime.now(UTC)
    run.error = {"failed": failed} if failed else None
    if changes:
        result.changed = True
    return result


def record_failed_run(
    db: Session, course: Course, kind: str, error: Exception, started_at: datetime
) -> None:
    code = getattr(error, "code", type(error).__name__)
    db.add(
        SyncRun(
            institution_id=course.institution_id,
            course_id=course.id,
            kind=kind,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status="failed",
            error={"code": code, "message": str(error)[:500]},
        )
    )


def integration_for(db: Session, course: Course) -> CanvasIntegration:
    integration = db.get(CanvasIntegration, course.canvas_integration_id)
    assert integration is not None
    return integration


def last_sync(db: Session, course_id: uuid.UUID) -> SyncRun | None:
    return db.scalar(
        select(SyncRun)
        .where(SyncRun.course_id == course_id)
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )


def sync_state(db: Session, course_id: uuid.UUID) -> dict[str, Any]:
    run = last_sync(db, course_id)
    ok = db.scalar(
        select(SyncRun)
        .where(SyncRun.course_id == course_id, SyncRun.status.in_(("ok", "partial")))
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    return {
        "last_run": None
        if run is None
        else {
            "status": run.status,
            "kind": run.kind,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": (run.error or {}).get("code"),
            "failed_learners": len((run.error or {}).get("failed", {})),
        },
        "last_success_at": ok.finished_at if ok else None,
    }
