# SPDX-License-Identifier: AGPL-3.0-or-later
"""Course roster from LTI Names and Roles (spec §4.3 "use NRPS where suitable", ADR-0009).

Learners appear in OpenCredential before they ever open the tool, so lecturers see the whole
class and automatic awards can reach everyone. Course roles follow Canvas: members that NRPS no
longer lists (or lists as ``Inactive``/``Deleted``) lose their Canvas-derived course roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import CanvasIntegration, Course, Membership
from opencredential.integrations.base import LmsPermissionError
from opencredential.lti.claims import map_roles
from opencredential.lti.provision import LTI_SOURCES, link_identity, set_course_roles, upsert_user
from opencredential.lti.services import nrps_members
from opencredential.settings import Settings


@dataclass(frozen=True)
class RosterResult:
    members: int
    learners: int
    staff: int
    revoked: int
    without_canvas_id: int


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
    learners = staff = no_canvas_id = revoked = 0
    for m in members:
        roles = map_roles(list(m.roles)) if m.status == "Active" else set()
        user, _ = upsert_user(
            db,
            course.institution_id,
            integration.id,
            sub=m.sub,
            canvas_user_id=m.canvas_user_id,
            name=m.name,
            given_name=m.given_name,
            family_name=m.family_name,
            email=m.email,
            verified_by="nrps",
        )
        link_identity(
            db, course.institution_id, integration.id, user.id, "lti11_user_id", m.lti11_user_id
        )
        _, gone = set_course_roles(
            db, course.institution_id, user.id, course.id, frozenset(roles), source="nrps", now=now
        )
        revoked += len(gone)
        seen.add(user.id)
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

    result = RosterResult(len(members), learners, staff, revoked, no_canvas_id)
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
