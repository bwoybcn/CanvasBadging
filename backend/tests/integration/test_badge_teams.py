# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge teams in shared courses (migration 0010).

In a recognition course with many staff, switching badge teams on means each badge is edited and
awarded only by its owner, its named team and administrators over the course.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
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
