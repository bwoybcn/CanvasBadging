# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 EligibilityEvaluation, Credential, CredentialEvidence, CredentialStatus, ShareGrant.

The award decision is the bridge: every credential references exactly one decision, and every
decision references an evaluation or carries a manual justification (§12.4).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, UniqueConstraint, text

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


class EligibilityEvaluation(TenantMixin, Base):
    __tablename__ = "eligibility_evaluations"
    __table_args__ = tenant_args(
        "eligibility_evaluations",
        tenant_fk("version_id", "achievement_versions"),
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        Index("ix_eligibility_version_user", "version_id", "user_id", "evaluated_at"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(choice("met", "not_met", "unknown", name="outcome"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    inputs_hash: Mapped[str] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(
        choice("sync", "manual", "reeval", "dev_seed", name="triggered_by")
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AwardDecision(TenantMixin, Base):
    __tablename__ = "award_decisions"
    __table_args__ = tenant_args(
        "award_decisions",
        tenant_fk("version_id", "achievement_versions"),
        tenant_fk("user_id", "users"),
        tenant_fk("issuer_id", "issuers"),
        tenant_fk("evaluation_id", "eligibility_evaluations"),
        tenant_fk("decided_by", "users"),
        CheckConstraint("evaluation_id IS NOT NULL OR justification IS NOT NULL", name="has_basis"),
        # One live decision per learner, version and issuance sequence (spec §6.6). A rejected
        # decision does not block a later explicit manual award.
        Index(
            "uq_award_decisions_live",
            "version_id",
            "user_id",
            "issuance_seq",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(choice("automatic", "confirmed", "manual", name="kind"))
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    justification: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        choice("awaiting_confirmation", "ready", "issued", "rejected", "failed", name="status")
    )
    issuance_seq: Mapped[int] = mapped_column(Integer, default=1)
    #: Evidence references for manual awards (spec §11.4); copied to credential_evidence on issue.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)


class StatusList(TenantMixin, Base):
    __tablename__ = "status_lists"
    __table_args__ = tenant_args(
        "status_lists",
        tenant_fk("issuer_id", "issuers"),
        tenant_fk("published_key_id", "issuer_keys"),
    )

    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(choice("revocation", name="purpose"), default="revocation")
    url_path: Mapped[str] = mapped_column(Text, unique=True)
    size: Mapped[int] = mapped_column(Integer, default=131072)
    next_publish_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_credential: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: ``validUntil`` of the published list credential; serving stops (503) after it.
    published_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Credential(TenantMixin, Base):
    """Issued credential. ``signed_json`` is immutable once ``status = 'issued'`` (trigger)."""

    __tablename__ = "credentials"
    __table_args__ = tenant_args(
        "credentials",
        tenant_fk("award_decision_id", "award_decisions"),
        tenant_fk("issuer_id", "issuers"),
        tenant_fk("issuer_key_id", "issuer_keys"),
        tenant_fk("version_id", "achievement_versions"),
        tenant_fk("user_id", "users"),
        tenant_fk("status_list_id", "status_lists"),
        UniqueConstraint("status_list_id", "status_list_index"),
        Index(
            "uq_credentials_live_per_learner",
            "version_id",
            "user_id",
            unique=True,
            postgresql_where=text("status <> 'failed' AND superseded_by_id IS NULL"),
        ),
    )

    award_decision_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    issuer_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    credential_uri: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(
        choice("pending_signature", "issued", "failed", name="status"),
        default="pending_signature",
    )
    signed_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_salt: Mapped[str] = mapped_column(Text)
    recipient_hash: Mapped[str] = mapped_column(Text)
    status_list_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status_list_index: Mapped[int | None] = mapped_column(Integer)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: Signing attempts and the last failure (reconciliation, spec §17.2). Not PII.
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class StatusListBit(TenantMixin, Base):
    __tablename__ = "status_list_bits"
    __table_args__ = tenant_args(
        "status_list_bits",
        tenant_fk("status_list_id", "status_lists"),
        tenant_fk("credential_id", "credentials"),
        UniqueConstraint("status_list_id", "index"),
    )

    status_list_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    index: Mapped[int] = mapped_column(Integer)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class CredentialEvidence(TenantMixin, Base):
    __tablename__ = "credential_evidence"
    __table_args__ = tenant_args(
        "credential_evidence", tenant_fk("credential_id", "credentials", ondelete="CASCADE")
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(
        choice(
            "completion_record",
            "assessment_result",
            "evaluation_statement",
            "artefact",
            "lecturer_confirmation",
            name="kind",
        )
    )
    narrative: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    include_in_credential: Mapped[bool] = mapped_column(Boolean, default=False)
    public: Mapped[bool] = mapped_column(Boolean, default=False)


class CredentialStatus(TenantMixin, Base):
    __tablename__ = "credential_status"
    __table_args__ = tenant_args("credential_status", tenant_fk("credential_id", "credentials"))

    credential_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    state: Mapped[str] = mapped_column(
        choice("active", "revoked", "suspended", name="state"), default="active"
    )
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_text: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CredentialStatusEvent(TenantMixin, Base):
    __tablename__ = "credential_status_events"
    __table_args__ = tenant_args(
        "credential_status_events",
        tenant_fk("credential_id", "credentials"),
        tenant_fk("actor_id", "users"),
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevocationRequest(TenantMixin, Base):
    __tablename__ = "revocation_requests"
    __table_args__ = tenant_args(
        "revocation_requests",
        tenant_fk("credential_id", "credentials"),
        tenant_fk("requested_by", "users"),
        tenant_fk("decided_by", "users"),
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        choice("open", "approved", "rejected", name="status"), default="open"
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ShareGrant(TenantMixin, Base):
    __tablename__ = "share_grants"
    __table_args__ = tenant_args(
        "share_grants",
        tenant_fk("credential_id", "credentials"),
        tenant_fk("created_by", "users"),
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    share_id: Mapped[str] = mapped_column(Text, unique=True)
    show_name: Mapped[bool] = mapped_column(Boolean, default=False)
    show_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
