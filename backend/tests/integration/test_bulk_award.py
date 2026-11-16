# SPDX-License-Identifier: AGPL-3.0-or-later
"""Award a badge to a list of student ID numbers or emails (extracurricular badges, PR 2).

Matches each entry to a student in the badge's course, previews, then makes one manual award per
learner. Learners outside the course are never reached; identifiers never reach the audit log.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.world import World, build_world

pytestmark = pytest.mark.db

ISSUE = "oc:issue_credential"
MANUAL_RULES = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}
REASON = "Logged 10 hours on the widening participation volunteering scheme."
SIS = {"s1": "201111111", "s2": "202222222", "s3": "203333333", "outsider": "209999999"}


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    w = build_world(client)
    with w.db() as db:
        integration_id = db.scalar(select(m.CanvasIntegration.id))
        for who, sis in SIS.items():
            db.add(
                m.ExternalIdentity(
                    institution_id=w.iid,
                    canvas_integration_id=integration_id,
                    user_id=w.users[who],
                    kind="sis_user_id",
                    value=sis,
                )
            )
            user = db.get(m.User, w.users[who])
            assert user is not None
            user.email = f"{who.upper()}@Student.Example.ac.uk"
    with registry.override(w.lms):
        yield w


def _badge(world: World) -> str:
    return str(
        world.publish(
            MANUAL_RULES,
            title="WP Volunteer",
            category="Participation",
            demonstration_kind="participating",
            award_policy="manual",
        )["id"]
    )


def _bulk(world: World, did: str, ids: list[str], confirm: bool = False, **kw: Any) -> Any:
    body = {"definition_id": did, "identifiers": ids, "justification": REASON, "confirm": confirm}
    return world.post(kw.pop("who", "lecturer"), "/api/v1/awards/bulk", {**body, **kw})


def test_preview_then_award_a_list(world: World) -> None:
    did = _badge(world)
    pasted = [
        "student_id\n201111111\n202222222",  # a column copied from a spreadsheet
        "s3@student.example.ac.uk, 201111111; 209999999\t123456789",
    ]
    r = _bulk(world, did, pasted)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["committed"] is False
    assert [(x["identifier"], x["status"]) for x in preview["rows"]] == [
        ("201111111", "will_award"),
        ("202222222", "will_award"),
        ("s3@student.example.ac.uk", "will_award"),
        ("201111111", "duplicate"),
        ("209999999", "not_found"),
        ("123456789", "not_found"),
    ]
    assert preview["rows"][0]["learner_name"] == "S1"
    # Someone outside the course looks exactly like nobody: no name, no id.
    assert preview["rows"][4]["learner_name"] is None and preview["rows"][4]["user_id"] is None
    assert world.jobs(ISSUE) == []  # a preview changes nothing

    r = _bulk(world, did, pasted, confirm=True)
    result = r.json()
    assert result["counts"] == {
        "awarded": 3,
        "duplicate": 1,
        "not_found": 2,
    }
    assert len(world.jobs(ISSUE)) == 3
    with world.db() as db:
        decisions = db.scalars(select(m.AwardDecision)).all()
        assert {d.kind for d in decisions} == {"manual"}
        assert {d.justification for d in decisions} == {REASON}
        event = db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == "award.bulk"))
        assert event is not None and event.data["counts"]["awarded"] == 3
        logged = json.dumps([e.data for e in db.scalars(select(m.AuditEvent))])
        assert "201111111" not in logged and "student.example" not in logged

    # Running the list again awards nobody twice.
    again = _bulk(world, did, ["201111111", "202222222"], confirm=True).json()
    assert again["counts"] == {"already_awarded": 2}
    assert preview["second_approval"] is False
    assert len(world.jobs(ISSUE)) == 3


def test_second_approval_applies_to_list_awards(world: World) -> None:
    did = _badge(world)
    units = world.get("admin", "/api/v1/admin/org-units").json()
    lib = next(u["id"] for u in units if u["name"] == "Library")
    world.patch(
        "admin",
        f"/api/v1/admin/org-units/{lib}",
        {"review_policy": {"manual_awards_require_second_approval": True}},
    )
    result = _bulk(world, did, ["201111111"], confirm=True).json()
    assert result["counts"] == {"awaiting_confirmation": 1}
    assert world.jobs(ISSUE) == []
    preview = _bulk(world, did, ["201111111"]).json()
    assert preview["rows"][0]["status"] == "pending_confirmation"
    assert preview["second_approval"] is True


def test_list_awards_are_refused_when_they_should_be(world: World) -> None:
    did = _badge(world)
    assert _bulk(world, did, ["201111111"], who="s1").status_code == 403
    assert _bulk(world, did, ["201111111"], who="outsider").status_code == 403
    r = _bulk(world, did, ["201111111"], justification="Too short")
    assert r.status_code == 422 and r.json()["code"] == "JUSTIFICATION_REQUIRED"
    r = _bulk(world, did, [" ", ""])
    assert r.status_code == 422 and r.json()["code"] == "LIST_EMPTY"
    r = _bulk(world, did, ["\n".join(str(200000000 + i) for i in range(1001))])
    assert r.status_code == 422 and r.json()["code"] == "LIST_TOO_LONG"
    draft = world.draft(MANUAL_RULES, award_policy="manual", title="Not yet published")
    r = _bulk(world, draft["id"], ["201111111"])
    assert r.status_code == 422 and r.json()["code"] == "NOT_LIVE"


def test_list_cannot_look_up_people_outside_the_course(world: World) -> None:
    """The preview only matches the course's students: an outsider's email or student number
    reads exactly like a typo, with no name or id (review 14 Nov 2026, finding 1)."""
    did = _badge(world)
    preview = _bulk(world, did, ["outsider@student.example.ac.uk", SIS["outsider"]]).json()
    assert [(x["status"], x["learner_name"], x["user_id"]) for x in preview["rows"]] == [
        ("not_found", None, None),
        ("not_found", None, None),
    ]
