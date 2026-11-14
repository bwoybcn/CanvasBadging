# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas REST implementation of :class:`~opencredential.integrations.base.LmsAdapter`
(spec §4.3, §4.5).

Method map (spec §4.5 name → method → Canvas endpoint):

==========================  ==========================  ==========================================
``get_course``              :meth:`get_course`          ``GET /api/v1/courses/:id``
``get_course_members``      :meth:`list_members`        LTI NRPS ``context_memberships_url``
``get_modules``             :meth:`list_modules`        ``GET /courses/:id/modules`` + ``/items``
``get_module_progress``     :meth:`list_module_progress` ``GET /courses/:id/modules?student_id=``
``get_assignments``         :meth:`list_assignments`    ``GET /courses/:id/assignments``
``get_submission``          :meth:`list_submissions`    ``GET /courses/:id/students/submissions``
``get_grade``               :meth:`get_grade`           same, released (``posted_at``) only
(sub-account linking)       :meth:`list_accounts`       ``GET /accounts`` + ``/:id/sub_accounts``
==========================  ==========================  ==========================================

Every list is fully paginated or the call raises; nothing returns a silently partial result.
Errors follow the base contract: transient (retry), permission/not-found (data unavailable).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from opencredential.db.models import CanvasIntegration
from opencredential.integrations.base import (
    AccountRecord,
    AssignmentRecord,
    LmsNotFound,
    ModuleProgressRecord,
    ModuleRecord,
    SubmissionRecord,
)
from opencredential.integrations.canvas.http import CanvasHttp, TokenProvider
from opencredential.settings import Settings

STUDENT_BATCH = 40
ASSIGNMENT_FILTER_MAX = 50
PROGRESS_STATES = {"locked", "unlocked", "started", "completed"}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(frozen=True)
class CourseRecord:
    course_ref: str
    name: str
    course_code: str | None
    workflow_state: str
    account_id: str | None = None


@dataclass(frozen=True)
class GradeRecord:
    """A released grade, or an explicit reason why there is none."""

    assignment_id: str
    lms_user_id: str
    #: ``released`` | ``unreleased`` | ``excused`` | ``ungraded`` | ``stale``
    status: str
    score: float | None
    points_possible: float | None


class CanvasAdapter:
    name = "canvas"

    def __init__(self, settings: Settings, base_url: str, tokens: TokenProvider, **http_kw: Any):
        self.http = CanvasHttp(settings, base_url, tokens, **http_kw)

    # ---- course ------------------------------------------------------------------------------

    def get_course(self, course_ref: str) -> CourseRecord:
        data = self.http.get_json(f"/api/v1/courses/{_id(course_ref)}")
        return CourseRecord(
            course_ref=str(data["id"]),
            name=str(data.get("name") or ""),
            course_code=data.get("course_code"),
            workflow_state=str(data.get("workflow_state") or "unknown"),
            account_id=str(data["account_id"]) if data.get("account_id") else None,
        )

    def course_account(self, course_ref: str) -> str | None:
        return self.get_course(course_ref).account_id

    # ---- accounts ----------------------------------------------------------------------------

    def list_accounts(self) -> Sequence[AccountRecord]:
        """Every account the connected Canvas user administers, and all sub-accounts below."""
        seen: dict[str, AccountRecord] = {}

        def add(a: dict[str, Any]) -> None:
            parent = a.get("parent_account_id")
            seen[str(a["id"])] = AccountRecord(
                account_id=str(a["id"]),
                name=str(a.get("name") or f"Account {a['id']}"),
                parent_id=str(parent) if parent else None,
            )

        tops = list(self.http.paginate("/api/v1/accounts"))
        for a in tops:
            add(a)
        for a in tops:
            for sub in self.http.paginate(
                f"/api/v1/accounts/{_id(str(a['id']))}/sub_accounts", {"recursive": "true"}
            ):
                add(sub)
        return list(seen.values())

    # ---- modules -----------------------------------------------------------------------------

    def list_modules(self, course_ref: str) -> Sequence[ModuleRecord]:
        cid = _id(course_ref)
        out = []
        for m in self.http.paginate(f"/api/v1/courses/{cid}/modules"):
            items = list(self.http.paginate(f"/api/v1/courses/{cid}/modules/{m['id']}/items"))
            has_req = any(i.get("completion_requirement") for i in items)
            published = m.get("published", True)
            out.append(
                ModuleRecord(
                    module_id=str(m["id"]),
                    name=str(m.get("name") or ""),
                    workflow_state="active" if published else "unpublished",
                    has_requirements=has_req,
                    requirement_type=m.get("requirement_type") if has_req else None,
                )
            )
        return out

    def list_module_progress(
        self, course_ref: str, lms_user_id: str
    ) -> Sequence[ModuleProgressRecord]:
        cid = _id(course_ref)
        out = []
        for m in self.http.paginate(
            f"/api/v1/courses/{cid}/modules", {"student_id": _id(lms_user_id)}
        ):
            state = m.get("state")
            if state not in PROGRESS_STATES:
                # No progression row yet (or a student Canvas does not evaluate): not "failed",
                # just not started. Locked/unlocked both mean "not completed".
                state = "unlocked" if state is None else "unknown"
            out.append(
                ModuleProgressRecord(
                    module_id=str(m["id"]),
                    state=str(state),
                    completed_at=_dt(m.get("completed_at")),
                )
            )
        return out

    # ---- assignments and submissions ---------------------------------------------------------

    def list_assignments(self, course_ref: str) -> Sequence[AssignmentRecord]:
        cid = _id(course_ref)
        return [
            AssignmentRecord(
                assignment_id=str(a["id"]),
                name=str(a.get("name") or ""),
                points_possible=(
                    float(a["points_possible"]) if a.get("points_possible") is not None else None
                ),
                published=bool(a.get("published", True)),
            )
            for a in self.http.paginate(f"/api/v1/courses/{cid}/assignments")
        ]

    def list_submissions(
        self, course_ref: str, assignment_ids: Iterable[str], lms_user_ids: Iterable[str]
    ) -> Sequence[SubmissionRecord]:
        cid = _id(course_ref)
        wanted_assignments = {str(a) for a in assignment_ids}
        students = [_id(u) for u in lms_user_ids]
        out: list[SubmissionRecord] = []
        for start in range(0, len(students), STUDENT_BATCH):
            batch = students[start : start + STUDENT_BATCH]
            params: list[tuple[str, Any]] = [("student_ids[]", s) for s in batch]
            if 0 < len(wanted_assignments) <= ASSIGNMENT_FILTER_MAX:
                params += [("assignment_ids[]", a) for a in sorted(wanted_assignments)]
            for s in self.http.paginate(f"/api/v1/courses/{cid}/students/submissions", params):
                aid = str(s["assignment_id"])
                if wanted_assignments and aid not in wanted_assignments:
                    continue
                out.append(_submission(s))
        return out

    def get_submission(
        self, course_ref: str, assignment_id: str, lms_user_id: str
    ) -> SubmissionRecord:
        subs = self.list_submissions(course_ref, [assignment_id], [lms_user_id])
        for s in subs:
            if s.assignment_id == str(assignment_id) and s.lms_user_id == _id(lms_user_id):
                return s
        raise LmsNotFound(f"no submission for assignment {assignment_id}")

    def get_grade(
        self,
        course_ref: str,
        assignment_id: str,
        lms_user_id: str,
        points_possible: float | None = None,
    ) -> GradeRecord:
        """The learner's grade as the learner can see it (ADR-0010 "released")."""
        s = self.get_submission(course_ref, assignment_id, lms_user_id)
        if s.excused:
            status, score = "excused", None
        elif s.workflow_state != "graded" or s.score is None:
            status, score = "ungraded", None
        elif s.posted_at is None:
            status, score = "unreleased", None  # staff can see it; the learner cannot
        elif not s.grade_matches_current_submission:
            status, score = "stale", None
        else:
            status, score = "released", s.score
        return GradeRecord(str(assignment_id), _id(lms_user_id), status, score, points_possible)

    def close(self) -> None:
        self.http.close()


def _submission(s: dict[str, Any]) -> SubmissionRecord:
    state = str(s.get("workflow_state") or "unsubmitted")
    return SubmissionRecord(
        assignment_id=str(s["assignment_id"]),
        lms_user_id=str(s["user_id"]),
        workflow_state=state,
        submitted_at=_dt(s.get("submitted_at")),
        score=float(s["score"]) if s.get("score") is not None else None,
        # Canvas sends ``excused: null`` for never-graded submissions.
        excused=bool(s.get("excused")),
        posted_at=_dt(s.get("posted_at")),
        grade_matches_current_submission=s.get("grade_matches_current_submission") is not False,
        missing=bool(s.get("missing")),
        late=bool(s.get("late")),
    )


def _id(value: str) -> str:
    """Canvas ids are digits; anything else would let a value rewrite the request path."""
    v = str(value).strip()
    if not v.isdigit():
        raise LmsNotFound(f"not a Canvas id: {v[:20]!r}")
    return v


def build(settings: Settings, integration: CanvasIntegration) -> CanvasAdapter:
    """Factory registered with :mod:`opencredential.integrations.registry`."""
    from opencredential.integrations.canvas.oauth import IntegrationTokens

    tokens = IntegrationTokens(settings, integration.institution_id, integration.id)
    return CanvasAdapter(settings, integration.base_url, TokenProvider(tokens.get, tokens.refresh))
