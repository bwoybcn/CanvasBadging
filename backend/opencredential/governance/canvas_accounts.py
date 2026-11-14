# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link chosen Canvas sub-accounts to areas (org units).

Canvas keeps courses in a tree of accounts: the root account, then sub-accounts (often one per
faculty or service, sometimes deeper for departments), then courses. An institution
administrator reads that tree from Canvas and ticks the sub-accounts that should become areas.

* Each ticked sub-account gets an area named after it (or is linked to an existing area). Its
  parent area is the area of the nearest ticked sub-account above it.
* A course joins an area when it is first launched, from the nearest linked sub-account above
  it. Courses already in an area are never moved, so a manual choice always wins.
* Sub-accounts nobody ticks are ignored. Terms, sandboxes and other housekeeping sub-accounts
  therefore never become areas.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import CanvasAccount, CanvasIntegration, Course, OrgUnit
from opencredential.errors import DomainError, Invalid, NotFound
from opencredential.governance import people
from opencredential.integrations.base import (
    AccountDirectory,
    AccountRecord,
    LmsError,
    LmsPermissionError,
)

MAX_DEPTH = 50
#: Canvas's internal top-level account. It never holds courses, so it is never offered.
SITE_ADMIN = "site admin"


class CanvasUnavailable(DomainError):
    status = 502


def _directory(integration: CanvasIntegration) -> AccountDirectory | None:
    from opencredential.integrations.registry import get_adapter

    try:
        adapter = get_adapter(integration, "")
    except LmsError:
        return None
    return adapter if isinstance(adapter, AccountDirectory) else None


# ---- reading the tree ------------------------------------------------------------------------


def _without_site_admin(accounts: Sequence[AccountRecord]) -> list[AccountRecord]:
    """Leave out Canvas's top-level "Site Admin" account and anything below it."""
    dropped = {
        a.account_id
        for a in accounts
        if a.parent_id is None and a.name.strip().lower() == SITE_ADMIN
    }
    out = []
    for a in accounts:
        if a.account_id in dropped or a.parent_id in dropped:
            dropped.add(a.account_id)
            continue
        out.append(a)
    return out


def refresh(db: Session, actor: authz.Actor, *, request_id: str | None = None) -> dict[str, Any]:
    """Read the account tree from every connected Canvas and store it."""
    authz.require_inst_admin(actor)
    now = datetime.now(UTC)
    read = 0
    integrations = db.scalars(select(CanvasIntegration)).all()
    connected = 0
    for integration in integrations:
        directory = _directory(integration)
        if directory is None:
            continue
        try:
            accounts = directory.list_accounts()
        except LmsPermissionError as exc:
            raise CanvasUnavailable(
                "CANVAS_ACCOUNTS_FORBIDDEN",
                "Canvas refused to list its sub-accounts.",
                "Add the scopes url:GET|/api/v1/accounts and "
                "url:GET|/api/v1/accounts/:account_id/sub_accounts to the OpenCredential API "
                "developer key in Canvas, then reconnect Canvas under Canvas connection. The "
                "person who connects must be a Canvas account administrator.",
                status=409,
            ) from exc
        except LmsError as exc:
            raise CanvasUnavailable(
                "CANVAS_UNAVAILABLE",
                "Canvas did not return its sub-accounts.",
                "Canvas did not answer properly. Try again in a few minutes.",
            ) from exc
        connected += 1
        accounts = _without_site_admin(accounts)
        existing = {
            r.account_id: r
            for r in db.scalars(
                select(CanvasAccount).where(CanvasAccount.canvas_integration_id == integration.id)
            )
        }
        seen = set()
        for a in accounts:
            seen.add(a.account_id)
            row = existing.get(a.account_id)
            if row is None:
                row = CanvasAccount(
                    institution_id=actor.institution_id,
                    canvas_integration_id=integration.id,
                    account_id=a.account_id,
                    name=a.name,
                )
                db.add(row)
            row.name, row.parent_account_id, row.refreshed_at = a.name, a.parent_id, now
            read += 1
        # Forget sub-accounts Canvas no longer reports, unless someone linked them.
        for account_id, row in existing.items():
            if account_id not in seen and row.org_unit_id is None:
                db.delete(row)
    if not connected:
        raise CanvasUnavailable(
            "CANVAS_NOT_CONNECTED",
            "No Canvas connection can list sub-accounts yet.",
            "Finish the Canvas setup under Canvas connection first.",
            status=409,
        )
    db.flush()
    audit.record(
        db,
        action="canvas_accounts.refresh",
        resource_type="canvas_account",
        resource_id=None,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"accounts": read},
    )
    return {"accounts": read}


def _ordered(rows: Iterable[CanvasAccount]) -> list[tuple[CanvasAccount, int]]:
    """Rows depth-first (parents before children, siblings by name), with their depth."""
    rows = list(rows)
    keys = {(r.canvas_integration_id, r.account_id) for r in rows}
    children: dict[tuple[uuid.UUID, str | None], list[CanvasAccount]] = {}
    for r in rows:
        parent = r.parent_account_id
        if (r.canvas_integration_id, parent) not in keys:
            parent = None  # a root, or a parent the connected user cannot see
        children.setdefault((r.canvas_integration_id, parent), []).append(r)
    out: list[tuple[CanvasAccount, int]] = []

    def walk(integration_id: uuid.UUID, parent: str | None, depth: int) -> None:
        for r in sorted(children.get((integration_id, parent), []), key=lambda x: x.name.lower()):
            out.append((r, depth))
            if depth < MAX_DEPTH:
                walk(integration_id, r.account_id, depth + 1)

    for integration_id in sorted({r.canvas_integration_id for r in rows}, key=str):
        walk(integration_id, None, 0)
    return out


def listing(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    authz.require_inst_admin(actor)
    rows = db.scalars(select(CanvasAccount)).all()
    units = {u.id: u for u in db.scalars(select(OrgUnit))}
    counts = {
        (i, a): n
        for i, a, n in db.execute(
            select(Course.canvas_integration_id, Course.canvas_account_id, func.count())
            .where(Course.canvas_account_id.is_not(None))
            .group_by(Course.canvas_integration_id, Course.canvas_account_id)
        ).all()
    }
    out = []
    for r, depth in _ordered(rows):
        unit = units.get(r.org_unit_id) if r.org_unit_id else None
        out.append(
            {
                "id": str(r.id),
                "account_id": r.account_id,
                "name": r.name,
                "parent_account_id": r.parent_account_id,
                "depth": depth,
                "org_unit_id": str(unit.id) if unit else None,
                "org_unit_name": unit.name if unit else None,
                "courses": counts.get((r.canvas_integration_id, r.account_id), 0),
                "refreshed_at": r.refreshed_at.isoformat(),
            }
        )
    return out


# ---- linking ---------------------------------------------------------------------------------


def _accounts(db: Session, integration_id: uuid.UUID) -> dict[str, CanvasAccount]:
    return {
        r.account_id: r
        for r in db.scalars(
            select(CanvasAccount).where(CanvasAccount.canvas_integration_id == integration_id)
        )
    }


def _linked_unit(
    accounts: dict[str, CanvasAccount], account_id: str | None, db: Session
) -> uuid.UUID | None:
    """The area of the nearest linked account at or above ``account_id``."""
    for _ in range(MAX_DEPTH):
        row = accounts.get(account_id) if account_id else None
        if row is None:
            return None
        if row.org_unit_id is not None:
            unit = db.get(OrgUnit, row.org_unit_id)
            if unit is not None and unit.status == "active":
                return unit.id
        account_id = row.parent_account_id
    return None


def place_course(db: Session, course: Course) -> bool:
    """Put an unplaced course in the area of its nearest linked sub-account."""
    if course.org_unit_id is not None or not course.canvas_account_id:
        return False
    unit_id = _linked_unit(
        _accounts(db, course.canvas_integration_id), course.canvas_account_id, db
    )
    if unit_id is None:
        return False
    course.org_unit_id = unit_id
    audit.record(
        db,
        action="course.org_unit",
        resource_type="course",
        resource_id=course.id,
        institution_id=course.institution_id,
        actor_kind="system",
        data={"from": None, "to": str(unit_id), "via": "canvas_account"},
    )
    return True


def link(
    db: Session,
    actor: authz.Actor,
    items: list[dict[str, Any]],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Link sub-accounts to areas, creating an area for each unless one is named.

    ``items``: ``{"id", "org_unit_id"?, "kind"?}``. Rows are handled parents first, so a
    faculty and its departments ticked together nest correctly.
    """
    authz.require_inst_admin(actor)
    if not items:
        raise Invalid("NOTHING_SELECTED", "Tick at least one sub-account.")
    wanted: dict[uuid.UUID, dict[str, Any]] = {}
    for item in items:
        row = db.get(CanvasAccount, item["id"])
        if row is None:
            raise NotFound("CANVAS_ACCOUNT_NOT_FOUND", "No such Canvas sub-account.")
        wanted[row.id] = item
    ordered = [r for r, _ in _ordered(db.scalars(select(CanvasAccount))) if r.id in wanted]
    linked = 0
    integrations = set()
    for row in ordered:
        item = wanted[row.id]
        integrations.add(row.canvas_integration_id)
        unit_id = item.get("org_unit_id")
        if unit_id is not None:
            if db.get(OrgUnit, unit_id) is None:
                raise NotFound("ORG_UNIT_NOT_FOUND", "No such area.")
        elif row.org_unit_id is not None:
            continue  # already linked; nothing to create
        else:
            accounts = _accounts(db, row.canvas_integration_id)
            parent = _linked_unit(accounts, row.parent_account_id, db)
            kind = item.get("kind") or ("department" if parent else "faculty")
            unit = people.create_org_unit(
                db, actor, name=row.name, kind=kind, parent_id=parent, request_id=request_id
            )
            unit_id = unit.id
        row.org_unit_id = unit_id
        db.flush()
        linked += 1
        audit.record(
            db,
            action="canvas_account.link",
            resource_type="canvas_account",
            resource_id=row.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"account_id": row.account_id, "org_unit_id": str(unit_id)},
        )
    placed = _place_existing(db, integrations)
    return {"linked": linked, "courses_placed": placed}


def _place_existing(db: Session, integration_ids: Iterable[uuid.UUID]) -> int:
    """Place courses launched before their sub-account was linked."""
    placed = 0
    for integration_id in integration_ids:
        integration = db.get(CanvasIntegration, integration_id)
        directory = _directory(integration) if integration else None
        courses = db.scalars(
            select(Course).where(
                Course.canvas_integration_id == integration_id, Course.org_unit_id.is_(None)
            )
        ).all()
        for course in courses:
            if course.canvas_account_id is None and directory is not None:
                ref = course.canvas_course_id
                if ref.startswith("lti:"):
                    continue
                try:
                    course.canvas_account_id = directory.course_account(ref)
                except LmsError:
                    continue
            if place_course(db, course):
                placed += 1
    db.flush()
    return placed


def unlink(
    db: Session, actor: authz.Actor, account_row_id: uuid.UUID, *, request_id: str | None = None
) -> None:
    """Stop placing new courses from this sub-account. The area and its courses stay."""
    authz.require_inst_admin(actor)
    row = db.get(CanvasAccount, account_row_id)
    if row is None:
        raise NotFound("CANVAS_ACCOUNT_NOT_FOUND", "No such Canvas sub-account.")
    old, row.org_unit_id = row.org_unit_id, None
    audit.record(
        db,
        action="canvas_account.unlink",
        resource_type="canvas_account",
        resource_id=row.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"account_id": row.account_id, "org_unit_id": str(old) if old else None},
    )
