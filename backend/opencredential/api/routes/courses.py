# SPDX-License-Identifier: AGPL-3.0-or-later
"""``/api/v1/courses``: course pickers, Canvas refresh and progress (spec §4.4, §8.2, §13)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from opencredential import audit
from opencredential.api.deps import ActorDep, RequestIdDep, SettingsDep, TenantDb
from opencredential.authz import policy as authz
from opencredential.credentials.state import CredentialState
from opencredential.db.models import Course, LmsAssignment, LmsModule, SyncRun
from opencredential.eligibility import progress
from opencredential.errors import Conflict, Forbidden, NotFound, RateLimited
from opencredential.jobs import enqueue
from opencredential.sync import sync_state

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


class CourseOut(BaseModel):
    id: uuid.UUID
    title: str
    course_code: str | None
    status: str
    roles: list[str]
    #: Whether the caller works on this course's badges: its own staff, or an administrator over
    #: it. Decided here so the screens keep no role list of their own.
    staff: bool = False
    badge_teams: bool = False


class BadgeTeamsIn(BaseModel):
    enabled: bool


def _course(
    db: TenantDb, actor: authz.Actor, course_id: uuid.UUID, *, staff: bool = True
) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise NotFound("NOT_FOUND", "No such course.")
    if staff:
        if not authz.is_course_staff(db, actor, course):
            raise NotFound("NOT_FOUND", "No such course.")
    elif not (authz.is_course_staff(db, actor, course) or authz.is_student_in(actor, course.id)):
        raise NotFound("NOT_FOUND", "No such course.")
    return course


@router.get("", response_model=list[CourseOut])
def my_courses(db: TenantDb, actor: ActorDep) -> list[CourseOut]:
    ids = actor.course_ids({"student", *authz.COURSE_STAFF})
    q = select(Course)
    if not actor.is_inst_admin and not actor.has("dept_admin"):
        q = q.where(Course.id.in_(ids))
    out = []
    for c in db.scalars(q.order_by(Course.title)):
        roles = sorted(actor.course_roles(c.id))
        staff = authz.is_course_staff(db, actor, c)
        if not roles and staff:
            roles = ["admin"]
        if roles:
            out.append(
                CourseOut(
                    id=c.id,
                    title=c.title,
                    course_code=c.course_code,
                    status=c.status,
                    roles=roles,
                    staff=staff,
                    badge_teams=c.badge_teams,
                )
            )
    return out


@router.get("/{course_id}/issuers")
def course_issuers(course_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    course = _course(db, actor, course_id)
    return [
        {"id": str(i.id), "name": i.name, "did": i.did}
        for i in authz.usable_issuers(db, actor, course)
    ]


@router.get("/{course_id}/canvas/modules")
def course_modules(course_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    rows = db.scalars(
        select(LmsModule)
        .where(LmsModule.course_id == course.id, LmsModule.workflow_state != "deleted")
        .order_by(LmsModule.canvas_module_id)
    )
    return {
        "items": [
            {
                "id": m.canvas_module_id,
                "name": m.name,
                "published": m.workflow_state == "active",
                "has_requirements": m.has_requirements,
                "requirement_type": m.requirement_type,
                "usable": m.has_requirements,
            }
            for m in rows
        ],
        "sync": sync_state(db, course.id),
    }


@router.get("/{course_id}/canvas/assignments")
def course_assignments(course_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    rows = db.scalars(
        select(LmsAssignment)
        .where(LmsAssignment.course_id == course.id, LmsAssignment.deleted.is_(False))
        .order_by(LmsAssignment.name)
    )
    return {
        "items": [
            {
                "id": a.canvas_assignment_id,
                "name": a.name,
                "points_possible": a.points_possible,
                "published": a.published,
                "score_rules_allowed": bool(a.points_possible),
            }
            for a in rows
        ],
        "sync": sync_state(db, course.id),
    }


@router.get("/{course_id}/sync")
def get_sync(course_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    course = _course(db, actor, course_id, staff=False)
    return sync_state(db, course.id)


@router.post("/{course_id}/sync", status_code=202)
def request_sync(
    course_id: uuid.UUID, db: TenantDb, actor: ActorDep, settings: SettingsDep, rid: RequestIdDep
) -> dict[str, Any]:
    """On-demand refresh from Canvas (rate-limited per course, spec §4.4)."""
    course = _course(db, actor, course_id, staff=False)
    if course.status != "active":
        # Inactive courses take no part (spec §4.1): reading Canvas would evaluate and award.
        raise Conflict(
            "COURSE_NOT_ACTIVE",
            "Badges are switched off for this course, so it is not read from Canvas.",
        )
    recent = db.scalar(
        select(SyncRun.started_at)
        .where(SyncRun.course_id == course.id, SyncRun.kind == "on_demand")
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    window = timedelta(seconds=settings.sync_min_interval_seconds)
    if recent is not None and datetime.now(UTC) - recent < window:
        raise RateLimited(
            "SYNC_RATE_LIMITED", "This course was refreshed recently. Try again in a few minutes."
        )
    job = enqueue.defer(
        db,
        enqueue.SYNC_COURSE,
        queue="sync",
        institution_id=actor.institution_id,
        args={"course_id": str(course.id), "kind": "on_demand"},
        subject_type="course",
        subject_id=course.id,
        queueing_lock=f"sync:{course.id}",
    )
    audit.record(
        db,
        action="course.sync_requested",
        resource_type="course",
        resource_id=course.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=rid,
    )
    return {"queued": job is not None, "job_id": job}


def _running_again(db: TenantDb, course: Course) -> bool:
    from opencredential.integrations.base import LmsError
    from opencredential.integrations.registry import get_adapter
    from opencredential.sync import integration_for, lifecycle

    try:
        adapter = get_adapter(integration_for(db, course), course.canvas_course_id)
    except LmsError:
        return False
    try:
        return lifecycle.running_again(course, adapter)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


class CourseActivationOut(BaseModel):
    id: uuid.UUID
    status: str
    activated_at: datetime | None
    sync_queued: bool


def _activation_course(db: TenantDb, actor: authz.Actor, course_id: uuid.UUID) -> Course:
    course = _course(db, actor, course_id)  # course staff or an administrator over it; else 404
    if not (
        actor.course_roles(course.id) & authz.COURSE_STAFF
        or actor.is_inst_admin
        or authz.is_dept_admin_over(db, actor, course.org_unit_id)
    ):
        raise Forbidden("FORBIDDEN", "Only course staff or an administrator can change this.")
    return course


@router.post("/{course_id}/activate", response_model=CourseActivationOut)
def activate_course(
    course_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> CourseActivationOut:
    """Switch micro-credentials on for a course (spec §4.1): it joins scheduled Canvas
    reconciliation and an initial sync is queued at once. Idempotent."""
    course = _activation_course(db, actor, course_id)
    if course.status == "archived":
        # Archived because it ended in Canvas. It can come back only if Canvas says it is
        # running again (its end date was moved, or it was opened again).
        if not _running_again(db, course):
            raise Conflict(
                "COURSE_ARCHIVED",
                "This course has ended in Canvas, so badges are switched off for it. If the "
                "course is opened again in Canvas, you can switch badges on here.",
            )
        course.ended_at = None
        course.archived_at = None
    job = None
    if course.status != "active":
        course.status = "active"
        course.activated_at = datetime.now(UTC)
        course.activated_by = actor.user_id
        audit.record(
            db,
            action="course.activate",
            resource_type="course",
            resource_id=course.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=rid,
        )
        job = enqueue.defer(
            db,
            enqueue.SYNC_COURSE,
            queue="sync",
            institution_id=actor.institution_id,
            args={"course_id": str(course.id), "kind": "initial"},
            subject_type="course",
            subject_id=course.id,
            queueing_lock=f"sync:{course.id}",
        )
    db.flush()
    return CourseActivationOut(
        id=course.id,
        status=course.status,
        activated_at=course.activated_at,
        sync_queued=job is not None,
    )


@router.post("/{course_id}/deactivate", response_model=CourseActivationOut)
def deactivate_course(
    course_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> CourseActivationOut:
    """Stop scheduled Canvas reconciliation for a course. Issued credentials are untouched."""
    course = _activation_course(db, actor, course_id)
    if course.status == "active":
        course.status = "inactive"
        audit.record(
            db,
            action="course.deactivate",
            resource_type="course",
            resource_id=course.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=rid,
        )
    db.flush()
    return CourseActivationOut(
        id=course.id, status=course.status, activated_at=course.activated_at, sync_queued=False
    )


def _course_records(
    db: TenantDb, actor: authz.Actor, course_id: uuid.UUID, status: str | None
) -> list[dict[str, Any]]:
    from opencredential.governance import records

    course = _course(db, actor, course_id)  # course staff or an administrator over it; else 404
    return records.records(db, actor, course_staff_of=course.id, status=status, limit=1_000_000)


@router.get("/{course_id}/credentials")
def course_credentials(
    course_id: uuid.UUID,
    db: TenantDb,
    actor: ActorDep,
    status: CredentialState | None = None,
) -> list[dict[str, Any]]:
    """Award history for course staff (spec §2.2): every credential issued in this course."""
    return _course_records(db, actor, course_id, status)


@router.get(
    "/{course_id}/credentials.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def course_credentials_csv(
    course_id: uuid.UUID,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    status: CredentialState | None = None,
) -> Response:
    """Course-level issuance records as CSV for course staff (spec §2.2). No email addresses."""
    from opencredential.governance import records

    course = _course(db, actor, course_id)  # course staff or an administrator over it; else 404
    body, n = records.to_csv_counted(
        records.iter_records(db, actor, course_staff_of=course.id, status=status),
        records.RECORD_COLUMNS,
    )
    audit.record(
        db,
        action="course.report_export",
        resource_type="course",
        resource_id=course_id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=rid,
        data={"counts": {"rows": n}},
    )
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="course-credentials.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{course_id}/progress")
def course_progress(course_id: uuid.UUID, db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    course = _course(db, actor, course_id)
    return progress.course_progress(db, course)


@router.put("/{course_id}/badge-teams", response_model=CourseOut)
def set_badge_teams(
    course_id: uuid.UUID, body: BadgeTeamsIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> CourseOut:
    """Badge teams: each badge in this course is edited and awarded only by its own team."""
    from opencredential.authoring import team

    course = team.set_course_badge_teams(
        db, actor, _course(db, actor, course_id), body.enabled, request_id=rid
    )
    roles = sorted(actor.course_roles(course.id)) or ["admin"]
    return CourseOut(
        id=course.id,
        title=course.title,
        course_code=course.course_code,
        status=course.status,
        roles=roles,
        staff=True,  # only this course's staff, or an administrator over it, gets this far
        badge_teams=course.badge_teams,
    )
