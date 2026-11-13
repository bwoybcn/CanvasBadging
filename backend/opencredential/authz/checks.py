# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal role checks for W4's privileged actions (ADR-0013; W7 generalises them).

* Revocation: roles listed in the institution policy ``revokers`` (default ``inst_admin`` and
  ``dept_admin``). ``inst_admin`` holds at institution scope; ``dept_admin`` only for issuers in
  their org unit.
* Key management: ``inst_admin`` at institution scope only.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.api.errors import ApiError
from opencredential.db.models import Institution, Issuer, Membership


def _roles(db: Session, user_id: uuid.UUID) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.revoked_at.is_(None))
        )
    )


def holds(
    db: Session, user_id: uuid.UUID, roles: Iterable[str], *, issuer: Issuer | None = None
) -> bool:
    wanted = set(roles)
    for m in _roles(db, user_id):
        if m.role not in wanted:
            continue
        if m.scope_type == "institution":
            return True
        if issuer is not None and m.scope_type == "org_unit" and m.scope_id == issuer.org_unit_id:
            return True
        if issuer is not None and m.scope_type == "issuer" and m.scope_id == issuer.id:
            return True
    return False


def require_revoker(db: Session, user_id: uuid.UUID, issuer: Issuer) -> None:
    institution = db.get(Institution, issuer.institution_id)
    revokers = (institution.policy or {}).get("revokers") if institution else None
    if not holds(db, user_id, revokers or ["inst_admin"], issuer=issuer):
        raise ApiError(403, "FORBIDDEN", "You are not allowed to revoke this credential")


def require_key_manager(db: Session, user_id: uuid.UUID) -> None:
    if not holds(db, user_id, ["inst_admin"]):
        raise ApiError(403, "FORBIDDEN", "Only institutional administrators can manage keys")
