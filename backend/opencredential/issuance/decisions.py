# SPDX-License-Identifier: AGPL-3.0-or-later
"""Award decisions: the only thing that can lead to a credential (ADR-0012, spec §6.6).

The idempotency key is SHA-256 of (institution | learner | achievement version | award kind |
issuance sequence). Processing the same eligibility outcome twice therefore finds the same
decision instead of creating a second one. Explicit reissue is a separate operation that bumps
``issuance_seq`` (spec §6.6 "explicit reissuance must be a separate authorised operation").
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import AchievementDefinition, AchievementVersion, AwardDecision
from opencredential.ids import uuid7

KINDS = ("automatic", "confirmed", "manual")


class DecisionError(RuntimeError):
    pass


def idempotency_key(
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    kind: str,
    issuance_seq: int = 1,
) -> str:
    material = f"{institution_id}|{user_id}|{version_id}|{kind}|{issuance_seq}"
    return hashlib.sha256(material.encode()).hexdigest()


def decide(
    db: Session,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    kind: str,
    evaluation_id: uuid.UUID | None = None,
    justification: str | None = None,
    decided_by: uuid.UUID | None = None,
    status: str = "ready",
    issuance_seq: int = 1,
    now: datetime | None = None,
) -> tuple[AwardDecision, bool]:
    """Create the decision, or return the existing one for the same key. ``(decision, created)``.

    Uses ``INSERT … ON CONFLICT DO NOTHING`` so two workers racing on the same completion event
    cannot both create a decision.
    """
    if kind not in KINDS:
        raise DecisionError(f"kind must be one of {KINDS}")
    if evaluation_id is None and not justification:
        raise DecisionError("a decision needs an eligibility evaluation or a justification")
    version = db.get(AchievementVersion, version_id)
    if version is None or not version.frozen:
        raise DecisionError("awards can only be made against a published achievement version")
    definition = db.get(AchievementDefinition, version.definition_id)
    assert definition is not None
    key = idempotency_key(institution_id, user_id, version_id, kind, issuance_seq)
    new_id = uuid7()
    stmt = (
        insert(AwardDecision)
        .values(
            id=new_id,
            institution_id=institution_id,
            version_id=version_id,
            user_id=user_id,
            issuer_id=definition.issuer_id,
            kind=kind,
            evaluation_id=evaluation_id,
            justification=justification,
            decided_by=decided_by,
            decided_at=now or datetime.now(UTC),
            status=status,
            issuance_seq=issuance_seq,
            idempotency_key=key,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(AwardDecision.id)
    )
    inserted = db.execute(stmt).scalar()
    decision = db.scalar(select(AwardDecision).where(AwardDecision.idempotency_key == key))
    assert decision is not None
    if inserted:
        audit.record(
            db,
            action="award.decide",
            resource_type="award_decision",
            resource_id=decision.id,
            institution_id=institution_id,
            actor_user_id=decided_by,
            actor_kind="user" if decided_by else "system",
            data={"kind": kind, "version_id": str(version_id), "issuance_seq": issuance_seq},
        )
    return decision, bool(inserted)
