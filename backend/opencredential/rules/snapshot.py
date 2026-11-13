# SPDX-License-Identifier: AGPL-3.0-or-later
"""``LearnerSnapshot``: everything the engine may look at, already loaded.

The eligibility service builds a snapshot from the ``lms_*`` tables (ADR-0010) and manual
approvals; the engine never reads anything else. Absence is meaningful: a module missing from
``modules`` means Canvas no longer reports it, while a learner missing from ``module_progress``
for a known module means "no progress recorded".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: Data kinds a sync can fail to fetch for a learner (ADR-0010 "unknown, not failed").
MODULES = "modules"
SUBMISSIONS = "submissions"


@dataclass(frozen=True)
class ModuleInfo:
    module_id: str
    name: str
    workflow_state: str  # active | unpublished | deleted
    has_requirements: bool
    fetched_at: datetime


@dataclass(frozen=True)
class ModuleProgress:
    module_id: str
    state: str  # locked | unlocked | started | completed
    completed_at: datetime | None
    fetched_at: datetime


@dataclass(frozen=True)
class AssignmentInfo:
    assignment_id: str
    name: str
    points_possible: float | None
    published: bool
    deleted: bool
    fetched_at: datetime


@dataclass(frozen=True)
class Submission:
    assignment_id: str
    workflow_state: str  # unsubmitted | submitted | pending_review | graded
    submitted_at: datetime | None
    score: float | None
    excused: bool
    posted_at: datetime | None
    grade_matches_current_submission: bool
    missing: bool
    fetched_at: datetime


@dataclass(frozen=True)
class Approval:
    """A lecturer's decision on a manual-approval rule for this learner."""

    rule_id: str
    decision: str  # approve | decline
    decided_at: datetime
    decided_by: str


@dataclass(frozen=True)
class LearnerSnapshot:
    learner_ref: str
    now: datetime
    max_age: timedelta
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    module_progress: dict[str, ModuleProgress] = field(default_factory=dict)
    assignments: dict[str, AssignmentInfo] = field(default_factory=dict)
    submissions: dict[str, Submission] = field(default_factory=dict)
    approvals: dict[str, Approval] = field(default_factory=dict)
    #: Kinds of data the last sync could not fetch for this learner.
    unavailable: frozenset[str] = frozenset()
    #: When the course was last synced successfully (``None``: never).
    synced_at: datetime | None = None
    #: Rules whose Canvas source changed or disappeared since publication.
    rule_source_status: dict[str, str] = field(default_factory=dict)

    def is_stale(self, fetched_at: datetime | None) -> bool:
        return fetched_at is None or self.now - fetched_at > self.max_age
