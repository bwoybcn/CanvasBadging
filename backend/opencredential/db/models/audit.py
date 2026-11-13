# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 AuditEvent (append-only: trigger + grants) and BackgroundJob (read-only view)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Integer, Table, Text

from opencredential.db.base import Base, choice
from opencredential.db.models._types import (
    JSONB,
    Any,
    DateTime,
    Mapped,
    Uuid,
    datetime,
    mapped_column,
    uuid,
)


class AuditEvent(Base):
    """``institution_id`` is nullable (system events), so this is RLS'd by its own policy."""

    __tablename__ = "audit_events"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_kind: Mapped[str] = mapped_column(choice("user", "system", "lti", name="actor_kind"))
    action: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


#: Read-only view over the procrastinate job tables (created by migration, not by metadata).
background_jobs = Table(
    "background_jobs",
    Base.metadata,
    Column("id", BigInteger, primary_key=True),
    Column("queue_name", Text),
    Column("task_name", Text),
    Column("status", Text),
    Column("attempts", Integer),
    Column("scheduled_at", DateTime(timezone=True)),
    Column("subject_type", Text),
    Column("subject_id", Text),
    Column("institution_id", Uuid),
    Column("args", JSONB),
    info={"is_view": True},
)
