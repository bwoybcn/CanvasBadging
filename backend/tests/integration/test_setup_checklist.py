# SPDX-License-Identifier: AGPL-3.0-or-later
"""The administrator's setup checklist (product review recommendation 13).

A new institution starts with nothing done. Each step is ticked by the thing it describes
actually being true, in any order, and only institution administrators can read it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.governance.institution import set_verification_host
from opencredential.settings import get_settings

pytestmark = pytest.mark.db

BASIS = "Senate resolution S/2026/14: the Library may award study-skills badges"
KEYS = ["canvas", "address", "area", "issuer", "authorised", "delegated"]


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


class Fresh:
    """An institution with one administrator, one lecturer and nothing else."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        suffix = uuid.uuid4().hex[:8]
        self.suffix = suffix
        with owner_session() as db:
            inst = m.Institution(slug=f"setup-{suffix}", name="Setup University", is_demo=False)
            db.add(inst)
            db.flush()
            admin = m.User(institution_id=inst.id, display_name="Ada Admin", email="ada@x.test")
            lecturer = m.User(institution_id=inst.id, display_name="Lee Lecturer")
            db.add_all([admin, lecturer])
            db.flush()
            db.add(
                m.Membership(
                    institution_id=inst.id,
                    user_id=admin.id,
                    scope_type="institution",
                    scope_id=inst.id,
                    role="inst_admin",
                    source="dev_seed",
                )
            )
            self.iid, self.admin, self.lecturer = inst.id, admin.id, lecturer.id

    def h(self, user_id: uuid.UUID) -> dict[str, str]:
        token, _ = sessions.issue(
            get_settings(), user_id=user_id, institution_id=self.iid, method="dev"
        )
        return {"authorization": f"Bearer {token}"}

    def setup(self) -> dict[str, Any]:
        r = self.client.get("/api/v1/admin/setup", headers=self.h(self.admin))
        assert r.status_code == 200, r.text
        return dict(r.json())

    def done(self) -> dict[str, bool]:
        return {s["key"]: s["done"] for s in self.setup()["steps"]}

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.client.post(path, json=body, headers=self.h(self.admin))
        assert r.status_code in (200, 201), r.text
        return dict(r.json())


def test_a_new_institution_has_nothing_ticked_and_is_told_what_to_do(client: TestClient) -> None:
    f = Fresh(client)
    out = f.setup()
    assert [s["key"] for s in out["steps"]] == KEYS
    assert (out["done"], out["total"], out["complete"], out["next"]) == (0, 6, False, "canvas")
    steps = {s["key"]: s for s in out["steps"]}
    # The first two are the operator's, and say so instead of linking to a page.
    for key in ("canvas", "address"):
        assert steps[key]["operator"] is True and steps[key]["to"] is None
        assert "whoever runs the service" in steps[key]["detail"]
    assert "development identity" in steps["address"]["detail"]
    assert steps["area"]["to"] == "/admin/areas"
    assert steps["issuer"]["to"] == steps["delegated"]["to"] == "/admin/issuers"
    assert steps["authorised"]["detail"] == "Create an issuer first."
    assert steps["delegated"]["detail"] == "Authorise an issuer first."


def test_each_step_is_ticked_by_the_thing_itself(
    client: TestClient, signer_available: bool
) -> None:
    f = Fresh(client)

    # An area that may not issue does not count; one that may does.
    unit = f.post("/api/v1/admin/org-units", {"name": "University Library", "kind": "service"})
    r = client.patch(
        f"/api/v1/admin/org-units/{unit['id']}", json={"may_issue": False}, headers=f.h(f.admin)
    )
    assert r.status_code == 200, r.text
    steps = {s["key"]: s for s in f.setup()["steps"]}
    assert steps["area"]["done"] is False
    assert "None of your 1 areas may issue badges" in steps["area"]["detail"]
    client.patch(
        f"/api/v1/admin/org-units/{unit['id']}", json={"may_issue": True}, headers=f.h(f.admin)
    )
    steps = {s["key"]: s for s in f.setup()["steps"]}
    assert steps["area"]["done"] is True
    assert steps["area"]["detail"] == "University Library may issue badges."

    # A new issuer is not yet authorised.
    issuer = f.post(
        "/api/v1/admin/issuers",
        {
            "name": "Library Skills Centre",
            "slug": f"library-{f.suffix}",
            "level": "department",
            "org_unit_id": unit["id"],
        },
    )
    done = f.done()
    assert done["issuer"] is True and done["authorised"] is False and done["delegated"] is False
    assert f.setup()["next"] == "canvas"

    f.post(f"/api/v1/admin/issuers/{issuer['id']}/authorise", {"authority_basis": BASIS})
    steps = {s["key"]: s for s in f.setup()["steps"]}
    assert steps["authorised"]["done"] is True
    assert steps["authorised"]["detail"] == "Library Skills Centre can sign badges."
    assert steps["delegated"]["done"] is False
    assert "lecturers have no issuer to choose" in steps["delegated"]["detail"]

    f.post(
        f"/api/v1/admin/issuers/{issuer['id']}/delegations",
        {"scope_type": "org_unit", "scope_id": unit["id"]},
    )
    assert f.done()["delegated"] is True

    # The operator's two steps.
    with owner_session() as db:
        inst = db.get(m.Institution, f.iid)
        assert inst is not None
        set_verification_host(db, inst, f"badges-{f.suffix}.example.ac.uk")
        integration = m.CanvasIntegration(
            id=uuid.uuid4(),
            institution_id=f.iid,
            name="Canvas",
            base_url="https://canvas.example.ac.uk",
            lti_issuer="https://canvas.instructure.com",
            lti_client_id=f"1000{f.suffix}",
            status="active",
        )
        db.add(integration)
        db.flush()
    steps = {s["key"]: s for s in f.setup()["steps"]}
    assert steps["address"]["done"] is True
    assert steps["address"]["detail"] == f"Badges are checked at badges-{f.suffix}.example.ac.uk."
    # Registered but not yet allowed to read Canvas: still to do, and it says which half is missing.
    assert steps["canvas"]["done"] is False
    assert "cannot read Canvas yet" in steps["canvas"]["detail"]
    with owner_session() as db:
        db.add(
            m.CanvasToken(
                institution_id=f.iid,
                canvas_integration_id=integration.id,
                purpose="integration_account",
                access_token_enc=b"sealed",
                scopes=[],
            )
        )
    out = f.setup()
    assert all(s["done"] for s in out["steps"])
    assert (out["done"], out["complete"], out["next"]) == (6, True, None)

    # Taking a step away unticks it: a suspended issuer can no longer sign.
    f.post(f"/api/v1/admin/issuers/{issuer['id']}/suspend", {"reason": "Paused for review"})
    done = f.done()
    assert done["issuer"] is True and done["authorised"] is False and done["delegated"] is False


def test_only_institution_administrators_see_the_checklist(client: TestClient) -> None:
    f = Fresh(client)
    assert client.get("/api/v1/admin/setup", headers=f.h(f.lecturer)).status_code == 403
    assert client.get("/api/v1/admin/setup").status_code == 401
    # Another institution's administrator sees their own state, not this one's.
    f.post("/api/v1/admin/org-units", {"name": "University Library", "kind": "service"})
    other = Fresh(client)
    assert f.done()["area"] is True and other.done()["area"] is False
