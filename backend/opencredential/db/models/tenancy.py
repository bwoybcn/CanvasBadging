# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 Institution, CanvasIntegration and LTI registration state."""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

from opencredential.db.base import Base, TenantMixin, choice, tenant_args, tenant_fk
from opencredential.db.models._types import (
    ARRAY,
    JSONB,
    Any,
    Boolean,
    DateTime,
    LargeBinary,
    Mapped,
    Text,
    Uuid,
    datetime,
    mapped_column,
    uuid,
)

DEFAULT_POLICY: dict[str, Any] = {
    "definitions_require_approval": True,
    # Whether faculties, departments and services may set review less strictly than the
    # institution (migration 0009). The institution's own mode is ``definition_review``, which
    # falls back to ``definitions_require_approval`` when unset.
    "areas_may_relax_review": False,
    "self_approval_allowed": False,
    "approver_roles": ["dept_admin", "inst_admin"],
    "manual_awards_require_second_approval": False,
    "revokers": ["inst_admin", "dept_admin"],
    "score_rules_default_policy": "lecturer_confirmed",
    "score_rules_force_confirmation": False,
    "course_activation_required": True,
    "max_snapshot_age_minutes": 120,
    "include_recipient_name_in_credential": False,
    "dept_admins_may_delegate": True,
}

DEFAULT_RETENTION: dict[str, Any] = {
    "lti_launch_state_minutes": 10,
    "snapshot_days_after_course_end": 365,
    "audit_event_years": 7,
    "failed_job_days": 90,
    "evaluation_days": 730,
}


class Institution(Base):
    """The tenant. Not itself a TenantMixin table: its ``id`` *is* the tenant id."""

    __tablename__ = "institutions"

    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    #: Unique across institutions: the did:web issuers of one institution live under this host,
    #: so two institutions must never share it (review finding S3).
    verification_host: Mapped[str | None] = mapped_column(Text, unique=True)
    linkedin_org_id: Mapped[str | None] = mapped_column(Text)
    linkedin_org_name: Mapped[str | None] = mapped_column(Text)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: dict(DEFAULT_POLICY))
    retention: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_RETENTION)
    )
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        choice("active", "suspended", name="status"), default="active"
    )


class CanvasIntegration(TenantMixin, Base):
    __tablename__ = "canvas_integrations"
    __table_args__ = tenant_args(
        "canvas_integrations", UniqueConstraint("lti_issuer", "lti_client_id")
    )

    name: Mapped[str] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text)
    lti_issuer: Mapped[str] = mapped_column(Text)
    lti_client_id: Mapped[str] = mapped_column(Text)
    lti_jwks_url: Mapped[str | None] = mapped_column(Text)
    lti_auth_url: Mapped[str | None] = mapped_column(Text)
    lti_token_url: Mapped[str | None] = mapped_column(Text)
    api_client_id: Mapped[str | None] = mapped_column(Text)
    api_client_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    privacy_level: Mapped[str] = mapped_column(
        choice("public", "name_only", "email_only", "anonymous", name="privacy_level"),
        default="public",
    )
    live_events_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    live_events_jwks_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        choice("pending", "active", "disabled", name="status"), default="pending"
    )


class LtiDeployment(TenantMixin, Base):
    __tablename__ = "lti_deployments"
    __table_args__ = tenant_args(
        "lti_deployments",
        tenant_fk("canvas_integration_id", "canvas_integrations"),
        UniqueConstraint("canvas_integration_id", "deployment_id"),
    )

    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deployment_id: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(choice("account", "course", name="scope"))
    canvas_account_id: Mapped[str | None] = mapped_column(Text)


class CanvasToken(TenantMixin, Base):
    """Envelope-encrypted OAuth tokens. Never serialised by the API."""

    __tablename__ = "canvas_tokens"
    __table_args__ = tenant_args(
        "canvas_tokens", tenant_fk("canvas_integration_id", "canvas_integrations")
    )

    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(choice("integration_account", "user", name="purpose"))
    canvas_user_id: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class LtiLaunchState(Base):
    """OIDC state/nonce rows, purged after 10 minutes. Pre-tenant (resolved at launch).

    Browser binding (spec §4.2, third-party cookies): at login we give the browser a random
    ``browser secret`` through a cookie *and*, when Canvas offers it, through platform storage
    (``lti_storage_target``). Only its SHA-256 is stored. A launch whose cookie is missing is
    parked under a one-time ``launch_ticket`` until the page proves it holds the secret.
    """

    __tablename__ = "lti_launch_state"

    state: Mapped[str] = mapped_column(Text, unique=True)
    nonce: Mapped[str] = mapped_column(Text)
    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_id: Mapped[str | None] = mapped_column(Text)
    browser_secret_hash: Mapped[str | None] = mapped_column(Text)
    storage_target: Mapped[str | None] = mapped_column(Text)
    launch_ticket_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    launch_claims: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LtiNonceUsed(Base):
    __tablename__ = "lti_nonces_used"
    __table_args__ = (UniqueConstraint("nonce", "iss"),)

    nonce: Mapped[str] = mapped_column(Text)
    iss: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
