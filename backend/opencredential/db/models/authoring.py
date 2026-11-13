# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.1 AchievementDefinition, AchievementVersion, BadgeAsset, AwardRuleSet, AwardRule."""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint

from opencredential.db.base import Base, TenantMixin, choice, tenant_args, tenant_fk
from opencredential.db.models._types import (
    JSONB,
    Any,
    Boolean,
    DateTime,
    Integer,
    Mapped,
    Text,
    Uuid,
    datetime,
    mapped_column,
    uuid,
)

DEFINITION_STATES = ("draft", "in_review", "approved", "published", "archived")
AWARD_POLICIES = ("automatic", "lecturer_confirmed", "manual")
# Open Badges 3.0 AchievementType vocabulary (subset used by the authoring UI; ext: allowed).
ACHIEVEMENT_TYPES = (
    "Achievement",
    "Assessment",
    "Award",
    "Badge",
    "Certificate",
    "Competency",
    "CoCurricular",
    "Course",
    "LearningProgram",
    "MicroCredential",
)
RULE_TYPES = (
    "module_completed",
    "modules_completed",
    "assignment_submitted",
    "assignment_score",
    "manual_approval",
    "group",
)


class BadgeAsset(TenantMixin, Base):
    __tablename__ = "badge_assets"
    __table_args__ = tenant_args("badge_assets")

    kind: Mapped[str] = mapped_column(choice("upload", "template", name="kind"))
    media_type: Mapped[str] = mapped_column(choice("image/svg+xml", "image/png", name="media_type"))
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    alt_text: Mapped[str] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    sanitised: Mapped[bool] = mapped_column(Boolean, default=False)
    png_rendition_key: Mapped[str | None] = mapped_column(Text)


class BadgeTemplate(TenantMixin, Base):
    __tablename__ = "badge_templates"
    __table_args__ = tenant_args("badge_templates", tenant_fk("org_unit_id", "org_units"))

    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AchievementDefinition(TenantMixin, Base):
    __tablename__ = "achievement_definitions"
    __table_args__ = tenant_args(
        "achievement_definitions",
        tenant_fk("issuer_id", "issuers"),
        tenant_fk("course_id", "courses"),
        tenant_fk("template_id", "badge_templates"),
        tenant_fk("owner_user_id", "users"),
        tenant_fk("current_version_id", "achievement_versions", use_alter=True),
    )

    issuer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    course_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(choice(*DEFINITION_STATES, name="state"), default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    award_policy: Mapped[str] = mapped_column(
        choice(*AWARD_POLICIES, name="award_policy"), default="automatic"
    )


class AchievementVersion(TenantMixin, Base):
    """Immutable once ``frozen`` (enforced by trigger ``trg_achievement_versions_frozen``)."""

    __tablename__ = "achievement_versions"
    __table_args__ = tenant_args(
        "achievement_versions",
        tenant_fk("definition_id", "achievement_definitions"),
        tenant_fk("asset_id", "badge_assets"),
        tenant_fk("published_by", "users"),
        UniqueConstraint("definition_id", "version_no"),
    )

    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    short_description: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    learning_outcomes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    criteria_narrative: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    achievement_type: Mapped[str] = mapped_column(
        choice(*ACHIEVEMENT_TYPES, name="achievement_type"), default="Badge"
    )
    demonstration_kind: Mapped[str] = mapped_column(
        choice(
            "attending",
            "participating",
            "completing",
            "demonstrating",
            "assessed",
            name="demonstration_kind",
        )
    )
    evidence_description: Mapped[str | None] = mapped_column(Text)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    skills: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    credit_claim_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Awarding policy chosen for this version. ``NULL`` while drafting means "use the
    #: institution default"; publication resolves and snapshots it (ADR-0017).
    award_policy: Mapped[str | None] = mapped_column(choice(*AWARD_POLICIES, name="award_policy"))
    content_hash: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)


class DefinitionReview(TenantMixin, Base):
    __tablename__ = "definition_reviews"
    __table_args__ = tenant_args(
        "definition_reviews",
        tenant_fk("definition_id", "achievement_definitions"),
        tenant_fk("version_id", "achievement_versions"),
        tenant_fk("reviewer_id", "users"),
    )

    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(choice("approve", "reject", "comment", name="decision"))
    checklist: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)


class ManualRuleApproval(TenantMixin, Base):
    """A lecturer's decision on a ``manual_approval`` rule (Rule E) for one learner.

    Append-only history: the latest row per (rule, learner) is the one the engine reads.
    """

    __tablename__ = "manual_rule_approvals"
    __table_args__ = tenant_args(
        "manual_rule_approvals",
        tenant_fk("version_id", "achievement_versions"),
        tenant_fk("rule_id", "award_rules"),
        tenant_fk("user_id", "users", ondelete="CASCADE"),
        tenant_fk("decided_by", "users"),
        Index("ix_manual_rule_approvals_lookup", "version_id", "user_id", "rule_id", "decided_at"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(choice("approve", "decline", name="decision"))
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AwardRuleSet(TenantMixin, Base):
    __tablename__ = "award_rule_sets"
    __table_args__ = tenant_args("award_rule_sets", tenant_fk("version_id", "achievement_versions"))

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    mode: Mapped[str] = mapped_column(choice("ALL", "ANY", name="mode"))
    schema_version: Mapped[str] = mapped_column(Text, default="rules/v1")


class AwardRule(TenantMixin, Base):
    __tablename__ = "award_rules"
    __table_args__ = tenant_args(
        "award_rules",
        tenant_fk("rule_set_id", "award_rule_sets", ondelete="CASCADE"),
        tenant_fk("parent_rule_id", "award_rules"),
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(choice(*RULE_TYPES, name="type"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_status: Mapped[str] = mapped_column(
        choice("ok", "source_missing", "source_changed", name="source_status"), default="ok"
    )
