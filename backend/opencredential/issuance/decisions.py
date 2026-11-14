# SPDX-License-Identifier: AGPL-3.0-or-later
"""Award decisions: the only thing that can lead to a credential (ADR-0012, spec §6.6).

The idempotency key is SHA-256 of (institution | learner | achievement version | award kind |
issuance sequence). Processing the same eligibility outcome twice therefore finds the same
decision instead of creating a second one. Explicit reissue is a separate operation that bumps
``issuance_seq`` (spec §6.6 "explicit reissuance must be a separate authorised operation").

A manual award made after an earlier award was rejected is a new decision, not a replay, so it
passes ``attempt`` (the number of rejected decisions before it) and gets a key of its own.

This module is the only place that builds keys and inserts decisions; eligibility calls it.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    AwardDecision,
    Credential,
    CredentialStatus,
)
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
    attempt: int = 0,
) -> str:
    material = f"{institution_id}|{user_id}|{version_id}|{kind}|{issuance_seq}"
    if attempt:
        # Attempt 0 keeps the original format, so keys of existing decisions do not change.
        material += f"|attempt:{attempt}"
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
    attempt: int = 0,
    evidence: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    record_audit: bool = True,
) -> tuple[AwardDecision, bool]:
    """Create the decision, or return the existing one for the same key. ``(decision, created)``.

    Uses ``INSERT … ON CONFLICT DO NOTHING`` so two workers racing on the same completion event
    cannot both create a decision. If a concurrent decision of another kind won the race for
    the learner's single live slot, that live decision is returned with ``created=False``.
    ``record_audit=False`` lets a caller that writes its own, more specific audit event skip
    the generic ``award.decide`` one.
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
    key = idempotency_key(institution_id, user_id, version_id, kind, issuance_seq, attempt)

    def other_live() -> AwardDecision | None:
        # One live (not rejected) decision per learner, version and issuance sequence
        # (``uq_award_decisions_live``): a second decision of another kind reuses the live one.
        return db.scalar(
            select(AwardDecision).where(
                AwardDecision.version_id == version_id,
                AwardDecision.user_id == user_id,
                AwardDecision.issuance_seq == issuance_seq,
                AwardDecision.status != "rejected",
                AwardDecision.idempotency_key != key,
            )
        )

    live = other_live()
    if live is not None:
        return live, False
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
            evidence=[dict(e) for e in (evidence or [])],
        )
        # No conflict target: covers both the idempotency key and the live-decision index.
        .on_conflict_do_nothing()
        .returning(AwardDecision.id)
    )
    inserted = db.execute(stmt).scalar()
    decision = db.scalar(select(AwardDecision).where(AwardDecision.idempotency_key == key))
    if decision is None:
        live = other_live()
        assert live is not None
        return live, False
    if inserted and record_audit:
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


def reissue(
    db: Session,
    original: AwardDecision,
    *,
    justification: str,
    decided_by: uuid.UUID | None,
    now: datetime | None = None,
) -> AwardDecision:
    """Explicit reissue: a new ``ready`` decision for the same learner, version and basis.

    Used after a revocation that was not the learner's fault (for example ``key_compromise``).
    The original credential must already be revoked, so a learner never holds two live copies.
    The new decision has the next ``issuance_seq``, so it gets its own idempotency key and a
    fresh credential that supersedes the old one; calling this twice for the same original
    returns the same new decision.
    """
    if not justification:
        raise DecisionError("a reissue needs a justification")
    revoked = db.scalar(
        select(CredentialStatus.id)
        .join(Credential, Credential.id == CredentialStatus.credential_id)
        .where(Credential.award_decision_id == original.id, CredentialStatus.state == "revoked")
    )
    if revoked is None:
        raise DecisionError("only a revoked credential can be reissued; revoke it first")
    decision, _ = decide(
        db,
        institution_id=original.institution_id,
        user_id=original.user_id,
        version_id=original.version_id,
        kind=original.kind,
        evaluation_id=original.evaluation_id,
        justification=f"reissue of {original.id}: {justification}",
        decided_by=decided_by,
        issuance_seq=original.issuance_seq + 1,
        now=now,
    )
    return decision
