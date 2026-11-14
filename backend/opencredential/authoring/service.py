# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge definitions, immutable versions and the lifecycle (spec §5, §11, ADR-0017).

Lifecycle of a definition's *working* version::

    DRAFT --submit--> IN_REVIEW --approve--> APPROVED --publish--> PUBLISHED --archive--> ARCHIVED
      ^                   |
      +-----reject--------+

* Edits are only possible in DRAFT; submitting fixes a ``content_hash``, and publication checks
  the approved content is exactly what is being published.
* Publication freezes the version (DB trigger) together with its rules and resolved awarding
  policy, and points ``current_version_id`` at it. Awards always reference that exact version.
* A substantive change to a published badge is a *new version* (``new_version``): the live
  version keeps awarding until the new one is published, and earlier awards keep pointing at the
  version they were made under.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authoring import rules_store
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    BadgeAsset,
    Course,
    DefinitionReview,
    Institution,
    Issuer,
    LmsAssignment,
    LmsModule,
    SyncRun,
)
from opencredential.db.models.authoring import ACHIEVEMENT_TYPES, AWARD_POLICIES
from opencredential.errors import Conflict, Invalid, NotFound
from opencredential.jobs import enqueue
from opencredential.rules.schema import (
    AssignmentScore,
    AssignmentSubmitted,
    ManualApproval,
    ModuleCompleted,
    ModulesCompleted,
    RuleSet,
)

#: Spec §5.2 standard categories. Institutions add local ones in ``institutions.categories``.
STANDARD_CATEGORIES = (
    "Participation",
    "Completion",
    "Competency",
    "Skills demonstration",
    "Professional development",
    "Research development",
    "Digital literacy",
    "Employability",
    "Other",
)
#: Spec §11.1 "how achievement is demonstrated".
DEMONSTRATION_KINDS = {
    "attending": "Attending",
    "participating": "Participating",
    "completing": "Completing",
    "demonstrating": "Demonstrating competence",
    "assessed": "Achieving assessed proficiency",
}
COMPETENCY_CATEGORIES = {"Competency", "Skills demonstration"}
COMPETENCY_TYPES = {"Competency"}
REVIEW_CHECKLIST = (
    "clarity",
    "level",
    "evidence",
    "alignment",
    "accessibility",
    "consistency",
    "terminology",
)
#: Words that can imply academic credit or a formal qualification (spec §11.2, §11.5).
CREDIT_TERMS = re.compile(
    r"\b(degree|diploma|credits?|CATS|ECTS|accredit\w*|qualifications?|bachelor'?s?|"
    r"master'?s|honours|postgraduate certificate|PGCert)\b",
    re.IGNORECASE,
)
CONTENT_FIELDS = (
    "title",
    "short_description",
    "description",
    "learning_outcomes",
    "criteria_narrative",
    "category",
    "achievement_type",
    "demonstration_kind",
    "evidence_description",
    "validity_days",
    "skills",
    "asset_id",
    "award_policy",
)


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    framework: str | None = Field(default=None, max_length=120)
    code: str | None = Field(default=None, max_length=60)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https://")


class DraftFields(BaseModel):
    """Editable fields of a draft version. Everything is optional while drafting; completeness
    is checked when the draft is submitted (see :func:`readiness`)."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=120)
    short_description: str | None = Field(default=None, max_length=280)
    description: str | None = Field(default=None, max_length=4000)
    learning_outcomes: list[str] | None = Field(default=None, max_length=12)
    criteria_narrative: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    achievement_type: str | None = None
    demonstration_kind: str | None = None
    evidence_description: str | None = Field(default=None, max_length=2000)
    validity_days: int | None = Field(default=None, ge=1, le=3650)
    skills: list[Skill] | None = Field(default=None, max_length=20)
    asset_id: uuid.UUID | None = None
    award_policy: str | None = Field(
        default=None, description="automatic | lecturer_confirmed | manual | null (default)"
    )


def _now() -> datetime:
    return datetime.now(UTC)


def categories(db: Session, institution_id: uuid.UUID) -> list[str]:
    inst = db.get(Institution, institution_id)
    local = [c for c in (inst.categories if inst else []) if c not in STANDARD_CATEGORIES]
    return [*STANDARD_CATEGORIES, *local]


# ---- loading ---------------------------------------------------------------------------------


def get_definition(db: Session, definition_id: uuid.UUID) -> AchievementDefinition:
    d = db.get(AchievementDefinition, definition_id)
    if d is None:
        raise NotFound("NOT_FOUND", "No such badge.")
    return d


def working_version(db: Session, definition: AchievementDefinition) -> AchievementVersion:
    v = db.scalar(
        select(AchievementVersion)
        .where(AchievementVersion.definition_id == definition.id)
        .order_by(AchievementVersion.version_no.desc())
        .limit(1)
    )
    assert v is not None
    return v


def live_version(db: Session, definition: AchievementDefinition) -> AchievementVersion | None:
    if definition.current_version_id is None or definition.state == "archived":
        return None
    return db.get(AchievementVersion, definition.current_version_id)


# ---- create / edit -----------------------------------------------------------------------------


def _apply(db: Session, version: AchievementVersion, fields: DraftFields) -> None:
    data = fields.model_dump(exclude_unset=True)
    if "achievement_type" in data and data["achievement_type"] not in (None, *ACHIEVEMENT_TYPES):
        raise Invalid("ACHIEVEMENT_TYPE_INVALID", "Unknown achievement type.")
    if "demonstration_kind" in data and data["demonstration_kind"] not in DEMONSTRATION_KINDS:
        raise Invalid("DEMONSTRATION_KIND_INVALID", "Unknown way of demonstrating achievement.")
    if "award_policy" in data and data["award_policy"] not in (None, *AWARD_POLICIES):
        raise Invalid("AWARD_POLICY_INVALID", "Unknown awarding method.")
    if data.get("asset_id") is not None and db.get(BadgeAsset, data["asset_id"]) is None:
        raise Invalid("ASSET_NOT_FOUND", "That badge image does not exist.")
    for key, value in data.items():
        if key == "learning_outcomes" and value is not None:
            value = [o.strip() for o in value if o and o.strip()]
        if key == "skills" and value is not None:
            value = [dict(s) for s in value]
        if isinstance(value, str):
            value = value.strip()
        if key in ("title", "short_description", "description", "criteria_narrative", "category"):
            value = value or ""
        if key == "learning_outcomes":
            value = value or []
        if key == "skills":
            value = value or []
        if key == "achievement_type":
            value = value or "Badge"
        if key == "demonstration_kind":
            value = value or "completing"
        setattr(version, key, value)


def create(
    db: Session,
    actor: authz.Actor,
    *,
    issuer_id: uuid.UUID,
    course_id: uuid.UUID | None,
    fields: DraftFields,
    rules: RuleSet | None = None,
    template_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> AchievementDefinition:
    course = db.get(Course, course_id) if course_id else None
    if course_id and course is None:
        raise NotFound("COURSE_NOT_FOUND", "No such course.")
    if course is not None:
        authz.require_course_staff(db, actor, course)
    elif not (actor.is_inst_admin or actor.has("dept_admin")):
        raise Invalid(
            "COURSE_REQUIRED",
            "Choose the Canvas course this badge belongs to.",
            "Only administrators can create badges that are not tied to a course.",
        )
    issuer = authz.require_issuer(db, actor, issuer_id, course)
    if template_id is not None:
        from opencredential.governance import templates

        fields = templates.apply(db, actor, template_id, course, fields)
    definition = AchievementDefinition(
        institution_id=actor.institution_id,
        issuer_id=issuer.id,
        template_id=template_id,
        course_id=course.id if course else None,
        owner_user_id=actor.user_id,
        state="draft",
        award_policy="automatic",
    )
    db.add(definition)
    db.flush()
    version = AchievementVersion(
        institution_id=actor.institution_id,
        definition_id=definition.id,
        version_no=1,
        title="",
        short_description="",
        description="",
        learning_outcomes=[],
        criteria_narrative="",
        category="",
        achievement_type="Badge",
        demonstration_kind="completing",
        skills=[],
    )
    _apply(db, version, fields)
    db.add(version)
    db.flush()
    if rules is not None:
        rules_store.save(db, actor.institution_id, version.id, rules)
    audit.record(
        db,
        action="achievement.create",
        resource_type="achievement_definition",
        resource_id=definition.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "course_id": str(course.id) if course else None,
            "issuer_id": str(issuer.id),
            "template_id": str(template_id) if template_id else None,
        },
    )
    return definition


def _require_state(definition: AchievementDefinition, *states: str) -> None:
    if definition.state not in states:
        raise Conflict(
            "INVALID_STATE",
            f"This badge is {definition.state.replace('_', ' ')}; that action needs it to be "
            + " or ".join(s.replace("_", " ") for s in states)
            + ".",
        )


def update_draft(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    fields: DraftFields,
    request_id: str | None = None,
) -> AchievementVersion:
    authz.require_edit(db, actor, definition)
    _require_state(definition, "draft")
    version = working_version(db, definition)
    _apply(db, version, fields)
    audit.record(
        db,
        action="achievement.edit",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"fields": sorted(fields.model_dump(exclude_unset=True))},
    )
    return version


def set_rules(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    rules: RuleSet,
    request_id: str | None = None,
) -> RuleSet:
    authz.require_edit(db, actor, definition)
    _require_state(definition, "draft")
    if definition.course_id is None and any(
        not isinstance(r, ManualApproval) for r in rules.leaves()
    ):
        raise Invalid(
            "COURSE_REQUIRED",
            "Canvas-based requirements need a course. Badges without a course can only use "
            "staff confirmation.",
        )
    version = working_version(db, definition)
    saved = rules_store.save(db, actor.institution_id, version.id, rules)
    audit.record(
        db,
        action="rules.edit",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"mode": rules.mode, "count": len(rules.leaves())},
    )
    return saved


def delete_draft(db: Session, actor: authz.Actor, definition: AchievementDefinition) -> None:
    authz.require_edit(db, actor, definition)
    if definition.current_version_id is not None or definition.state != "draft":
        raise Conflict(
            "INVALID_STATE",
            "Only drafts that were never published can be deleted. Archive the badge instead.",
        )
    version = working_version(db, definition)
    from opencredential.db.models import AwardRule, AwardRuleSet  # local: keeps imports tidy

    rs = db.scalar(select(AwardRuleSet).where(AwardRuleSet.version_id == version.id))
    if rs is not None:
        for rule in db.scalars(select(AwardRule).where(AwardRule.rule_set_id == rs.id)):
            db.delete(rule)
        db.flush()
        db.delete(rs)
    for review in db.scalars(
        select(DefinitionReview).where(DefinitionReview.definition_id == definition.id)
    ):
        db.delete(review)
    db.flush()
    db.delete(version)
    db.flush()
    db.delete(definition)
    audit.record(
        db,
        action="achievement.delete_draft",
        resource_type="achievement_definition",
        resource_id=definition.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
    )


# ---- readiness checks --------------------------------------------------------------------------


def _issue(field: str, code: str, message: str, severity: str = "error") -> dict[str, Any]:
    return {"field": field, "code": code, "message": message, "severity": severity}


def _rule_source_issues(db: Session, course: Course | None, rules: RuleSet) -> list[dict[str, Any]]:
    if course is None:
        return []
    synced = db.scalar(
        select(func.count())
        .select_from(SyncRun)
        .where(SyncRun.course_id == course.id, SyncRun.status.in_(("ok", "partial")))
    )
    if not synced:
        return [
            _issue(
                "rules",
                "COURSE_NOT_SYNCED",
                "Course data has not been read from Canvas yet, so the modules and assignments "
                "in these rules could not be checked.",
                "warning",
            )
        ]
    out = []
    modules = {
        m.canvas_module_id: m
        for m in db.scalars(select(LmsModule).where(LmsModule.course_id == course.id))
    }
    assignments = {
        a.canvas_assignment_id: a
        for a in db.scalars(select(LmsAssignment).where(LmsAssignment.course_id == course.id))
    }
    for r in rules.leaves():
        mids = (
            [r.module_id]
            if isinstance(r, ModuleCompleted)
            else r.module_ids
            if isinstance(r, ModulesCompleted)
            else []
        )
        for mid in mids:
            m = modules.get(mid)
            if m is None or m.workflow_state == "deleted":
                out.append(
                    _issue(
                        "rules",
                        "RULE_SOURCE_MISSING",
                        f"Module {mid} is not in this Canvas course.",
                    )
                )
            elif not m.has_requirements:
                out.append(
                    _issue(
                        "rules",
                        "MODULE_HAS_NO_REQUIREMENTS",
                        f"Module “{m.name}” has no completion requirements in Canvas, "
                        "so Canvas cannot report completion.",
                    )
                )
            elif m.workflow_state != "active":
                out.append(
                    _issue(
                        "rules",
                        "MODULE_UNPUBLISHED",
                        f"Module “{m.name}” is not published in Canvas.",
                        "warning",
                    )
                )
        if isinstance(r, AssignmentSubmitted | AssignmentScore):
            a = assignments.get(r.assignment_id)
            if a is None or a.deleted:
                out.append(
                    _issue(
                        "rules",
                        "RULE_SOURCE_MISSING",
                        f"Assignment {r.assignment_id} is not in this Canvas course.",
                    )
                )
            elif isinstance(r, AssignmentScore) and not (a.points_possible or 0) > 0:
                out.append(
                    _issue(
                        "rules",
                        "NO_POINTS_POSSIBLE",
                        f"“{a.name}” has no points possible, so a percentage cannot be calculated.",
                    )
                )
            elif not a.published:
                out.append(
                    _issue(
                        "rules",
                        "ASSIGNMENT_UNPUBLISHED",
                        f"“{a.name}” is not published in Canvas.",
                        "warning",
                    )
                )
    return out


def readiness(
    db: Session, definition: AchievementDefinition, version: AchievementVersion
) -> list[dict[str, Any]]:
    """Problems that block submission (``error``) or deserve attention (``warning``)."""
    issues: list[dict[str, Any]] = []
    required = {
        "title": "Add a badge title.",
        "short_description": "Add a short description.",
        "criteria_narrative": "Describe the achievement criteria.",
        "category": "Choose an achievement category.",
    }
    for f, msg in required.items():
        if not (getattr(version, f) or "").strip():
            issues.append(_issue(f, "REQUIRED", msg))
    if not version.learning_outcomes:
        issues.append(_issue("learning_outcomes", "REQUIRED", "Add at least one learning outcome."))
    if version.asset_id is None:
        issues.append(_issue("asset_id", "REQUIRED", "Add badge artwork."))
    if version.category and version.category not in categories(db, definition.institution_id):
        issues.append(
            _issue("category", "CATEGORY_INVALID", "Choose one of the listed categories.")
        )

    # §5.2: completion and attendance must not read as demonstrated competency.
    kind = version.demonstration_kind
    claims_competency = (
        version.category in COMPETENCY_CATEGORIES or version.achievement_type in COMPETENCY_TYPES
    )
    if claims_competency and kind not in ("demonstrating", "assessed"):
        issues.append(
            _issue(
                "demonstration_kind",
                "COMPETENCY_MISMATCH",
                f"A badge for {DEMONSTRATION_KINDS[kind].lower()} cannot be presented as a "
                "competency. Choose a completion or participation category, or change how "
                "achievement is demonstrated.",
            )
        )

    rules = rules_store.load(db, version.id)
    if rules is None:
        issues.append(_issue("rules", "RULES_REQUIRED", "Set the requirements for this badge."))
    else:
        if kind == "assessed" and not any(
            isinstance(r, AssignmentScore | ManualApproval) for r in rules.leaves()
        ):
            issues.append(
                _issue(
                    "rules",
                    "ASSESSMENT_RULE_EXPECTED",
                    "This badge says achievement is assessed, but no requirement checks a mark "
                    "or a member of staff's judgement.",
                    "warning",
                )
            )
        course = db.get(Course, definition.course_id) if definition.course_id else None
        issues.extend(_rule_source_issues(db, course, rules))

    terms = credit_terms(version)
    if terms and not version.credit_claim_approved:
        issues.append(
            _issue(
                "description",
                "CREDIT_TERMS",
                "The wording mentions " + ", ".join(f"“{t}”" for t in terms) + ". Badges must not "
                "imply academic credit or a formal qualification unless the institution approves "
                "it. A reviewer must confirm this before publication.",
                "warning",
            )
        )
    return issues


def _content_hash(db: Session, version: AchievementVersion) -> str:
    rules = rules_store.load(db, version.id)
    content = {f: getattr(version, f) for f in CONTENT_FIELDS}
    content["rules"] = rules_store.strip_ids(rules) if rules else None
    blob = json.dumps(content, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ---- lifecycle -----------------------------------------------------------------------------------


def credit_terms(version: AchievementVersion) -> list[str]:
    """Words in the badge's text that can imply academic credit or a qualification."""
    text_blob = " ".join(
        [
            version.title,
            version.short_description,
            version.description,
            version.criteria_narrative,
            *version.learning_outcomes,
        ]
    )
    return sorted({m.group(0).lower() for m in CREDIT_TERMS.finditer(text_blob)})


def review_forced_reason(version: AchievementVersion) -> str | None:
    """The fixed safeguard: badges that claim assessed proficiency or use credit wording always
    need a colleague's review, whatever their area's setting."""
    if version.demonstration_kind == "assessed":
        return "assessed"
    if credit_terms(version):
        return "credit"
    return None


def review_requirement(
    db: Session, definition: AchievementDefinition, version: AchievementVersion
) -> dict[str, Any]:
    """How this badge version would be reviewed if submitted now.

    ``mode`` is the effective review mode (``required``, ``author_decides`` or
    ``not_required``); ``area_mode`` is what the badge's area set; ``forced_by`` names the
    safeguard that made review required (``assessed`` or ``credit``), if any.
    """
    settings = authz.definition_review_settings(db, definition)
    area_mode = settings["definition_review"]
    forced = review_forced_reason(version)
    source = settings["sources"]["definition_review"]
    return {
        "mode": "required" if forced else area_mode,
        "area_mode": area_mode,
        "forced_by": forced,
        "set_by_org_unit_id": str(source) if source else None,
        "self_approval_allowed": bool(settings["self_approval_allowed"]),
    }


REVIEW_CHOICES = ("colleague", "skip")


def submit(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    request_id: str | None = None,
    *,
    review: str | None = None,
) -> list[dict[str, Any]]:
    """Submit a draft. ``review`` is the author's choice where their area lets them decide:
    ``colleague`` (the default) asks for review, ``skip`` publishes without review."""
    authz.require_edit(db, actor, definition)
    _require_state(definition, "draft")
    if review is not None and review not in REVIEW_CHOICES:
        raise Invalid("REVIEW_CHOICE_INVALID", "Choose colleague review or no review.")
    version = working_version(db, definition)
    issues = readiness(db, definition, version)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise Invalid(
            "DRAFT_INCOMPLETE",
            "This badge is not ready to submit.",
            "; ".join(e["message"] for e in errors),
            errors=[
                {"field": e["field"], "code": e["code"], "message": e["message"]} for e in errors
            ],
        )
    requirement = review_requirement(db, definition, version)
    mode = requirement["mode"]
    if review == "skip" and mode == "required":
        reason = {
            "assessed": "Badges that claim assessed proficiency always need a colleague's review.",
            "credit": "Badges whose wording refers to credit or a qualification always need a "
            "colleague's review.",
        }.get(requirement["forced_by"] or "", "Your area requires a colleague to review badges.")
        raise Conflict("REVIEW_REQUIRED", reason)
    version.content_hash = _content_hash(db, version)
    definition.state = "in_review"
    # An explicit request for a colleague's review is always honoured, even where none is needed.
    skip = review != "colleague" and (
        mode == "not_required" or (mode == "author_decides" and review == "skip")
    )
    audit.record(
        db,
        action="achievement.submit",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "content_hash": version.content_hash,
            "review_mode": mode,
            "review": "skipped" if skip else "requested",
            **({"review_forced_by": requirement["forced_by"]} if requirement["forced_by"] else {}),
        },
    )
    if skip:
        definition.state = "approved"
        author_chose = mode == "author_decides"
        db.add(
            DefinitionReview(
                institution_id=actor.institution_id,
                definition_id=definition.id,
                version_id=version.id,
                reviewer_id=actor.user_id,
                decision="approve",
                checklist={"policy": f"definition_review={mode}"},
                comment=(
                    "Published without review: the author chose not to ask a colleague."
                    if author_chose
                    else "Approved automatically: review is not required in this area."
                ),
                without_review=True,
            )
        )
    return issues


def approve(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    *,
    checklist: dict[str, bool],
    comment: str | None,
    credit_claim_approved: bool | None = None,
    request_id: str | None = None,
) -> DefinitionReview:
    policy = authz.institution_policy(db, actor.institution_id)
    authz.require_review(db, actor, definition, policy)
    _require_state(definition, "in_review")
    missing = [k for k in REVIEW_CHECKLIST if not checklist.get(k)]
    if missing:
        raise Invalid(
            "CHECKLIST_INCOMPLETE",
            "Confirm every review check before approving.",
            "Unchecked: " + ", ".join(missing),
        )
    version = working_version(db, definition)
    if version.content_hash != _content_hash(db, version):
        raise Conflict("CONTENT_CHANGED", "The badge changed after it was submitted.")
    if credit_claim_approved is not None:
        version.credit_claim_approved = credit_claim_approved
    review = DefinitionReview(
        institution_id=actor.institution_id,
        definition_id=definition.id,
        version_id=version.id,
        reviewer_id=actor.user_id,
        decision="approve",
        checklist={k: bool(checklist.get(k)) for k in REVIEW_CHECKLIST},
        comment=comment,
    )
    db.add(review)
    definition.state = "approved"
    audit.record(
        db,
        action="achievement.approve",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"credit_claim_approved": version.credit_claim_approved},
    )
    return review


def reject(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    *,
    comment: str,
    checklist: dict[str, bool] | None = None,
    request_id: str | None = None,
) -> DefinitionReview:
    policy = authz.institution_policy(db, actor.institution_id)
    authz.require_review(db, actor, definition, policy)
    _require_state(definition, "in_review", "approved")
    if not comment or len(comment.strip()) < 5:
        raise Invalid("COMMENT_REQUIRED", "Explain what needs to change.")
    version = working_version(db, definition)
    review = DefinitionReview(
        institution_id=actor.institution_id,
        definition_id=definition.id,
        version_id=version.id,
        reviewer_id=actor.user_id,
        decision="reject",
        checklist={k: bool(v) for k, v in (checklist or {}).items() if k in REVIEW_CHECKLIST},
        comment=comment.strip(),
    )
    db.add(review)
    definition.state = "draft"
    version.content_hash = None
    audit.record(
        db,
        action="achievement.reject",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
    )
    return review


def resolve_award_policy(
    version_choice: str | None, rules: RuleSet, policy: dict[str, Any]
) -> tuple[str, str | None]:
    """ADR-0017: the badge's choice, else the institution default for score badges.

    Returns ``(policy, note)``; ``note`` explains any institutional override.
    """
    has_score = rules.has_score_rule()
    if version_choice is None:
        chosen = (
            policy.get("score_rules_default_policy", "lecturer_confirmed")
            if has_score
            else ("automatic")
        )
    else:
        chosen = version_choice
    if has_score and chosen == "automatic" and policy.get("score_rules_force_confirmation"):
        return "lecturer_confirmed", (
            "Your institution requires staff confirmation for badges based on marks."
        )
    return chosen, None


def publish(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    request_id: str | None = None,
) -> AchievementVersion:
    policy = authz.institution_policy(db, actor.institution_id)
    if not (
        authz.can_edit_definition(db, actor, definition)
        or authz.can_review(db, actor, definition, policy)
    ):
        authz.require_edit(db, actor, definition)
    _require_state(definition, "approved")
    version = working_version(db, definition)
    if version.content_hash != _content_hash(db, version):
        raise Conflict("CONTENT_CHANGED", "The badge changed after it was approved.")
    issuer = db.get(Issuer, definition.issuer_id)
    if issuer is None or issuer.status != "active":
        raise Conflict("ISSUER_INACTIVE", "The issuer for this badge is not active.")
    authz.require_issuing_allowed(db, issuer, authz.definition_course(db, definition))
    issues = readiness(db, definition, version)
    blocking = [i for i in issues if i["severity"] == "error"]
    if any(i["code"] == "CREDIT_TERMS" for i in issues):
        blocking.append(
            _issue(
                "description",
                "CREDIT_CLAIM_NOT_APPROVED",
                "The wording implies academic credit or a qualification. A reviewer must "
                "approve that claim, or the wording must change.",
            )
        )
    if blocking:
        raise Invalid(
            "NOT_PUBLISHABLE",
            "This badge cannot be published yet.",
            "; ".join(b["message"] for b in blocking),
            errors=[
                {"field": b["field"], "code": b["code"], "message": b["message"]} for b in blocking
            ],
        )
    rules = rules_store.load(db, version.id)
    assert rules is not None
    resolved, note = resolve_award_policy(version.award_policy, rules, policy)
    now = _now()
    version.award_policy = resolved
    version.description = version.description or version.short_description
    version.content_hash = _content_hash(db, version)
    version.published_at = now
    version.published_by = actor.user_id
    db.flush()
    version.frozen = True
    previous = definition.current_version_id
    definition.current_version_id = version.id
    definition.award_policy = resolved
    definition.state = "published"
    audit.record(
        db,
        action="achievement.publish",
        resource_type="achievement_version",
        resource_id=version.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "version_no": version.version_no,
            "award_policy": resolved,
            "policy_note": note,
            "replaces": str(previous) if previous else None,
        },
    )
    if definition.course_id is not None:
        enqueue.defer(
            db,
            enqueue.EVALUATE_COURSE,
            queue="eligibility",
            institution_id=actor.institution_id,
            args={"course_id": str(definition.course_id), "triggered_by": "reeval"},
            subject_type="course",
            subject_id=definition.course_id,
            queueing_lock=f"evaluate_course:{definition.course_id}",
        )
    return version


def archive(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    request_id: str | None = None,
) -> None:
    policy = authz.institution_policy(db, actor.institution_id)
    if not authz.can_review(db, actor, definition, policy):
        authz.require_edit(db, actor, definition)
    if definition.state == "archived":
        return
    if definition.current_version_id is None:
        raise Conflict("INVALID_STATE", "Only published badges can be archived. Delete the draft.")
    definition.state = "archived"
    audit.record(
        db,
        action="achievement.archive",
        resource_type="achievement_definition",
        resource_id=definition.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
    )


def new_version(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    request_id: str | None = None,
) -> AchievementVersion:
    authz.require_edit(db, actor, definition)
    _require_state(definition, "published")
    live = db.get(AchievementVersion, definition.current_version_id)
    assert live is not None
    draft = AchievementVersion(
        institution_id=live.institution_id,
        definition_id=definition.id,
        version_no=live.version_no + 1,
        **{f: getattr(live, f) for f in CONTENT_FIELDS if f != "award_policy"},
        award_policy=live.award_policy,
        credit_claim_approved=False,
    )
    db.add(draft)
    db.flush()
    rules = rules_store.load(db, live.id)
    if rules is not None:
        from opencredential.rules.schema import parse

        rules_store.save(db, live.institution_id, draft.id, parse(rules_store.strip_ids(rules)))
    definition.state = "draft"
    audit.record(
        db,
        action="achievement.new_version",
        resource_type="achievement_version",
        resource_id=draft.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"from_version": str(live.id), "version_no": draft.version_no},
    )
    return draft
