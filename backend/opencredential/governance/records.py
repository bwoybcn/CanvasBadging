# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institution-wide issuance records, operational reporting and CSV export (spec §10.5).

Scope: institution administrators see everything; department administrators see credentials
from courses and issuers in the org units they administer. Records carry the learner's display
name (needed to act on a record) but never an email address.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    AwardDecision,
    Course,
    Credential,
    CredentialStatus,
    Issuer,
    User,
    background_jobs,
)

RECORD_COLUMNS = (
    "credential_id",
    "issued_at",
    "badge_title",
    "version_no",
    "course_title",
    "course_code",
    "issuer_name",
    "learner_name",
    "award_kind",
    "status",
    "revoked_at",
    "revocation_reason",
)


def _scope_filter(db: Session, actor: authz.Actor) -> Any:
    """SQL condition limiting rows to the actor's administrative scope, or ``None``."""
    authz.require_admin(actor)
    units = authz.admin_org_units(db, actor)
    if units is None:
        return None
    if not units:
        return Credential.id.is_(None)  # nothing
    return or_(Course.org_unit_id.in_(units), Issuer.org_unit_id.in_(units))


def _base(db: Session, actor: authz.Actor) -> Any:
    q = (
        select(
            Credential,
            AchievementVersion,
            AchievementDefinition,
            Course,
            Issuer,
            User,
            CredentialStatus,
            AwardDecision,
        )
        .join(AchievementVersion, AchievementVersion.id == Credential.version_id)
        .join(AchievementDefinition, AchievementDefinition.id == AchievementVersion.definition_id)
        .outerjoin(Course, Course.id == AchievementDefinition.course_id)
        .join(Issuer, Issuer.id == Credential.issuer_id)
        .join(User, User.id == Credential.user_id)
        .join(AwardDecision, AwardDecision.id == Credential.award_decision_id)
        .outerjoin(CredentialStatus, CredentialStatus.credential_id == Credential.id)
        .where(Credential.status == "issued")
    )
    cond = _scope_filter(db, actor)
    return q if cond is None else q.where(cond)


def _status(cred: Credential, st: CredentialStatus | None, now: datetime) -> str:
    if st is not None and st.state == "revoked":
        return "revoked"
    if cred.valid_until is not None and cred.valid_until < now:
        return "expired"
    return "active"


def _day_start(d: date | None) -> datetime | None:
    return datetime.combine(d, time.min, tzinfo=UTC) if d else None


def records(
    db: Session,
    actor: authz.Actor,
    *,
    course_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    status: str | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
    learner: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    q = _base(db, actor)
    if course_id:
        q = q.where(AchievementDefinition.course_id == course_id)
    if definition_id:
        q = q.where(AchievementDefinition.id == definition_id)
    if issued_from:
        q = q.where(Credential.issued_at >= _day_start(issued_from))
    if issued_to:
        q = q.where(Credential.issued_at < _day_start(issued_to) + timedelta(days=1))  # type: ignore[operator]
    if learner:
        q = q.where(User.display_name.ilike(f"%{learner.strip()}%"))
    if status == "revoked":
        q = q.where(CredentialStatus.state == "revoked")
    elif status == "active":
        q = q.where(or_(CredentialStatus.state.is_(None), CredentialStatus.state != "revoked"))
    q = q.order_by(Credential.issued_at.desc()).offset(offset).limit(limit)
    now = datetime.now(UTC)
    out = []
    for cred, ver, defn, course, issuer, user, st, decision in db.execute(q):
        row_status = _status(cred, st, now)
        if status == "active" and row_status != "active":
            continue
        out.append(
            {
                "credential_id": str(cred.id),
                "definition_id": str(defn.id),
                "course_id": str(course.id) if course else None,
                "issued_at": cred.issued_at,
                "badge_title": ver.title,
                "version_no": ver.version_no,
                "course_title": course.title if course else None,
                "course_code": course.course_code if course else None,
                "issuer_name": issuer.name,
                "learner_name": user.display_name if user.status == "active" else None,
                "award_kind": decision.kind,
                "status": row_status,
                "revoked_at": st.changed_at if st is not None and st.state == "revoked" else None,
                "revocation_reason": st.reason_code if st is not None else None,
                "can_revoke": row_status != "revoked",
            }
        )
    return out


def to_csv(rows: Iterable[dict[str, Any]], columns: Iterable[str]) -> str:
    """CSV with formula-injection protection (cells starting with = + - @ are quoted with ')."""
    cols = list(columns)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for row in rows:
        w.writerow([_cell(row.get(c)) for c in cols])
    return buf.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="seconds")
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


# ---- summary -------------------------------------------------------------------------------


def summary(
    db: Session,
    actor: authz.Actor,
    *,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> dict[str, Any]:
    """Counts for the operational report: issued, by course, by badge, by month, revocations,
    pending awards and failed issuance."""
    rows = records(
        db, actor, issued_from=issued_from, issued_to=issued_to, limit=1_000_000, offset=0
    )
    by_course: dict[str, dict[str, Any]] = {}
    by_badge: dict[str, dict[str, Any]] = {}
    by_month: dict[str, int] = {}
    revoked = 0
    for r in rows:
        key = r["course_id"] or "none"
        c = by_course.setdefault(
            key,
            {
                "course_id": r["course_id"],
                "course_title": r["course_title"] or "(no course)",
                "issued": 0,
                "revoked": 0,
            },
        )
        b = by_badge.setdefault(
            r["definition_id"],
            {
                "definition_id": r["definition_id"],
                "badge_title": r["badge_title"],
                "course_title": r["course_title"],
                "issued": 0,
                "revoked": 0,
            },
        )
        c["issued"] += 1
        b["issued"] += 1
        if r["status"] == "revoked":
            revoked += 1
            c["revoked"] += 1
            b["revoked"] += 1
        if r["issued_at"]:
            month = r["issued_at"].astimezone(UTC).strftime("%Y-%m")
            by_month[month] = by_month.get(month, 0) + 1
    return {
        "issued": len(rows),
        "revoked": revoked,
        "active": sum(1 for r in rows if r["status"] == "active"),
        "pending_awards": pending_awards(db, actor),
        "failed_issuance": failed_issuance(db, actor),
        "by_course": sorted(by_course.values(), key=lambda x: (-x["issued"], x["course_title"])),
        "by_badge": sorted(by_badge.values(), key=lambda x: (-x["issued"], x["badge_title"])),
        "by_month": [{"month": k, "issued": v} for k, v in sorted(by_month.items())],
    }


def _decision_scope(db: Session, actor: authz.Actor) -> Any:
    q = (
        select(AwardDecision)
        .join(AchievementVersion, AchievementVersion.id == AwardDecision.version_id)
        .join(AchievementDefinition, AchievementDefinition.id == AchievementVersion.definition_id)
        .outerjoin(Course, Course.id == AchievementDefinition.course_id)
        .join(Issuer, Issuer.id == AwardDecision.issuer_id)
    )
    units = authz.admin_org_units(db, actor)
    if units is not None:
        q = q.where(or_(Course.org_unit_id.in_(units), Issuer.org_unit_id.in_(units)))
    return q


def pending_awards(db: Session, actor: authz.Actor) -> dict[str, int]:
    """Awards waiting for a person (confirmation) and awards decided but not yet issued."""
    base = _decision_scope(db, actor).subquery()
    awaiting = db.scalar(
        select(func.count()).select_from(base).where(base.c.status == "awaiting_confirmation")
    )
    ready = db.scalar(
        select(func.count())
        .select_from(base)
        .where(
            base.c.status == "ready",
            ~select(Credential.id)
            .where(Credential.award_decision_id == base.c.id, Credential.status == "issued")
            .exists(),
        )
    )
    return {"awaiting_confirmation": int(awaiting or 0), "awaiting_issuance": int(ready or 0)}


def failed_issuance(db: Session, actor: authz.Actor) -> dict[str, int]:
    units = authz.admin_org_units(db, actor)
    stuck_q = (
        select(func.count())
        .select_from(Credential)
        .where(Credential.status.in_(("pending_signature", "failed")))
    )
    if units is not None:
        stuck_q = stuck_q.join(Issuer, Issuer.id == Credential.issuer_id).where(
            Issuer.org_unit_id.in_(units)
        )
    failed_jobs = 0
    if units is None:  # job rows carry no org unit; only institution admins see them
        failed_jobs = int(
            db.scalar(
                select(func.count())
                .select_from(background_jobs)
                .where(background_jobs.c.status == "failed")
            )
            or 0
        )
    return {"credentials_not_issued": int(db.scalar(stuck_q) or 0), "failed_jobs": failed_jobs}
