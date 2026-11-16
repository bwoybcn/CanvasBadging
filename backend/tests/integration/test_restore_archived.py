# SPDX-License-Identifier: AGPL-3.0-or-later
"""Restoring an archived badge (product review, 14 Nov 2026).

Archive used to be one click with no way back: an archived badge could not be published again
or given a new version. ``POST /api/v1/achievements/{id}/restore`` undoes it. The published
version goes live again as it was, so nothing needs a new review, and a newer version that was
in progress comes back as a draft.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.world import World, build_world

pytestmark = pytest.mark.db

RULES: dict[str, Any] = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    w = build_world(client)
    with registry.override(w.lms):
        yield w


def _state(world: World, did: str) -> dict[str, Any]:
    r = world.get("lecturer", f"/api/v1/achievements/{did}")
    assert r.status_code == 200, r.text
    return r.json()


def _awardable(world: World) -> set[str]:
    r = world.get("lecturer", "/api/v1/achievements?awardable=true")
    assert r.status_code == 200, r.text
    return {b["id"] for b in r.json()["items"]}


def test_an_archived_badge_goes_live_again_as_it_was(world: World, signer_available: bool) -> None:
    if not signer_available:
        pytest.skip("signer not running")
    d = world.publish(RULES)
    did, version = d["id"], d["live_version_id"]
    assert did in _awardable(world)

    assert world.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code == 200
    archived = _state(world, did)
    assert archived["state"] == "archived" and archived["live_version_id"] is None
    assert did not in _awardable(world)

    r = world.post("lecturer", f"/api/v1/achievements/{did}/restore")
    assert r.status_code == 200, r.text
    restored = r.json()
    assert restored["state"] == "published"
    # The same published version, not a new one: nothing to review again.
    assert restored["live_version_id"] == version
    assert restored["working_version"]["id"] == version
    assert did in _awardable(world)
    # Learners are evaluated again, as after publishing: an evaluation of the course is waiting.
    assert any(j["status"] == "todo" for j in world.jobs("oc:evaluate_course"))
    log = world.get("admin", "/api/v1/admin/audit?limit=500").json()["items"]
    assert {"achievement.archive", "achievement.restore"} <= {e["action"] for e in log}


def test_a_version_in_progress_comes_back_as_a_draft(world: World, signer_available: bool) -> None:
    if not signer_available:
        pytest.skip("signer not running")
    d = world.publish(RULES)
    did, live = d["id"], d["live_version_id"]
    assert world.post("lecturer", f"/api/v1/achievements/{did}/new-version").status_code == 200
    assert world.post("lecturer", f"/api/v1/achievements/{did}/submit").status_code == 200
    assert _state(world, did)["state"] == "in_review"
    assert world.post("reviewer", f"/api/v1/achievements/{did}/archive").status_code == 200

    r = world.post("reviewer", f"/api/v1/achievements/{did}/restore")
    assert r.status_code == 200, r.text
    restored = r.json()
    # Version 1 is live again; version 2 must be submitted again before it can replace it.
    assert restored["state"] == "draft"
    assert restored["live_version_id"] == live
    assert restored["working_version"]["version_no"] == 2
    assert did in _awardable(world)
    assert world.post("lecturer", f"/api/v1/achievements/{did}/publish").status_code == 409


def test_only_archived_badges_and_only_their_staff(world: World, signer_available: bool) -> None:
    if not signer_available:
        pytest.skip("signer not running")
    d = world.publish(RULES)
    did = d["id"]
    r = world.post("lecturer", f"/api/v1/achievements/{did}/restore")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE"
    assert world.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code == 200
    assert world.post("s1", f"/api/v1/achievements/{did}/restore").status_code in (403, 404)
    assert world.post("outsider", f"/api/v1/achievements/{did}/restore").status_code in (403, 404)
    assert _state(world, did)["state"] == "archived"


def test_a_badge_of_a_suspended_issuer_stays_archived(world: World, signer_available: bool) -> None:
    if not signer_available:
        pytest.skip("signer not running")
    d = world.publish(RULES)
    did = d["id"]
    assert world.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code == 200
    r = world.post(
        "admin",
        f"/api/v1/admin/issuers/{world.issuer_id}/suspend",
        {"reason": "Authority under review"},
    )
    assert r.status_code == 200, r.text
    r = world.post("lecturer", f"/api/v1/achievements/{did}/restore")
    assert r.status_code == 409 and r.json()["code"] == "ISSUER_INACTIVE"
    assert _state(world, did)["state"] == "archived"
