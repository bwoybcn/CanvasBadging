# SPDX-License-Identifier: AGPL-3.0-or-later
"""Course roster from LTI Names and Roles (spec §4.3 "use NRPS where suitable", ADR-0009).

Learners appear in OpenCredential before they ever open the tool, so lecturers see the whole
class and automatic awards can reach everyone. Course roles follow Canvas: members that NRPS no
longer lists (or lists as ``Inactive``/``Deleted``) lose their Canvas-derived course roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import CanvasIntegration, Course, Membership
from opencredential.integrations.base import LmsPermissionError
from opencredential.logging import get_logger
from opencredential.lti.claims import TEST_USER_ROLE, map_roles
from opencredential.lti.provision import (
    LTI_SOURCES,
    ErasedPerson,
    find_user,
    link_identity,
    set_course_roles,
    upsert_user,
)
from opencredential.lti.services import NrpsMember, nrps_members
from opencredential.settings import Settings

log = get_logger("lti.roster")


@dataclass(frozen=True)
class RosterResult:
    members: int
    learners: int
    staff: int
    revoked: int
    without_canvas_id: int
    #: Members left out because their data was erased here (they stay erased).
    erased_skipped: int = 0
    #: Members whose record could not be stored (for example two Canvas accounts that claim
    #: the same identifier). They are left as they were; everyone else is still refreshed.
    skipped: int = 0


def sync_roster(
    db: Session,
    settings: Settings,
    integration: CanvasIntegration,
    course: Course,
    *,
    transport: httpx.BaseTransport | None = None,
) -> RosterResult:
    if not course.lti_nrps_url:
        raise LmsPermissionError("no Names and Roles URL yet: the course has not been launched")
    # Read the whole roster first: a failure part-way must not revoke anyone.
    members = list(
        nrps_members(
            settings,
            integration,
            course.lti_nrps_url,
            resource_link_id=course.lti_resource_link_id,
            transport=transport,
        )
    )
    now = datetime.now(UTC)
    seen: set = set()
    learners = staff = no_canvas_id = revoked = erased = skipped = 0
    for m in members:
        roles = map_roles(list(m.roles)) if m.status == "Active" else set()
        try:
            # One member in a savepoint: a record that cannot be stored is undone and left
            # out, and the rest of the class is still refreshed.
            with db.begin_nested():
                user_id, gone = _store_member(db, integration, course, m, frozenset(roles), now)
        except ErasedPerson:
            # Still on the Canvas class list, but erased here: leave them out and carry on.
            erased += 1
            continue
        except (ValueError, IntegrityError) as exc:
            skipped += 1
            log.warning(
                "roster.member_skipped",
                course_id=str(course.id),
                reason=str(exc)[:200] if isinstance(exc, ValueError) else "conflict",
            )
            # Whoever this is keeps the course roles they had: a record we could not read
            # is no evidence that they left.
            known = find_user(db, integration.id, "lti_sub", m.sub) or (
                find_user(db, integration.id, "canvas_user_id", m.canvas_user_id)
                if m.canvas_user_id
                else None
            )
            if known is not None:
                seen.add(known)
            continue
        revoked += gone
        seen.add(user_id)
        learners += "student" in roles
        staff += bool(roles & {"lecturer", "course_admin"})
        no_canvas_id += m.canvas_user_id is None and "student" in roles

    # Members who left the course entirely.
    for ms in db.scalars(
        select(Membership).where(
            Membership.scope_type == "course",
            Membership.scope_id == course.id,
            Membership.revoked_at.is_(None),
            Membership.source.in_(LTI_SOURCES),
        )
    ):
        if ms.user_id not in seen:
            ms.revoked_at = now
            revoked += 1

    result = RosterResult(len(members), learners, staff, revoked, no_canvas_id, erased, skipped)
    audit.record(
        db,
        action="course.roster_synced",
        resource_type="course",
        resource_id=course.id,
        institution_id=course.institution_id,
        actor_kind="system",
        data=result.__dict__,
    )
    return result


def _store_member(
    db: Session,
    integration: CanvasIntegration,
    course: Course,
    m: NrpsMember,
    roles: frozenset[str],
    now: datetime,
) -> tuple[Any, int]:
    """Create or update one class-list member and their course roles. Returns the user id and
    how many course roles they lost."""
    user, _ = upsert_user(
        db,
        course.institution_id,
        integration.id,
        sub=m.sub,
        canvas_user_id=m.canvas_user_id,
        sis_user_id=m.sis_user_id,
        name=m.name,
        given_name=m.given_name,
        family_name=m.family_name,
        email=m.email,
        verified_by="nrps",
    )
    if TEST_USER_ROLE in m.roles and not user.is_test_user:
        # Canvas's Student View "Test Student" can appear on the class list before anyone
        # has opened the tool as them: never listed, read or awarded (as on a launch).
        user.is_test_user = True
    link_identity(
        db, course.institution_id, integration.id, user.id, "lti11_user_id", m.lti11_user_id
    )
    _, gone = set_course_roles(
        db, course.institution_id, user.id, course.id, roles, source="nrps", now=now
    )
    db.flush()
    return user.id, len(gone)
