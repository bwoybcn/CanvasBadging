# SPDX-License-Identifier: AGPL-3.0-or-later
"""Award a badge to a list of learners (extracurricular badges, PR 2 of 4).

Providers often hold the evidence outside Canvas: a volunteering log, a workshop register, an
events system. Staff paste or upload the list of student ID numbers or university emails; we
match each one to a student enrolled in the badge's course, show a preview, and on confirmation
make one manual award per learner with the same written justification.

* Learners must be students in the badge's course. Enrolment stays Canvas's job (self-enrol link,
  SIS feed), so a list cannot reach anyone outside the course.
* Identifiers are matched only against the course's students. Anyone else, enrolled elsewhere or
  not at all, gets the same ``not_found`` row with no name, so the preview cannot be used to look
  up who an email or student number belongs to across the institution.
* Student ID numbers match the SIS user id Canvas sends at launch or in the roster; emails match
  the address Canvas holds for the learner, ignoring case.
* Each award goes through :func:`eligibility.service.make_manual_award`, the same code as a
  single manual award, so second approval, audit and issuance behave exactly the same.
* Identifiers are never written to the audit log: one ``award.bulk`` event records the counts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    Course,
    ExternalIdentity,
    User,
)
from opencredential.eligibility import service as eligibility
from opencredential.errors import DomainError, Invalid

MAX_IDENTIFIERS = 1000

#: Row statuses, in the order the preview lists them.
WILL_AWARD = "will_award"
AWARDED = "awarded"
AWAITING_CONFIRMATION = "awaiting_confirmation"
ALREADY_AWARDED = "already_awarded"
PENDING = "pending_confirmation"
NOT_FOUND = "not_found"
DUPLICATE = "duplicate"
FAILED = "failed"


@dataclass
class Row:
    identifier: str
    status: str
    user_id: uuid.UUID | None = None
    learner_name: str | None = None
    decision_id: uuid.UUID | None = None
    message: str | None = None


@dataclass
class BulkResult:
    rows: list[Row] = field(default_factory=list)
    committed: bool = False
    #: Each award waits for a second member of staff (the badge's area requires it).
    second_approval: bool = False

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.status] = out.get(r.status, 0) + 1
        return out


def parse_identifiers(raw: list[str]) -> list[str]:
    """Split pasted text (lines, commas, semicolons, tabs), trim, drop blanks and header-like
    cells, keep order. Duplicates are kept so the preview can point them out."""
    out: list[str] = []
    for item in raw:
        for part in str(item).replace(";", "\n").replace(",", "\n").replace("\t", "\n").split():
            value = part.strip().strip('"').strip("'")
            if value and value.lower() not in ("email", "student_id", "id", "sis_user_id"):
                out.append(value)
    if not out:
        raise Invalid("LIST_EMPTY", "Paste at least one student ID number or email.")
    if len(out) > MAX_IDENTIFIERS:
        raise Invalid(
            "LIST_TOO_LONG",
            f"Award to at most {MAX_IDENTIFIERS} students at a time. Split the list.",
        )
    return out


def _match(
    db: Session, course: Course, students: set[uuid.UUID], identifiers: list[str]
) -> dict[str, uuid.UUID]:
    """Map each identifier to one of ``students`` (the course's students), where one matches."""
    if not students:
        return {}
    emails = {i.lower() for i in identifiers if "@" in i}
    ids = {i for i in identifiers if "@" not in i}
    found: dict[str, uuid.UUID] = {}
    if emails:
        for uid, email in db.execute(
            select(User.id, func.lower(User.email)).where(
                func.lower(User.email).in_(emails),
                User.status == "active",
                User.id.in_(students),
            )
        ):
            # Two students in the course with one email: refuse to guess (treated as not found).
            found[email] = uid if email not in found else uuid.UUID(int=0)
    if ids:
        for uid, value in db.execute(
            select(ExternalIdentity.user_id, ExternalIdentity.value).where(
                ExternalIdentity.canvas_integration_id == course.canvas_integration_id,
                ExternalIdentity.kind == "sis_user_id",
                ExternalIdentity.value.in_(ids),
                ExternalIdentity.user_id.in_(students),
            )
        ):
            found[value] = uid
    return {k: v for k, v in found.items() if v.int != 0}


def award_list(
    db: Session,
    actor: authz.Actor,
    definition: AchievementDefinition,
    *,
    identifiers: list[str],
    justification: str,
    evidence: list[dict[str, Any]] | None = None,
    confirm: bool = False,
    request_id: str | None = None,
) -> BulkResult:
    """Preview (``confirm=False``) or make (``confirm=True``) manual awards for a list."""
    eligibility.require_award_staff(db, actor, definition)
    course = db.get(Course, definition.course_id) if definition.course_id else None
    if course is None:
        raise Invalid(
            "COURSE_REQUIRED",
            "Awarding to a list needs a badge that belongs to a Canvas course.",
        )
    target = eligibility.live_target(db, definition)
    if target is None:
        raise Invalid("NOT_LIVE", "Only published badges can be awarded.")
    justification = (justification or "").strip()
    if len(justification) < eligibility.MIN_JUSTIFICATION:
        raise Invalid(
            "JUSTIFICATION_REQUIRED",
            "Explain why this badge is awarded "
            f"(at least {eligibility.MIN_JUSTIFICATION} characters).",
        )
    items = parse_identifiers(identifiers)
    students = set(eligibility.course_students(db, course.id))
    matches = _match(db, course, students, items)
    # Checked once for the whole list: staff rights, live version and justification above, and
    # each learner against the course's students below.
    second = bool(
        authz.definition_review_settings(db, definition)["manual_awards_require_second_approval"]
    )
    result = BulkResult(committed=confirm, second_approval=second)
    seen: set[uuid.UUID] = set()
    for ident in items:
        key = ident.lower() if "@" in ident else ident
        uid = matches.get(key)
        if uid is None:
            result.rows.append(Row(ident, NOT_FOUND))
            continue
        user = db.get(User, uid)
        name = user.display_name if user else None
        if uid in seen:
            result.rows.append(Row(ident, DUPLICATE, uid, name))
            continue
        seen.add(uid)
        existing = eligibility.existing_live_decision(db, target.version.id, uid)
        if existing is not None:
            status = PENDING if existing.status == "awaiting_confirmation" else ALREADY_AWARDED
            result.rows.append(Row(ident, status, uid, name, existing.id))
            continue
        if not confirm:
            result.rows.append(Row(ident, WILL_AWARD, uid, name))
            continue
        try:
            with db.begin_nested():
                decision, _ = eligibility.make_manual_award(
                    db,
                    actor,
                    target,
                    user_id=uid,
                    justification=justification,
                    evidence=evidence,
                    second_approval=second,
                    request_id=request_id,
                )
        except DomainError as exc:
            result.rows.append(Row(ident, FAILED, uid, name, message=exc.title))
            continue
        status = AWAITING_CONFIRMATION if decision.status == "awaiting_confirmation" else AWARDED
        result.rows.append(Row(ident, status, uid, name, decision.id))
    if confirm:
        audit.record(
            db,
            action="award.bulk",
            resource_type="achievement_definition",
            resource_id=definition.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"version_id": str(target.version.id), "counts": result.counts()},
        )
    return result
