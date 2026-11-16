# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 User, ExternalIdentity, Membership, Course and org units.

Email is never an identifier (§12.2): it is nullable so erasure can clear it.
"""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint, false, text

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

ROLES = (
    "student",
    "lecturer",
    "course_admin",
    "issuer_manager",
    "reviewer",
    "dept_admin",
    "inst_admin",
)


class User(TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = tenant_args("users")

    display_name: Mapped[str | None] = mapped_column(Text)
    given_name: Mapped[str | None] = mapped_column(Text)
    family_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    email_verified_by: Mapped[str | None] = mapped_column(
        choice("lti", "nrps", "rest", "dev_seed", name="email_verified_by")
    )
    status: Mapped[str] = mapped_column(
        choice("active", "deleted", name="status"), default="active"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Canvas's Student View "Test Student": may look around, but is never listed or awarded.
    is_test_user: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class ExternalIdentity(TenantMixin, Base):
    """Canvas identifiers, scoped to the Canvas platform they came from (§12.2)."""

    __tablename__ = "external_identities"
    __table_args__ = tenant_args(
        "external_identities",
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        tenant_fk("canvas_integration_id", "canvas_integrations"),
        UniqueConstraint("canvas_integration_id", "kind", "value"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(
        choice("lti_sub", "canvas_user_id", "sis_user_id", "lti11_user_id", name="kind")
    )
    value: Mapped[str] = mapped_column(Text)


class ErasedIdentity(TenantMixin, Base):
    """A marker left when a person's data is erased, so Canvas cannot bring them back.

    Erasure deletes the person's :class:`ExternalIdentity` rows. Without something to recognise
    them by, the next class-list refresh or launch would create them again, name and email
    included. Each marker holds a keyed one-way fingerprint of one Canvas identifier
    (``secretbox.keyed_digest``), never the identifier itself.
    """

    __tablename__ = "erased_identities"
    __table_args__ = tenant_args(
        "erased_identities",
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        tenant_fk("canvas_integration_id", "canvas_integrations", ondelete="CASCADE"),
        UniqueConstraint("canvas_integration_id", "kind", "value_digest"),
    )

    #: The erased account's remaining row (no personal data), which issued badges still point at.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    value_digest: Mapped[str] = mapped_column(Text)


class OrgUnit(TenantMixin, Base):
    __tablename__ = "org_units"
    __table_args__ = tenant_args("org_units", tenant_fk("parent_id", "org_units"))

    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        choice("faculty", "department", "programme", "service", "other", name="kind")
    )
    #: Spec §10.3 "which departments can issue credentials". Inherited: a unit can issue only if
    #: it and every ancestor may.
    may_issue: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(
        choice("active", "archived", name="status"), default="active"
    )
    #: Colleague-review overrides for this unit and the units below it (migration 0009). Keys
    #: from ``authz.AREA_REVIEW_KEYS``; a missing key inherits from the unit above, then the
    #: institution policy.
    review_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Course(TenantMixin, Base):
    __tablename__ = "courses"
    __table_args__ = tenant_args(
        "courses",
        tenant_fk("canvas_integration_id", "canvas_integrations"),
        tenant_fk("org_unit_id", "org_units"),
        tenant_fk("activated_by", "users"),
        UniqueConstraint("canvas_integration_id", "canvas_course_id"),
    )

    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canvas_course_id: Mapped[str] = mapped_column(Text)
    lti_context_id: Mapped[str | None] = mapped_column(Text)
    #: NRPS ``context_memberships_url`` from the latest launch (roster sync, ADR-0009).
    lti_nrps_url: Mapped[str | None] = mapped_column(Text)
    #: Resource link of the Course Navigation placement; NRPS ``rlid`` returns per-member
    #: custom fields (the Canvas user id) for it.
    lti_resource_link_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    course_code: Mapped[str | None] = mapped_column(Text)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: Badge teams (migration 0010): in a shared course, such as a recognition course for a
    #: library or a faculty's CPD, only each badge's owner and named team can edit or award it.
    badge_teams: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The Canvas (sub-)account the course sits in, from the launch or the Canvas API. Used to
    #: place the course in the org unit linked to that sub-account (see ``CanvasAccount``).
    canvas_account_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        choice("inactive", "active", "archived", name="status"), default="inactive"
    )
    #: When the course ended in Canvas (its end date, or when we first saw it concluded).
    #: Cleared if Canvas later says it is running again. Retention counts from here.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When Canvas stopped being read for the course, some weeks after it ended
    #: (``sync_days_after_course_end``), and ``status`` became ``archived``.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(TenantMixin, Base):
    """A role held by a user within a scope (institution, org unit, issuer or course).

    ``scope_id`` is polymorphic (no FK); the authorisation module validates it.
    """

    __tablename__ = "memberships"
    __table_args__ = tenant_args(
        "memberships",
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        tenant_fk("granted_by", "users"),
        Index(
            "uq_memberships_active",
            "user_id",
            "scope_type",
            "scope_id",
            "role",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    scope_type: Mapped[str] = mapped_column(
        choice("institution", "org_unit", "issuer", "course", name="scope_type")
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(choice(*ROLES, name="role"))
    source: Mapped[str] = mapped_column(choice("lti", "nrps", "grant", "dev_seed", name="source"))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CanvasAccount(TenantMixin, Base):
    """A Canvas account or sub-account, read from Canvas by an administrator.

    Linking one to an org unit (``org_unit_id``) makes courses in it, or in sub-accounts below
    it that are not linked themselves, join that unit when they are first launched. Sub-accounts
    nobody links are ignored, so terms, sandboxes and other housekeeping sub-accounts never
    become areas.
    """

    __tablename__ = "canvas_accounts"
    __table_args__ = tenant_args(
        "canvas_accounts",
        tenant_fk("canvas_integration_id", "canvas_integrations", ondelete="CASCADE"),
        tenant_fk("org_unit_id", "org_units"),
        UniqueConstraint("canvas_integration_id", "account_id"),
    )

    canvas_integration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    account_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    parent_account_id: Mapped[str | None] = mapped_column(Text)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
