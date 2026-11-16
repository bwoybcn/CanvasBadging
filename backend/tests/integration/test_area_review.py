# SPDX-License-Identifier: AGPL-3.0-or-later
"""Colleague review set per area and per badge (migration 0009).

The institution sets a default review mode; a faculty, department or service can override it
for itself and the units below it; the author chooses where their area lets them. Badges that
claim assessed proficiency or use credit wording always need review. Named reviewers can be
given the ``reviewer`` role for an area. Second approval of manual awards follows the area too.
"""

from __future__ import annotations

import uuid
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
from tests.integration.world import CHECKLIST, World, build_world

pytestmark = pytest.mark.db

MANUAL_RULES = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}


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
        # Relaxing review per area is off by default; most tests here are about areas that do.
        r = w.patch(
            "admin", "/api/v1/institutions/current/policy", {"areas_may_relax_review": True}
        )
        assert r.status_code == 200, r.text
        yield w


def _library(world: World) -> str:
    """The world's course and issuer both sit in the Library unit."""
    units = world.get("admin", "/api/v1/admin/org-units").json()
    return str(next(u["id"] for u in units if u["name"] == "Library"))


def _set_area(world: World, unit_id: str, who: str = "admin", **review: Any) -> Any:
    return world.patch(who, f"/api/v1/admin/org-units/{unit_id}", {"review_policy": review})


def _submit(world: World, did: str, review: str | None = None, who: str = "lecturer") -> Any:
    body = {"review": review} if review else None
    return world.post(who, f"/api/v1/achievements/{did}/submit", body)


def _badge(world: World, **fields: Any) -> dict[str, Any]:
    return world.draft(
        MANUAL_RULES,
        title=fields.pop("title", "Volunteering: 10 hours"),
        category="Participation",
        demonstration_kind=fields.pop("demonstration_kind", "participating"),
        award_policy="manual",
        **fields,
    )


def test_institution_default_requires_review(world: World) -> None:
    d = _badge(world)
    assert d["review"]["mode"] == "required" and d["review"]["set_by_org_unit_id"] is None
    r = _submit(world, d["id"], "skip")
    assert r.status_code == 409 and r.json()["code"] == "REVIEW_REQUIRED"
    r = _submit(world, d["id"])
    assert r.status_code == 200 and r.json()["state"] == "in_review"


def test_area_switches_review_off(world: World) -> None:
    lib = _library(world)
    r = _set_area(world, lib, definition_review="not_required")
    assert r.status_code == 200, r.text
    assert r.json()["effective_review"]["definition_review"] == "not_required"
    assert r.json()["effective_review"]["sources"]["definition_review"] == lib

    d = _badge(world)
    assert d["review"] == {
        "mode": "not_required",
        "area_mode": "not_required",
        "forced_by": None,
        "set_by_org_unit_id": lib,
        "self_approval_allowed": False,
    }
    r = _submit(world, d["id"])
    assert r.status_code == 200 and r.json()["state"] == "approved"
    detail = world.get("lecturer", f"/api/v1/achievements/{d['id']}").json()
    assert detail["reviews"][-1]["without_review"] is True
    assert world.post("lecturer", f"/api/v1/achievements/{d['id']}/publish").status_code == 200

    # Admins can find live badges nobody else checked, with what review would be now.
    _set_area(world, lib, definition_review="required")
    rows = world.get("reviewer", "/api/v1/admin/review/published-without-review").json()
    assert [(x["id"], x["review_now"], x["area"]) for x in rows] == [
        (d["id"], "required", "Library")
    ]
    assert world.get("lecturer", "/api/v1/admin/review/published-without-review").status_code == (
        403
    )
    # Tightening review later does not unpublish anything.
    assert world.get("lecturer", f"/api/v1/achievements/{d['id']}").json()["state"] == ("published")


def test_author_decides(world: World) -> None:
    _set_area(world, _library(world), definition_review="author_decides")
    asks = _badge(world, title="Library workshop: Referencing")
    r = _submit(world, asks["id"])  # no choice means "ask a colleague"
    assert r.json()["state"] == "in_review"
    skips = _badge(world, title="Library workshop: Finding sources")
    r = _submit(world, skips["id"], "skip")
    assert r.json()["state"] == "approved"
    with world.db() as db:
        review = db.scalar(
            select(m.DefinitionReview).where(
                m.DefinitionReview.definition_id == uuid.UUID(skips["id"])
            )
        )
        assert review is not None and review.without_review
        assert review.comment and "author chose" in review.comment
        submit_event = db.scalars(
            select(m.AuditEvent)
            .where(m.AuditEvent.action == "achievement.submit")
            .order_by(m.AuditEvent.at.desc())
        ).first()
        assert submit_event is not None
        assert submit_event.data["review"] == "skipped"


@pytest.mark.parametrize(
    ("fields", "forced_by"),
    [
        ({"demonstration_kind": "assessed"}, "assessed"),
        ({"description": "Worth 10 CATS credits towards your degree."}, "credit"),
    ],
)
def test_safeguard_always_requires_review(
    world: World, fields: dict[str, Any], forced_by: str
) -> None:
    _set_area(world, _library(world), definition_review="not_required")
    d = _badge(world, **fields)
    assert d["review"]["mode"] == "required" and d["review"]["forced_by"] == forced_by
    assert d["review"]["area_mode"] == "not_required"
    r = _submit(world, d["id"], "skip")
    assert r.status_code == 409 and r.json()["code"] == "REVIEW_REQUIRED"
    assert _submit(world, d["id"]).json()["state"] == "in_review"


def test_areas_inherit_and_nearest_setting_wins(world: World) -> None:
    faculty = world.post(
        "admin", "/api/v1/admin/org-units", {"name": "Faculty of HSS", "kind": "faculty"}
    ).json()
    lib = _library(world)
    r = world.patch("admin", f"/api/v1/admin/org-units/{lib}", {"parent_id": faculty["id"]})
    assert r.status_code == 200, r.text
    _set_area(world, faculty["id"], definition_review="author_decides")
    assert _badge(world)["review"]["mode"] == "author_decides"
    assert _badge(world)["review"]["set_by_org_unit_id"] == faculty["id"]

    # The Library sets its own; a null clears it and the faculty's applies again.
    _set_area(world, lib, definition_review="not_required")
    assert _badge(world)["review"]["mode"] == "not_required"
    r = _set_area(world, lib, definition_review=None)
    assert r.json()["review_policy"] == {}
    assert _badge(world)["review"]["mode"] == "author_decides"


def test_areas_cannot_relax_review_by_default(client: TestClient) -> None:
    """Gary's decision, 14 Nov 2026: institutions opt in to letting areas relax review."""
    w = build_world(client)
    with registry.override(w.lms):
        policy = w.get("admin", "/api/v1/institutions/current/policy").json()
        assert policy["areas_may_relax_review"] is False
        r = _set_area(w, _library(w), definition_review="not_required")
        assert r.status_code == 403 and r.json()["code"] == "REVIEW_RELAX_NOT_ALLOWED"


def test_institution_can_stop_areas_relaxing_review(world: World) -> None:
    policy = {"areas_may_relax_review": False}
    r = world.patch("admin", "/api/v1/institutions/current/policy", policy)
    assert r.status_code == 200 and r.json()["areas_may_relax_review"] is False
    lib = _library(world)
    r = _set_area(world, lib, definition_review="not_required")
    assert r.status_code == 403 and r.json()["code"] == "REVIEW_RELAX_NOT_ALLOWED"
    r = _set_area(world, lib, manual_awards_require_second_approval=True)  # stricter is fine
    assert r.status_code == 200, r.text
    # Even an override stored earlier is ignored once relaxing is switched off.
    with world.db() as db:
        unit = db.get(m.OrgUnit, uuid.UUID(lib))
        assert unit is not None
        unit.review_policy = {**unit.review_policy, "definition_review": "not_required"}
    assert _badge(world)["review"]["mode"] == "required"


def test_department_admin_sets_own_area_but_not_others(world: World) -> None:
    lib = _library(world)
    other = world.post(
        "admin", "/api/v1/admin/org-units", {"name": "Careers", "kind": "other"}
    ).json()
    assert _set_area(world, lib, "reviewer", definition_review="author_decides").status_code == 200
    r = _set_area(world, other["id"], "reviewer", definition_review="not_required")
    assert r.status_code == 403
    assert _set_area(world, lib, "lecturer", definition_review="not_required").status_code == 403
    r = _set_area(world, lib, definition_review="sometimes")
    assert r.status_code == 422 and r.json()["code"] == "REVIEW_POLICY_INVALID"
    r = _set_area(world, lib, approver_roles=["lecturer"])
    assert r.status_code == 422 and r.json()["code"] == "REVIEW_POLICY_INVALID"


def test_named_reviewer_role(world: World) -> None:
    lib = _library(world)
    librarian = world.users["outsider"]
    r = world.post(
        "reviewer",  # a department administrator can name reviewers in their area
        "/api/v1/admin/memberships",
        {"user_id": str(librarian), "role": "reviewer", "scope_type": "org_unit", "scope_id": lib},
    )
    assert r.status_code == 201, r.text
    d = _badge(world)
    _submit(world, d["id"])
    queue = world.get("outsider", "/api/v1/achievements", params={"review_queue": True}).json()
    assert [i["id"] for i in queue["items"]] == [d["id"]]
    detail = world.get("outsider", f"/api/v1/achievements/{d['id']}").json()
    assert detail["can_review"] is True and detail["can_edit"] is False
    # The profile tells the screens to offer the Review queue, although this person holds no
    # staff role at all (they were once shown "This page is for course staff" instead).
    me = world.get("outsider", "/api/v1/learners/me").json()
    assert me["may_review"] is True
    assert {x["role"] for x in me["memberships"]} == {"reviewer"}
    r = world.post("outsider", f"/api/v1/achievements/{d['id']}/approve", {"checklist": CHECKLIST})
    assert r.status_code == 200 and r.json()["state"] == "approved"

    # The role is scoped: a badge in another area is not theirs to review.
    assert (
        world.post(
            "reviewer",
            "/api/v1/admin/memberships",
            {
                "user_id": str(librarian),
                "role": "reviewer",
                "scope_type": "course",
                "scope_id": lib,
            },
        ).json()["code"]
        == "SCOPE_INVALID"
    )


def test_self_approval_is_set_per_area(world: World) -> None:
    lib = _library(world)
    body = {
        "issuer_id": str(world.issuer_id),
        "course_id": str(world.course_id),
        "fields": {
            "title": "Library volunteer",
            "short_description": "Helped run library induction sessions.",
            "learning_outcomes": ["Explain library services to new students"],
            "criteria_narrative": "Volunteer at two induction sessions.",
            "category": "Participation",
            "demonstration_kind": "participating",
            "asset_id": world.artwork("reviewer"),
            "award_policy": "manual",
        },
        "rules": MANUAL_RULES,
    }
    r = world.post("reviewer", "/api/v1/achievements", body)  # the department admin authors it
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert _submit(world, did, who="reviewer").json()["state"] == "in_review"
    r = world.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
    assert r.status_code == 403 and r.json()["code"] == "SELF_APPROVAL_NOT_ALLOWED"

    _set_area(world, lib, self_approval_allowed=True)  # a sole member of staff in this area
    assert world.get("reviewer", f"/api/v1/achievements/{did}").json()["can_review"] is True
    r = world.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
    assert r.status_code == 200, r.text


def test_second_approval_of_manual_awards_follows_the_area(world: World) -> None:
    did = world.publish(
        MANUAL_RULES,
        title="WP Volunteer",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )["id"]
    award = {
        "definition_id": did,
        "user_id": str(world.users["s1"]),
        "justification": "Logged 10 hours on the widening participation scheme.",
    }
    _set_area(world, _library(world), manual_awards_require_second_approval=True)
    r = world.post("lecturer", "/api/v1/awards/manual", award)
    assert r.status_code == 201 and r.json()["status"] == "awaiting_confirmation"

    _set_area(world, _library(world), manual_awards_require_second_approval=False)
    award["user_id"] = str(world.users["s2"])
    r = world.post("lecturer", "/api/v1/awards/manual", award)
    assert r.status_code == 201 and r.json()["status"] == "ready"


def test_institution_review_mode_and_old_switch_stay_in_step(world: World) -> None:
    path = "/api/v1/institutions/current/policy"
    p = world.get("admin", path).json()
    assert (p["definition_review"], p["definitions_require_approval"]) == ("required", True)
    p = world.patch("admin", path, {"definition_review": "author_decides"}).json()
    assert (p["definition_review"], p["definitions_require_approval"]) == ("author_decides", True)
    assert _badge(world)["review"]["mode"] == "author_decides"
    p = world.patch("admin", path, {"definitions_require_approval": False}).json()
    assert (p["definition_review"], p["definitions_require_approval"]) == ("not_required", False)
    assert world.patch("reviewer", path, {"definition_review": "required"}).status_code == 403


# ---- review 14 Nov 2026: findings 6 and 9 ---------------------------------------------------

UNREVIEWED = "/api/v1/admin/review/published-without-review"


def test_unreviewed_list_uses_the_latest_approval_and_live_drafts(world: World) -> None:
    lib = _library(world)
    _set_area(world, lib, definition_review="not_required")
    checked = _badge(world, title="Volunteering: checked later")
    assert _submit(world, checked["id"]).json()["state"] == "approved"
    # A reviewer sends the auto-approved badge back; it is then reviewed properly.
    r = world.post(
        "reviewer", f"/api/v1/achievements/{checked['id']}/reject", {"comment": "Add the hours"}
    )
    assert r.status_code == 200, r.text
    _set_area(world, lib, definition_review="required")
    assert _submit(world, checked["id"]).json()["state"] == "in_review"
    r = world.post(
        "reviewer", f"/api/v1/achievements/{checked['id']}/approve", {"checklist": CHECKLIST}
    )
    assert r.status_code == 200, r.text
    assert (
        world.post("lecturer", f"/api/v1/achievements/{checked['id']}/publish").status_code == 200
    )

    _set_area(world, lib, definition_review="not_required")
    live = _badge(world, title="Volunteering: never checked")
    _submit(world, live["id"])
    assert world.post("lecturer", f"/api/v1/achievements/{live['id']}/publish").status_code == 200
    # Starting a new draft leaves the unreviewed version live, so it stays on the list.
    assert (
        world.post("lecturer", f"/api/v1/achievements/{live['id']}/new-version").status_code == 200
    )

    rows = world.get("reviewer", UNREVIEWED).json()
    assert [x["id"] for x in rows] == [live["id"]]


def test_asking_for_review_is_honoured_where_none_is_needed(world: World) -> None:
    _set_area(world, _library(world), definition_review="not_required")
    d = _badge(world)
    r = _submit(world, d["id"], "colleague")
    assert r.status_code == 200 and r.json()["state"] == "in_review"


def test_profile_says_who_is_offered_the_review_queue(world: World) -> None:
    """``may_review`` follows the institution's approver roles, so the menu matches what the
    server will allow (product recommendation 1: lecturers who approve get the link too)."""

    def may(who: str) -> bool:
        return bool(world.get(who, "/api/v1/learners/me").json()["may_review"])

    assert (may("admin"), may("reviewer"), may("lecturer"), may("s1")) == (
        True,
        True,
        False,
        False,
    )
    r = world.patch(
        "admin",
        "/api/v1/institutions/current/policy",
        {"approver_roles": ["lecturer", "dept_admin", "inst_admin"]},
    )
    assert r.status_code == 200, r.text
    assert (may("lecturer"), may("s1")) == (True, False)
