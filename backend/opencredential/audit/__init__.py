# SPDX-License-Identifier: AGPL-3.0-or-later
"""Append-only audit trail (spec §10.6). Write in the same transaction as the change."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from opencredential.db.models import AuditEvent


def record(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None,
    institution_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None = None,
    actor_kind: str = "user",
    request_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to ``session``. ``data`` must not contain free-text PII."""
    event = AuditEvent(
        institution_id=institution_id,
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        request_id=request_id,
        at=datetime.now(UTC),
        data=data or {},
    )
    session.add(event)
    return event
