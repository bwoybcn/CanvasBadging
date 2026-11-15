# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge teams in shared courses (migration 0010).

In a recognition course with many staff, switching badge teams on means each badge is edited and
awarded only by its owner, its named team and administrators over the course.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from opencredential.api.app import create_app
from opencredential.authz import policy as authz
from opencredential.db import models as m
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db

MANUAL_RULES = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}
REASON = "Ran two library induction sessions for new students."


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    w = build_world(client)
    with w.db() as db:  # a second librarian teaching in the same recognition course
        u = m.User(institution_id=w.iid, display_name="Robin Librarian", family_name="Librarian")
        db.add(u)
        db.flush()
        w.users["colleague"] = u.id
        db.add(
            m.Membership(
                institution_id=w.iid,
                user_id=u.id,
                scope_type="course",
                scope_id=w.course_id,
                role="lecturer",
                source="dev_seed",
            )
        )
    with registry.override(w.lms):
        yield w


def _badge(world: World) -> str:
    return str(
        world.publish(
            MANUAL_RULES,
            title="Library volunteer",
            category="Participation",
            demonstration_kind="participating",
            award_policy="manual",
        )["id"]
    )


def _award(world: World, who: str, did: str, student: str = "s1") -> Any:
    body = {"definition_id": did, "user_id": str(world.users[student]), "justification": REASON}
    return world.post(who, "/api/v1/awards/manual", body)


def _teams(world: World, who: str, enabled: bool) -> Any:
    return world.put(who, f"/api/v1/courses/{world.course_id}/badge-teams", {"enabled": enabled})


def test_without_teams_every_course_lecturer_can_award(world: World) -> None:
    did = _badge(world)
    detail = world.get("colleague", f"/api/v1/achievements/{did}").json()
    assert detail["can_edit"] is True and detail["can_award"] is True
    assert _award(world, "colleague", did).status_code == 201


def test_teams_keep_badges_to_their_team(world: World) -> None:
    did = _badge(world)
    r = _teams(world, "colleague", True)
    assert r.status_code == 200 and r.json()["badge_teams"] is True
    courses = world.get("colleague", "/api/v1/courses").json()
    assert courses[0]["badge_teams"] is True

    # Another lecturer in the course can see the badge but not change or award it.
    detail = world.get("colleague", f"/api/v1/achievements/{did}").json()
    assert (detail["can_edit"], detail["can_award"]) == (False, False)
    assert _award(world, "colleague", did).status_code == 403
    bulk = {"definition_id": did, "identifiers": ["x"], "justification": REASON}
    assert world.post("colleague", "/api/v1/awards/bulk", bulk).status_code == 403
    assert world.post("colleague", f"/api/v1/achievements/{did}/new-version").status_code == 403
    listed = world.get("colleague", "/api/v1/achievements", params={"course_id": world.course_id})
    assert did in [i["id"] for i in listed.json()["items"]]

    # The owner adds them as an awarder: they can award, not edit.
    team = world.get("lecturer", f"/api/v1/achievements/{did}/team").json()
    assert team["enabled"] is True and team["can_manage"] is True
    assert [c["name"] for c in team["candidates"]] == ["Robin Librarian"]
    path = f"/api/v1/achievements/{did}/team/{world.users['colleague']}"
    r = world.put("lecturer", path, {"role": "awarder"})
    assert r.status_code == 200, r.text
    assert [x["role"] for x in r.json()["members"]] == ["owner", "awarder"]
    assert _award(world, "colleague", did).status_code == 201
    assert world.post("colleague", f"/api/v1/achievements/{did}/new-version").status_code == 403

    # As an editor they can start a new version too; removed, they lose both.
    assert world.put("lecturer", path, {"role": "editor"}).status_code == 200
    assert world.post("colleague", f"/api/v1/achievements/{did}/new-version").status_code == 200
    assert world.delete("lecturer", path).status_code == 200
    assert _award(world, "colleague", did, "s2").status_code == 403

    # Department administrators over the course can always award.
    assert _award(world, "reviewer", did, "s2").status_code == 201


def test_team_rules(world: World) -> None:
    did = _badge(world)
    _teams(world, "lecturer", True)
    base = f"/api/v1/achievements/{did}/team"
    r = world.put("lecturer", f"{base}/{world.users['outsider']}", {"role": "editor"})
    assert r.status_code == 422 and r.json()["code"] == "NOT_COURSE_STAFF"
    r = world.put("lecturer", f"{base}/{world.users['lecturer']}", {"role": "editor"})
    assert r.status_code == 422 and r.json()["code"] == "OWNER_ALWAYS_ON_TEAM"
    r = world.put("colleague", f"{base}/{world.users['colleague']}", {"role": "editor"})
    assert r.status_code == 403  # nobody adds themselves to someone else's badge

    # A lecturer cannot switch teams off again; an administrator over the course can.
    r = _teams(world, "colleague", False)
    assert r.status_code == 403 and r.json()["code"] == "BADGE_TEAMS_ADMIN_ONLY"
    assert _teams(world, "s1", True).status_code == 404
    assert _teams(world, "reviewer", False).json()["badge_teams"] is False
    assert _award(world, "colleague", did).status_code == 201


# ---- review 14 Nov 2026: findings 2 to 4 ----------------------------------------------------


def test_owner_removed_from_course_loses_award_rights(world: World) -> None:
    """With badge teams on, the owner needs to still be staff in the course, as with teams off."""
    did = _badge(world)
    _teams(world, "lecturer", True)
    with world.db() as db:
        for ms in db.scalars(
            select(m.Membership).where(
                m.Membership.user_id == world.users["lecturer"],
                m.Membership.scope_id == world.course_id,
            )
        ):
            ms.revoked_at = datetime.now(UTC)
    assert _award(world, "lecturer", did).status_code == 403
    bulk = {"definition_id": did, "identifiers": ["x"], "justification": REASON}
    assert world.post("lecturer", "/api/v1/awards/bulk", bulk).status_code == 403


def test_revoking_follows_badge_teams(world: World) -> None:
    """Course staff may only revoke (or ask to revoke) credentials of badges on their team."""
    did = _badge(world)
    _teams(world, "lecturer", True)
    with world.db() as db:
        definition = db.get(m.AchievementDefinition, uuid.UUID(did))
        assert definition is not None
        course = db.get(m.Course, world.course_id)
        issuer = db.get(m.Issuer, definition.issuer_id)
        assert course is not None and issuer is not None
        policy = {"revokers": ["lecturer"]}

        def may(who: str) -> bool:
            actor = authz.load_actor(db, world.users[who], world.iid)
            return authz.can_revoke(db, actor, issuer, course, policy, definition)

        assert may("lecturer") is True
        assert may("colleague") is False
        db.add(
            m.AchievementTeamMember(
                institution_id=world.iid,
                definition_id=definition.id,
                user_id=world.users["colleague"],
                role="awarder",
                added_by=world.users["lecturer"],
            )
        )
        db.flush()
        assert may("colleague") is True
        course.badge_teams = False
        db.flush()
        db.execute(
            delete(m.AchievementTeamMember).where(
                m.AchievementTeamMember.definition_id == definition.id
            )
        )
        assert may("colleague") is True  # teams off: any course staff, as before


def test_awards_list_is_not_used_up_by_other_teams_badges(world: World) -> None:
    """The team rule is applied in SQL, so ``limit`` counts only awards the caller may see."""
    theirs = _badge(world)
    mine = _badge(world)
    _teams(world, "lecturer", True)
    path = f"/api/v1/achievements/{mine}/team/{world.users['colleague']}"
    assert world.put("lecturer", path, {"role": "awarder"}).status_code == 200
    assert _award(world, "lecturer", theirs, "s1").status_code == 201  # oldest
    assert _award(world, "lecturer", mine, "s2").status_code == 201
    listed = world.get("colleague", "/api/v1/awards", params={"limit": 1, "status": ""}).json()
    assert [d["user_id"] for d in listed] == [str(world.users["s2"])]


# ---- usability follow-ups (review 14 Nov 2026, items B, C, D) --------------------------------


def test_owner_hands_a_badge_to_a_colleague(world: World) -> None:
    did = _badge(world)
    _teams(world, "lecturer", True)
    owner = f"/api/v1/achievements/{did}/owner"
    r = world.put("colleague", owner, {"user_id": str(world.users["colleague"])})
    assert r.status_code == 403  # nobody takes a badge for themselves
    r = world.put("lecturer", owner, {"user_id": str(world.users["outsider"])})
    assert r.status_code == 422 and r.json()["code"] == "NOT_COURSE_STAFF"
    r = world.put("lecturer", owner, {"user_id": str(world.users["colleague"])})
    assert r.status_code == 200, r.text
    first = r.json()["members"][0]
    assert (first["name"], first["role"]) == ("Robin Librarian", "owner")
    assert "editor" in [x["role"] for x in r.json()["members"]]  # the old owner stays on
    assert _award(world, "colleague", did).status_code == 201
    detail = world.get("lecturer", f"/api/v1/achievements/{did}").json()
    assert detail["can_edit"] is True


def test_award_picker_lists_only_live_badges_you_can_award(world: World) -> None:
    did = _badge(world)
    _teams(world, "lecturer", True)
    assert world.post("lecturer", f"/api/v1/achievements/{did}/new-version").status_code == 200
    mine = world.get("lecturer", "/api/v1/achievements", params={"awardable": True}).json()
    assert [(i["id"], i["title"], i["can_award"]) for i in mine["items"]] == [
        (did, "Library volunteer", True)
    ]
    assert mine["items"][0]["course_title"]
    theirs = world.get("colleague", "/api/v1/achievements", params={"awardable": True}).json()
    assert theirs["items"] == []


def test_a_new_version_can_be_discarded_and_the_live_one_stays(world: World) -> None:
    did = _badge(world)
    url = f"/api/v1/achievements/{did}"
    live = world.get("lecturer", url).json()["live_version_id"]
    # A badge that was never superseded has nothing to discard.
    assert world.post("lecturer", f"{url}/discard-version").status_code == 409
    assert world.post("lecturer", f"{url}/new-version").status_code == 200
    draft = world.get("lecturer", url).json()
    assert draft["state"] == "draft" and draft["working_version"]["id"] != live
    assert world.post("s1", f"{url}/discard-version").status_code in (403, 404)
    r = world.post("lecturer", f"{url}/discard-version")
    assert r.status_code == 200, r.text
    back = r.json()
    assert back["state"] == "published"
    assert back["working_version"]["id"] == live == back["live_version_id"]
    assert _award(world, "lecturer", did).status_code == 201
    # A fresh version can be started again afterwards.
    assert world.post("lecturer", f"{url}/new-version").status_code == 200


def test_admin_course_list_shows_badge_teams(world: World) -> None:
    _teams(world, "lecturer", True)
    rows = world.get("admin", "/api/v1/admin/courses").json()
    assert [c["badge_teams"] for c in rows if c["id"] == str(world.course_id)] == [True]


def _remove_from_course(world: World, who: str) -> None:
    with world.db() as db:
        for ms in db.scalars(
            select(m.Membership).where(
                m.Membership.user_id == world.users[who],
                m.Membership.scope_id == world.course_id,
            )
        ):
            ms.revoked_at = datetime.now(UTC)


@pytest.mark.parametrize("teams", [False, True])
def test_owner_removed_from_course_cannot_edit(world: World, teams: bool) -> None:
    """Owning a course badge gives no rights of its own once the owner's course role has gone
    (outside review finding, 14 Nov 2026)."""
    did = _badge(world)
    _teams(world, "lecturer", teams)
    _remove_from_course(world, "lecturer")
    detail = world.get("lecturer", f"/api/v1/achievements/{did}")
    assert detail.status_code in (403, 404) or detail.json()["can_edit"] is False
    assert world.post("lecturer", f"/api/v1/achievements/{did}/new-version").status_code in (
        403,
        404,
    )
    path = f"/api/v1/achievements/{did}/team/{world.users['colleague']}"
    assert world.put("lecturer", path, {"role": "editor"}).status_code in (403, 404)
    assert world.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code in (403, 404)
    assert _award(world, "lecturer", did).status_code in (403, 404)
    # Staff still in the course carry on (with teams on, admins over the course do).
    who = "reviewer" if teams else "colleague"
    assert world.post(who, f"/api/v1/achievements/{did}/new-version").status_code == 200
