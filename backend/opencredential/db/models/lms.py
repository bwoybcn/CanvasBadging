# SPDX-License-Identifier: AGPL-3.0-or-later
"""LMS snapshot tables written by sync and read by the rules engine (ADR-0010)."""

from __future__ import annotations

from sqlalchemy import Float, UniqueConstraint, text

from opencredential.db.base import Base, TenantMixin, choice, tenant_args, tenant_fk
from opencredential.db.models._types import (
    JSONB,
    Any,
    Boolean,
    DateTime,
    Mapped,
    Text,
    Uuid,
    datetime,
    mapped_column,
    uuid,
)


class LmsModule(TenantMixin, Base):
    __tablename__ = "lms_modules"
    __table_args__ = tenant_args(
        "lms_modules",
        tenant_fk("course_id", "courses"),
        UniqueConstraint("course_id", "canvas_module_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_module_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    requirement_type: Mapped[str | None] = mapped_column(Text)
    has_requirements: Mapped[bool] = mapped_column(Boolean, default=False)
    workflow_state: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LmsModuleProgress(TenantMixin, Base):
    __tablename__ = "lms_module_progress"
    __table_args__ = tenant_args(
        "lms_module_progress",
        tenant_fk("course_id", "courses"),
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        UniqueConstraint("course_id", "user_id", "canvas_module_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_module_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LmsAssignment(TenantMixin, Base):
    __tablename__ = "lms_assignments"
    __table_args__ = tenant_args(
        "lms_assignments",
        tenant_fk("course_id", "courses"),
        UniqueConstraint("course_id", "canvas_assignment_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_assignment_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    points_possible: Mapped[float | None] = mapped_column(Float)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Whether this assignment's submissions are read from Canvas. Only assignments a live
    #: badge rule uses are (data minimisation): for the others no student's submission or mark
    #: is held, and a rule that starts using one waits for the next refresh.
    submissions_synced: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LmsSubmission(TenantMixin, Base):
    __tablename__ = "lms_submissions"
    __table_args__ = tenant_args(
        "lms_submissions",
        tenant_fk("course_id", "courses"),
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        UniqueConstraint("course_id", "user_id", "canvas_assignment_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_assignment_id: Mapped[str] = mapped_column(Text)
    workflow_state: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    excused: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade_matches_current_submission: Mapped[bool] = mapped_column(Boolean, default=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncRun(TenantMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = tenant_args("sync_runs", tenant_fk("course_id", "courses"))

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(
        choice("initial", "scheduled", "on_demand", "hint", "dev_seed", name="kind")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        choice("running", "ok", "partial", "failed", name="status"), default="running"
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
