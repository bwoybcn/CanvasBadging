# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link chosen Canvas sub-accounts to areas.

An administrator reads the sub-account tree from Canvas and ticks the ones that should be areas.
Ticked sub-accounts become areas nested like Canvas, existing courses in them join, and new
courses join on their first launch. Unticked sub-accounts (sandboxes, terms) are ignored.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import tenant_session
from opencredential.integrations import registry
from opencredential.integrations.base import AccountRecord
from opencredential.lti import provision
from opencredential.lti.claims import LaunchData
from opencredential.settings import get_settings
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db

TREE = [
    AccountRecord("1", "University of Liverpool", None),
    AccountRecord("2", "Faculty of Science", "1"),
    AccountRecord("3", "Chemistry", "2"),
    AccountRecord("4", "University Library", "1"),
    AccountRecord("5", "Sandboxes", "1"),
    # Canvas's internal account: never offered.
    AccountRecord("9", "Site Admin", None),
]


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def _course(w: World, ref: str, account: str | None = None) -> uuid.UUID:
    with tenant_session(w.iid) as db:
        integration = db.scalar(select(m.CanvasIntegration))
        assert integration is not None
        course = m.Course(
            institution_id=w.iid,
            canvas_integration_id=integration.id,
            canvas_course_id=ref,
            title=f"Course {ref}",
            canvas_account_id=account,
        )
        db.add(course)
        db.flush()
        return course.id


def _launch(context: str, course_ref: str, account: str) -> LaunchData:
    return LaunchData(
        issuer="",
        client_id="c",
        deployment_id="d",
        subject="sub",
        roles=(),
        course_roles=frozenset({"lecturer"}),
        context_id=context,
        context_title="Organic Chemistry",
        context_label=None,
        resource_link_id="rl",
        canvas_course_id=course_ref,
        canvas_account_id=account,
        canvas_user_id=None,
        sis_user_id=None,
        name=None,
        given_name=None,
        family_name=None,
        email=None,
        nrps_url=None,
        is_test_user=False,
        target_link_uri="https://tool.example/lti/launch",
    )


def test_link_chosen_sub_accounts(client: TestClient) -> None:
    w = build_world(client)
    w.lms.accounts = list(TREE)
    w.lms.course_accounts["202"] = "3"
    old = _course(w, "202")  # launched before anything was linked; account read from Canvas

    with registry.override(w.lms):
        assert w.post("lecturer", "/api/v1/admin/canvas-accounts/refresh").status_code == 403
        r = w.post("admin", "/api/v1/admin/canvas-accounts/refresh")
        assert r.status_code == 200, r.text
        assert r.json() == {"accounts": 5}

        rows = w.get("admin", "/api/v1/admin/canvas-accounts").json()
        assert [(x["name"], x["depth"]) for x in rows] == [
            ("University of Liverpool", 0),
            ("Faculty of Science", 1),
            ("Chemistry", 2),
            ("Sandboxes", 1),
            ("University Library", 1),
        ]
        ids = {x["name"]: x["id"] for x in rows}

        # Tick the faculty and its department together (children listed first on purpose),
        # and the Library as a service.
        r = w.post(
            "admin",
            "/api/v1/admin/canvas-accounts/link",
            {
                "items": [
                    {"id": ids["Chemistry"]},
                    {"id": ids["Faculty of Science"]},
                    {"id": ids["University Library"], "kind": "service"},
                ]
            },
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"linked": 3, "courses_placed": 1, "courses_queued": 0}

    with tenant_session(w.iid) as db:
        units = {u.name: u for u in db.scalars(select(m.OrgUnit))}
        science, chemistry, library = (
            units["Faculty of Science"],
            units["Chemistry"],
            units["University Library"],
        )
        assert (science.kind, science.parent_id) == ("faculty", None)
        assert (chemistry.kind, chemistry.parent_id) == ("department", science.id)
        assert (library.kind, library.parent_id) == ("service", None)
        placed = db.get(m.Course, old)
        assert placed is not None
        assert (placed.org_unit_id, placed.canvas_account_id) == (chemistry.id, "3")

        # A new course launched in a sub-account below a linked one joins the nearest area.
        integration = db.scalar(select(m.CanvasIntegration))
        assert integration is not None
        course, created = provision.upsert_course(
            db, w.iid, integration.id, _launch("ctx-new", "303", "3")
        )
        assert created and course.org_unit_id == chemistry.id
        course, _ = provision.upsert_course(
            db, w.iid, integration.id, _launch("ctx-sand", "404", "5")
        )
        assert course.org_unit_id is None  # Sandboxes is not linked; the root is not either

        # A course already in an area is never moved.
        course, _ = provision.upsert_course(
            db, w.iid, integration.id, _launch("ctx-new", "303", "4")
        )
        assert course.org_unit_id == chemistry.id

    rows = {x["name"]: x for x in w.get("admin", "/api/v1/admin/canvas-accounts").json()}
    assert rows["Chemistry"]["org_unit_name"] == "Chemistry"
    assert rows["Chemistry"]["courses"] == 1  # course 303 now says account 4

    # Unlinking stops new placements but keeps the area.
    lib = rows["University Library"]["id"]
    assert w.delete("admin", f"/api/v1/admin/canvas-accounts/{lib}/link").status_code == 204
    rows = {x["name"]: x for x in w.get("admin", "/api/v1/admin/canvas-accounts").json()}
    assert rows["University Library"]["org_unit_id"] is None
    names = [u["name"] for u in w.get("admin", "/api/v1/admin/org-units").json()]
    assert "University Library" in names

    # Sub-accounts that disappear from Canvas are forgotten unless linked.
    w.lms.accounts = [a for a in TREE if a.account_id not in ("5", "3")]
    with registry.override(w.lms):
        assert w.post("admin", "/api/v1/admin/canvas-accounts/refresh").status_code == 200
    names = [x["name"] for x in w.get("admin", "/api/v1/admin/canvas-accounts").json()]
    assert "Sandboxes" not in names and "Chemistry" in names


def test_a_missing_scope_says_which_scopes_to_add(client: TestClient) -> None:
    from opencredential.integrations.base import LmsPermissionError

    w = build_world(client)
    w.lms.failures[("accounts",)] = LmsPermissionError("401 insufficient scopes")
    with registry.override(w.lms):
        r = w.post("admin", "/api/v1/admin/canvas-accounts/refresh")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "CANVAS_ACCOUNTS_FORBIDDEN"
    assert "url:GET|/api/v1/accounts/:account_id/sub_accounts" in body["detail"]


def test_linking_many_courses_hands_the_rest_to_a_background_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole-product review, 16 Nov 2026, finding 19: every course whose sub-account was not
    known cost one Canvas call inside the administrator's request, so linking with hundreds of
    courses timed out. The request now makes a limited number and a job finishes the rest."""
    from opencredential.governance import canvas_accounts
    from opencredential.jobs import tasks

    monkeypatch.setattr(canvas_accounts, "LOOKUPS_PER_REQUEST", 2)
    w = build_world(client)
    w.lms.accounts = list(TREE)
    courses = []
    for n in range(5):
        w.lms.course_accounts[f"30{n}"] = "3"
        courses.append(_course(w, f"30{n}"))

    def placed() -> int:
        with tenant_session(w.iid) as db:
            return sum(db.get(m.Course, c).org_unit_id is not None for c in courses)  # type: ignore[union-attr]

    with registry.override(w.lms):
        w.post("admin", "/api/v1/admin/canvas-accounts/refresh")
        rows = {x["name"]: x for x in w.get("admin", "/api/v1/admin/canvas-accounts").json()}
        r = w.post(
            "admin",
            "/api/v1/admin/canvas-accounts/link",
            {"items": [{"id": rows["Chemistry"]["id"]}]},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"linked": 1, "courses_placed": 2, "courses_queued": 3}
        assert placed() == 2
        lookups = [c for c in w.lms.calls if c[0] == "course_account"]
        assert len(lookups) == 2  # and no more than that while the administrator waits

        jobs = w.jobs("oc:place_courses")
        assert len(jobs) == 1 and jobs[0]["status"] == "todo"
        assert tasks.place_courses_task(str(w.iid)) == 3
    assert placed() == 5
