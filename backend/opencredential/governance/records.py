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
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from opencredential.authz import policy as authz
from opencredential.credentials.state import ACTIVE, REVOKED, credential_state, state_sql
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


def _base(db: Session, actor: authz.Actor, course_staff_of: uuid.UUID | None = None) -> Any:
    """One row per issued credential in scope, as plain columns (no ORM objects), so that large
    exports and reports stay cheap."""
    q = (
        select(
            Credential.id.label("credential_id"),
            Credential.issued_at,
            Credential.valid_until,
            AchievementDefinition.id.label("definition_id"),
            AchievementVersion.title.label("badge_title"),
            AchievementVersion.version_no,
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Course.course_code,
            Issuer.name.label("issuer_name"),
            User.display_name,
            User.status.label("user_status"),
            AwardDecision.kind.label("award_kind"),
            CredentialStatus.state.label("status_state"),
            CredentialStatus.changed_at.label("status_changed_at"),
            CredentialStatus.reason_code.label("status_reason"),
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
    if course_staff_of is not None:
        # Course staff see their own course's records; the caller checked they are staff.
        return q.where(AchievementDefinition.course_id == course_staff_of)
    cond = _scope_filter(db, actor)
    return q if cond is None else q.where(cond)


def _day_start(d: date | None) -> datetime | None:
    return datetime.combine(d, time.min, tzinfo=UTC) if d else None


def _filtered(
    db: Session,
    actor: authz.Actor,
    now: datetime,
    *,
    course_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    status: str | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
    learner: str | None = None,
    course_staff_of: uuid.UUID | None = None,
) -> Any:
    q = _base(db, actor, course_staff_of)
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
    # The status filter is in SQL, so LIMIT/OFFSET pages are always full and consistent, and it
    # is the same rule each row's "status" is worked out with (credentials.state).
    if status:
        q = q.where(state_sql(now) == status)
    return q


def _row(r: Any, now: datetime) -> dict[str, Any]:
    row_status = credential_state(r.status_state, r.valid_until, now)
    return {
        "credential_id": str(r.credential_id),
        "definition_id": str(r.definition_id),
        "course_id": str(r.course_id) if r.course_id else None,
        "issued_at": r.issued_at,
        "badge_title": r.badge_title,
        "version_no": r.version_no,
        "course_title": r.course_title,
        "course_code": r.course_code,
        "issuer_name": r.issuer_name,
        "learner_name": r.display_name if r.user_status == "active" else None,
        "award_kind": r.award_kind,
        "status": row_status,
        "revoked_at": r.status_changed_at if row_status == REVOKED else None,
        "revocation_reason": r.status_reason,
        "can_revoke": row_status != REVOKED,
    }


def records(
    db: Session,
    actor: authz.Actor,
    *,
    limit: int = 200,
    offset: int = 0,
    **filters: Any,
) -> list[dict[str, Any]]:
    """One page of records, newest first. Filters as for :func:`iter_records`."""
    now = datetime.now(UTC)
    q = _filtered(db, actor, now, **filters)
    q = q.order_by(Credential.issued_at.desc(), Credential.id).offset(offset).limit(limit)
    return [_row(r, now) for r in db.execute(q)]


def iter_records(db: Session, actor: authz.Actor, **filters: Any) -> Iterator[dict[str, Any]]:
    """Every matching record, newest first, fetched in batches (for CSV export)."""
    now = datetime.now(UTC)
    q = _filtered(db, actor, now, **filters).order_by(Credential.issued_at.desc(), Credential.id)
    for r in db.execute(q.execution_options(yield_per=1000)):
        yield _row(r, now)


def to_csv(rows: Iterable[dict[str, Any]], columns: Iterable[str]) -> str:
    """CSV with formula-injection protection (cells starting with = + - @ are quoted with ')."""
    return to_csv_counted(rows, columns)[0]


def to_csv_counted(rows: Iterable[dict[str, Any]], columns: Iterable[str]) -> tuple[str, int]:
    """As :func:`to_csv`, also returning the number of data rows. ``rows`` may be a generator:
    only the CSV text is held in memory, not the records."""
    cols = list(columns)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    n = 0
    for row in rows:
        w.writerow([_cell(row.get(c)) for c in cols])
        n += 1
    return buf.getvalue(), n


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
    pending awards and failed issuance. Every count is worked out in PostgreSQL."""
    now = datetime.now(UTC)
    base = _filtered(db, actor, now, issued_from=issued_from, issued_to=issued_to).subquery()
    state = state_sql(now, status_state=base.c.status_state, valid_until=base.c.valid_until)
    revoked = func.count().filter(state == REVOKED)
    active = func.count().filter(state == ACTIVE)
    total, n_revoked, n_active = db.execute(
        select(func.count(), revoked, active).select_from(base)
    ).one()

    by_course = [
        {
            "course_id": str(cid) if cid else None,
            "course_title": title or "(no course)",
            "issued": int(n),
            "revoked": int(r),
        }
        for cid, title, n, r in db.execute(
            select(base.c.course_id, base.c.course_title, func.count(), revoked)
            .select_from(base)
            .group_by(base.c.course_id, base.c.course_title)
        )
    ]

    badge_rows = db.execute(
        select(base.c.definition_id, base.c.course_title, func.count(), revoked)
        .select_from(base)
        .group_by(base.c.definition_id, base.c.course_title)
    ).all()
    titles = _badge_titles(db, [r[0] for r in badge_rows])
    by_badge = [
        {
            "definition_id": str(did),
            "badge_title": titles.get(did, ""),
            "course_title": course_title,
            "issued": int(n),
            "revoked": int(r),
        }
        for did, course_title, n, r in badge_rows
    ]

    month = func.to_char(func.timezone("UTC", base.c.issued_at), "YYYY-MM")
    by_month = [
        {"month": m, "issued": int(n)}
        for m, n in db.execute(
            select(month, func.count())
            .select_from(base)
            .where(base.c.issued_at.is_not(None))
            .group_by(month)
            .order_by(month)
        )
    ]
    return {
        "issued": int(total),
        "revoked": int(n_revoked),
        "active": int(n_active),
        "pending_awards": pending_awards(db, actor),
        "failed_issuance": failed_issuance(db, actor),
        "by_course": sorted(by_course, key=lambda x: (-x["issued"], x["course_title"])),
        "by_badge": sorted(by_badge, key=lambda x: (-x["issued"], x["badge_title"])),
        "by_month": by_month,
    }


def _badge_titles(db: Session, definition_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each badge's current title (its latest version when no current version is set)."""
    if not definition_ids:
        return {}
    latest = (
        select(AchievementVersion.definition_id, func.max(AchievementVersion.version_no).label("n"))
        .where(AchievementVersion.definition_id.in_(definition_ids))
        .group_by(AchievementVersion.definition_id)
        .subquery()
    )
    rows = db.execute(
        select(AchievementDefinition.id, AchievementVersion.title)
        .join(latest, latest.c.definition_id == AchievementDefinition.id)
        .join(
            AchievementVersion,
            (AchievementVersion.definition_id == AchievementDefinition.id)
            & (
                (AchievementVersion.id == AchievementDefinition.current_version_id)
                | (
                    AchievementDefinition.current_version_id.is_(None)
                    & (AchievementVersion.version_no == latest.c.n)
                )
            ),
        )
    )
    return {did: title for did, title in rows}


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
