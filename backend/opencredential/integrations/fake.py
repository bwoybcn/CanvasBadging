# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory :class:`LmsAdapter` for tests and the development demo course.

It behaves like the Canvas adapter contract (modules that disappear are not returned, failures
raise the documented exceptions) without any network access. Real-Canvas behaviour is verified
separately against the local Canvas install (``canvas_live`` tests, W3).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from opencredential.integrations.base import (
    AccountRecord,
    AssignmentRecord,
    LmsError,
    LmsNotFound,
    ModuleProgressRecord,
    ModuleRecord,
    SubmissionRecord,
)


@dataclass
class FakeCourse:
    modules: dict[str, ModuleRecord] = field(default_factory=dict)
    assignments: dict[str, AssignmentRecord] = field(default_factory=dict)
    #: (lms_user_id, module_id) -> progress
    progress: dict[tuple[str, str], ModuleProgressRecord] = field(default_factory=dict)
    #: (lms_user_id, assignment_id) -> submission
    submissions: dict[tuple[str, str], SubmissionRecord] = field(default_factory=dict)


class FakeLmsAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.courses: dict[str, FakeCourse] = {}
        #: Exceptions to raise: keys like ("modules",), ("progress", user), ("submissions",)
        self.failures: dict[tuple[str, ...], LmsError] = {}
        self.calls: list[tuple[str, ...]] = []
        #: The account tree (sub-account linking) and which account each course sits in.
        self.accounts: list[AccountRecord] = []
        self.course_accounts: dict[str, str] = {}

    # -- test helpers ---------------------------------------------------------------------
    def course(self, ref: str) -> FakeCourse:
        return self.courses.setdefault(ref, FakeCourse())

    def add_module(self, course: str, module_id: str, name: str, **kw: Any) -> None:
        kw.setdefault("workflow_state", "active")
        kw.setdefault("has_requirements", True)
        self.course(course).modules[module_id] = ModuleRecord(module_id, name, **kw)

    def add_assignment(self, course: str, assignment_id: str, name: str, **kw: Any) -> None:
        kw.setdefault("points_possible", 100.0)
        kw.setdefault("published", True)
        self.course(course).assignments[assignment_id] = AssignmentRecord(assignment_id, name, **kw)

    def complete_module(
        self, course: str, user: str, module_id: str, when: datetime | None = None
    ) -> None:
        self.course(course).progress[(user, module_id)] = ModuleProgressRecord(
            module_id, "completed", when or datetime.now(UTC)
        )

    def set_submission(self, course: str, user: str, assignment_id: str, **kw: Any) -> None:
        current = self.course(course).submissions.get((user, assignment_id))
        if current is None:
            base: dict[str, Any] = {
                "workflow_state": "submitted",
                "submitted_at": datetime.now(UTC) - timedelta(hours=1),
                "score": None,
                "excused": False,
                "posted_at": None,
            }
            base.update(kw)
            self.course(course).submissions[(user, assignment_id)] = SubmissionRecord(
                assignment_id, user, **base
            )
        else:
            self.course(course).submissions[(user, assignment_id)] = replace(current, **kw)

    # -- adapter protocol -----------------------------------------------------------------
    def _fail(self, *key: str) -> None:
        self.calls.append(key)
        if key in self.failures:
            raise self.failures[key]

    def _get(self, ref: str) -> FakeCourse:
        if ref not in self.courses:
            raise LmsNotFound(f"course {ref} not found")
        return self.courses[ref]

    def list_accounts(self) -> Sequence[AccountRecord]:
        self._fail("accounts")
        return list(self.accounts)

    def course_account(self, course_ref: str) -> str | None:
        self._fail("course_account")
        return self.course_accounts.get(course_ref)

    def list_modules(self, course_ref: str) -> Sequence[ModuleRecord]:
        self._fail("modules")
        return list(self._get(course_ref).modules.values())

    def list_module_progress(
        self, course_ref: str, lms_user_id: str
    ) -> Sequence[ModuleProgressRecord]:
        self._fail("progress", lms_user_id)
        c = self._get(course_ref)
        out = []
        for mid in c.modules:
            p = c.progress.get((lms_user_id, mid))
            out.append(p or ModuleProgressRecord(mid, "unlocked", None))
        return out

    def list_assignments(self, course_ref: str) -> Sequence[AssignmentRecord]:
        self._fail("assignments")
        return list(self._get(course_ref).assignments.values())

    def list_submissions(
        self, course_ref: str, assignment_ids: Iterable[str], lms_user_ids: Iterable[str]
    ) -> Sequence[SubmissionRecord]:
        self._fail("submissions")
        c = self._get(course_ref)
        aids, uids = set(assignment_ids), set(lms_user_ids)
        out = []
        for (uid, aid), s in c.submissions.items():
            if uid in uids and aid in aids:
                out.append(s)
        # Canvas returns an "unsubmitted" row for every learner without a submission.
        for uid in uids:
            for aid in aids:
                if (uid, aid) not in c.submissions:
                    out.append(SubmissionRecord(aid, uid, "unsubmitted", None, None, False, None))
        return out


def passport_adapter(data: dict[str, Any], course_ref: str) -> FakeLmsAdapter:
    """The demo course from ``examples/academic-skills-passport`` as a fake LMS.

    Ids match what ``opencredential.seed`` writes (modules ``1000+i``, assignments ``5000+i``,
    learners by seed key), so a dev sync refreshes the demo snapshot with the same content.
    """
    now = datetime.now(UTC)
    fake = FakeLmsAdapter()
    module_ids = {m["key"]: str(1000 + i) for i, m in enumerate(data["modules"])}
    assignment_ids = {a["key"]: str(5000 + i) for i, a in enumerate(data["assignments"])}
    for m in data["modules"]:
        fake.add_module(
            course_ref, module_ids[m["key"]], m["name"], requirement_type=m["requirement_type"]
        )
    for a in data["assignments"]:
        fake.add_assignment(
            course_ref,
            assignment_ids[a["key"]],
            a["name"],
            points_possible=float(a["points_possible"]),
        )
    for s in data["students"]:
        for key in s["completed"]:
            fake.complete_module(course_ref, s["key"], module_ids[key], now - timedelta(days=3))
        for akey, sub in s["submissions"].items():
            excused = sub.get("excused", False)
            graded = sub.get("score") is not None or excused
            posted = sub.get("posted", True) and not excused
            fake.set_submission(
                course_ref,
                s["key"],
                assignment_ids[akey],
                workflow_state="graded" if graded else "submitted",
                submitted_at=None if excused else now - timedelta(days=4),
                score=sub.get("score"),
                excused=excused,
                posted_at=now - timedelta(days=1) if posted and graded else None,
            )
    return fake
