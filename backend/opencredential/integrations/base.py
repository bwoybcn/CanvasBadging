# SPDX-License-Identifier: AGPL-3.0-or-later
"""LMS abstraction (spec §4.5). Canvas is the first implementation; others come later.

The sync module (:mod:`opencredential.sync`) reads an LMS only through :class:`LmsAdapter` and
writes what it gets into the ``lms_*`` snapshot tables, which are all the rules engine sees.
Records here are LMS-neutral: Canvas types never leave ``integrations.canvas``.

Failure contract (ADR-0010 "unknown, not failed"):

* :class:`LmsTransientError`: rate limiting, timeouts, 5xx. The job retries with backoff.
* :class:`LmsPermissionError`: the integration account cannot read this. Not retried; the
  affected data is marked unavailable so rules stay ``unknown``.
* Any :class:`LmsError` for one learner affects only that learner's data.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class LmsError(Exception):
    code = "LMS_ERROR"


class LmsTransientError(LmsError):
    code = "LMS_TRANSIENT"


class LmsPermissionError(LmsError):
    code = "LMS_PERMISSION"


class LmsNotFound(LmsError):
    code = "LMS_NOT_FOUND"


@dataclass(frozen=True)
class ModuleRecord:
    module_id: str
    name: str
    #: ``active`` (published) or ``unpublished``. Modules that disappear are not returned.
    workflow_state: str
    has_requirements: bool
    requirement_type: str | None = None


@dataclass(frozen=True)
class ModuleProgressRecord:
    module_id: str
    #: ``locked`` | ``unlocked`` | ``started`` | ``completed``
    state: str
    completed_at: datetime | None


@dataclass(frozen=True)
class AssignmentRecord:
    assignment_id: str
    name: str
    points_possible: float | None
    published: bool


@dataclass(frozen=True)
class SubmissionRecord:
    assignment_id: str
    lms_user_id: str
    #: ``unsubmitted`` | ``submitted`` | ``pending_review`` | ``graded``
    workflow_state: str
    submitted_at: datetime | None
    score: float | None
    excused: bool
    #: When the grade was released to the learner (Canvas ``posted_at``); ``None`` = hidden.
    posted_at: datetime | None
    grade_matches_current_submission: bool = True
    missing: bool = False
    late: bool = False


@dataclass(frozen=True)
class AccountRecord:
    """A Canvas account or sub-account. ``parent_id`` is None for a root account."""

    account_id: str
    name: str
    parent_id: str | None


@dataclass(frozen=True)
class CourseStateRecord:
    """Whether a course has ended in the LMS (Canvas: concluded, or its term has ended)."""

    concluded: bool
    #: The end date the LMS holds for the course or its term, when there is one and it has
    #: passed. ``None`` when the LMS gives no date (a course concluded by hand).
    ended_at: datetime | None = None


@runtime_checkable
class CourseLifecycle(Protocol):
    """Optional adapter capability: tell whether a course has ended."""

    def course_state(self, course_ref: str) -> CourseStateRecord: ...


@runtime_checkable
class AccountDirectory(Protocol):
    """Optional adapter capability: read the LMS account tree and where a course sits in it."""

    def list_accounts(self) -> Sequence[AccountRecord]: ...

    def course_account(self, course_ref: str) -> str | None: ...


class LmsAdapter(Protocol):
    """Read-only access to one LMS installation (one ``canvas_integrations`` row)."""

    name: str

    def list_modules(self, course_ref: str) -> Sequence[ModuleRecord]: ...

    def list_module_progress(
        self, course_ref: str, lms_user_id: str
    ) -> Sequence[ModuleProgressRecord]: ...

    def list_assignments(self, course_ref: str) -> Sequence[AssignmentRecord]: ...

    def list_submissions(
        self, course_ref: str, assignment_ids: Iterable[str], lms_user_ids: Iterable[str]
    ) -> Sequence[SubmissionRecord]: ...
