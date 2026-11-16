# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two people editing one draft do not silently overwrite each other (round 3, finding H1).

Each badge response carries a ``revision``. The editor sends it back as ``If-Match`` when it
saves; a save made from a form loaded before someone else's save is refused with 409
``DRAFT_CHANGED`` and leaves the colleague's work in place. A save without ``If-Match`` (older
API clients) still goes through as before.
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
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db


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


def _draft(world: World) -> dict[str, Any]:
    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(world.issuer_id),
            "course_id": str(world.course_id),
            "fields": {"title": "Shared draft", "short_description": "First words"},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _patch(world: World, did: str, fields: dict[str, Any], revision: str | None) -> Any:
    headers = world.h("lecturer")
    if revision is not None:
        headers["if-match"] = revision
    return world.client.patch(f"/api/v1/achievements/{did}", headers=headers, json=fields)


def _put_rules(world: World, did: str, rules: dict[str, Any], revision: str | None) -> Any:
    headers = world.h("lecturer")
    if revision is not None:
        headers["if-match"] = revision
    return world.client.put(f"/api/v1/achievements/{did}/rules", headers=headers, json=rules)


MANUAL = {
    "mode": "ALL",
    "rules": [{"type": "manual_approval", "instructions": "Staff check the portfolio."}],
}


def test_a_save_from_an_out_of_date_form_is_refused(world: World) -> None:
    d = _draft(world)
    opened = d["revision"]  # both editors open the draft now

    first = _patch(world, d["id"], {"short_description": "Colleague's words"}, opened)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] != opened

    stale = _patch(world, d["id"], {"short_description": "My words"}, opened)
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "DRAFT_CHANGED"
    assert "Someone else saved changes" in stale.json()["title"]

    now = world.get("lecturer", f"/api/v1/achievements/{d['id']}").json()
    assert now["working_version"]["short_description"] == "Colleague's words"
    assert now["revision"] == first.json()["revision"]


def test_saving_in_turn_with_the_latest_revision_works(world: World) -> None:
    d = _draft(world)
    r1 = _patch(world, d["id"], {"short_description": "Step two"}, d["revision"])
    assert r1.status_code == 200, r1.text
    r2 = _put_rules(world, d["id"], MANUAL, r1.json()["revision"])
    assert r2.status_code == 200, r2.text
    # The quoted ETag form is accepted too.
    r3 = _patch(world, d["id"], {"title": "Step three"}, f'"{r2.json()["revision"]}"')
    assert r3.status_code == 200, r3.text


def test_requirements_saved_by_a_colleague_also_count_as_a_change(world: World) -> None:
    d = _draft(world)
    opened = d["revision"]
    assert _put_rules(world, d["id"], MANUAL, opened).status_code == 200
    stale = _patch(world, d["id"], {"short_description": "Mine"}, opened)
    assert stale.status_code == 409
    stale_rules = _put_rules(world, d["id"], MANUAL, opened)
    assert stale_rules.status_code == 409
    assert stale_rules.json()["code"] == "DRAFT_CHANGED"


def test_a_save_without_if_match_still_works(world: World) -> None:
    d = _draft(world)
    first = _patch(world, d["id"], {"short_description": "Colleague"}, d["revision"])
    assert first.status_code == 200
    r = _patch(world, d["id"], {"short_description": "Script"}, None)
    assert r.status_code == 200, r.text
    assert r.json()["working_version"]["short_description"] == "Script"
