# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 Issuer and IssuerKey (public metadata only; private keys live in schema ``keys``)."""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint, text

from opencredential.db.base import Base, TenantMixin, choice, tenant_args, tenant_fk
from opencredential.db.models._types import (
    Boolean,
    DateTime,
    Mapped,
    Text,
    Uuid,
    datetime,
    mapped_column,
    uuid,
)

ISSUER_LEVELS = ("university", "faculty", "department", "programme")


class Issuer(TenantMixin, Base):
    __tablename__ = "issuers"
    __table_args__ = tenant_args(
        "issuers",
        tenant_fk("org_unit_id", "org_units"),
        tenant_fk("approved_by", "users"),
        UniqueConstraint("institution_id", "slug"),
    )

    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    did: Mapped[str] = mapped_column(Text, unique=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        choice("draft", "active", "suspended", name="status"), default="draft"
    )
    #: Spec §10.2: university-, faculty- or department-level issuer.
    level: Mapped[str] = mapped_column(choice(*ISSUER_LEVELS, name="level"), default="university")
    #: The explicit delegation of authority recorded when an administrator authorised this
    #: issuer (for example "Senate resolution 2026/14"). Creating an issuer never implies it.
    authority_basis: Mapped[str | None] = mapped_column(Text)


class IssuerKey(TenantMixin, Base):
    __tablename__ = "issuer_keys"
    __table_args__ = tenant_args(
        "issuer_keys",
        tenant_fk("issuer_id", "issuers"),
        Index(
            "uq_issuer_keys_one_active",
            "issuer_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )

    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    verification_method_id: Mapped[str] = mapped_column(Text, unique=True)
    public_key_multibase: Mapped[str] = mapped_column(Text)
    algorithm: Mapped[str] = mapped_column(choice("Ed25519", name="algorithm"), default="Ed25519")
    state: Mapped[str] = mapped_column(
        choice("pending", "active", "retired", "revoked", name="state"), default="pending"
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    #: When the signer erased the private half (public key stays for verification).
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Development key: the api and signer refuse to start in production while one is active.
    is_dev: Mapped[bool] = mapped_column(Boolean, default=False)


class IssuerDelegation(TenantMixin, Base):
    __tablename__ = "issuer_delegations"
    __table_args__ = tenant_args(
        "issuer_delegations",
        tenant_fk("issuer_id", "issuers"),
        tenant_fk("granted_by", "users"),
    )

    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    scope_type: Mapped[str] = mapped_column(choice("org_unit", "course", name="scope_type"))
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
