# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas REST OAuth (integration account), token storage and refresh, and NRPS roster sync
(ADR-0009, spec §4.3). Canvas is mocked at the HTTP layer with shapes taken from the local
Canvas; the live checks are in docs/integrations/canvas.md."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential import secretbox
from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.integrations.canvas import oauth
from opencredential.lti import services
from opencredential.lti.roster import sync_roster
from opencredential.settings import get_settings

pytestmark = pytest.mark.db

BASE = "https://canvas.oc-test.example"
NRPS_URL = f"{BASE}/api/lti/courses/4/names_and_roles"
LEARNER = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
CUSTOM = "https://purl.imsglobal.org/spec/lti/claim/custom"


@pytest.fixture
def setup(database: None) -> Iterator[dict[str, Any]]:
    settings = get_settings()
    suffix = uuid.uuid4().hex[:8]
    with owner_session() as db:
        inst = m.Institution(slug=f"canvas-{suffix}", name="Canvas Access U", is_demo=False)
        db.add(inst)
        db.flush()
        integ = m.CanvasIntegration(
            id=uuid.uuid4(),
            institution_id=inst.id,
            name="Canvas",
            base_url=BASE,
            lti_issuer="https://canvas.instructure.com",
            lti_client_id=f"1000{suffix}",
            lti_token_url=f"{BASE}/login/oauth2/token",
            api_client_id="20000000000001",
            status="pending",
        )
        integ.api_client_secret_enc = secretbox.seal(
            settings, "api-secret", oauth.secret_context(integ.id)
        )
        db.add(integ)
        admin = m.User(institution_id=inst.id, display_name="Ada Admin", email="ada@x.test")
        student = m.User(institution_id=inst.id, display_name="Stu Dent")
        db.add_all([admin, student])
        db.flush()
        db.add(
            m.Membership(
                institution_id=inst.id,
                user_id=admin.id,
                scope_type="institution",
                scope_id=inst.id,
                role="inst_admin",
                source="grant",
            )
        )
        course = m.Course(
            institution_id=inst.id,
            canvas_integration_id=integ.id,
            canvas_course_id="4",
            title="Course",
            lti_nrps_url=NRPS_URL,
            lti_resource_link_id="rl-1",
        )
        db.add(course)
        db.flush()
        ids = {
            "iid": inst.id,
            "integ": integ.id,
            "admin": admin.id,
            "course": course.id,
            "student": student.id,
        }
    services.clear_token_cache()
    yield ids


def _client() -> TestClient:
    return TestClient(create_app(get_settings()))


def _auth(iid: uuid.UUID, uid: uuid.UUID) -> dict[str, str]:
    token, _ = sessions.issue(get_settings(), user_id=uid, institution_id=iid, method="dev")
    return {"authorization": f"Bearer {token}"}


def test_oauth_flow_stores_encrypted_tokens_and_never_returns_them(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client()
    # Only institution admins can start it.
    r = client.post(
        f"/api/v1/canvas/integrations/{setup['integ']}/oauth/start",
        headers=_auth(setup["iid"], setup["student"]),
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/v1/canvas/integrations/{setup['integ']}/oauth/start",
        headers=_auth(setup["iid"], setup["admin"]),
    )
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    q = parse_qs(urlsplit(url).query)
    assert url.startswith(f"{BASE}/login/oauth2/auth?")
    assert q["client_id"] == ["20000000000001"] and q["response_type"] == ["code"]
    assert "url:GET|/api/v1/users/:user_id/profile" in q["scope"][0].split(" ")

    seen: dict[str, Any] = {}

    def canvas(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        seen.update(form)
        return httpx.Response(
            200,
            json={
                "access_token": "AT-secret-1",
                "refresh_token": "RT-secret-1",
                "expires_in": 3600,
                "user": {"id": 7, "name": "OC Integration"},
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        oauth.httpx,
        "Client",
        lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(canvas)}),
    )
    cb = client.get(
        "/api/v1/canvas/oauth/callback", params={"code": "c0de", "state": q["state"][0]}
    )
    assert cb.status_code == 200 and "Canvas is connected" in cb.text
    assert seen["grant_type"] == ["authorization_code"] and seen["client_secret"] == ["api-secret"]

    with owner_session() as db:
        tok = db.scalar(
            select(m.CanvasToken).where(m.CanvasToken.canvas_integration_id == setup["integ"])
        )
        assert tok is not None and tok.canvas_user_id == "7"
        assert b"AT-secret-1" not in tok.access_token_enc
        assert b"RT-secret-1" not in (tok.refresh_token_enc or b"")
        assert db.get(m.CanvasIntegration, setup["integ"]).status == "active"  # type: ignore[union-attr]

    status = client.get("/api/v1/canvas/integrations", headers=_auth(setup["iid"], setup["admin"]))
    body = status.text
    assert status.status_code == 200 and status.json()[0]["api_connected"] is True
    assert "AT-secret" not in body and "RT-secret" not in body and "api-secret" not in body

    # The link works once.
    again = client.get(
        "/api/v1/canvas/oauth/callback", params={"code": "c0de", "state": q["state"][0]}
    )
    assert "OAUTH_STATE_REUSED" in again.text


def test_forged_oauth_state_is_refused(setup: dict[str, Any]) -> None:
    r = _client().get("/api/v1/canvas/oauth/callback", params={"code": "x", "state": "forged"})
    assert r.status_code == 400 and "OAUTH_STATE_INVALID" in r.text


def test_expiring_token_is_refreshed_server_side(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    with tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        row = oauth.store_integration_token(
            settings,
            db,
            integ,  # type: ignore[arg-type]
            {"access_token": "old", "refresh_token": "RT", "expires_in": 60},
        )
        row.expires_at = datetime.now(UTC) + timedelta(seconds=30)

    def canvas(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["RT"]
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    real_client = httpx.Client
    monkeypatch.setattr(
        oauth.httpx,
        "Client",
        lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(canvas)}),
    )
    tokens = oauth.IntegrationTokens(settings, setup["iid"], setup["integ"])
    assert tokens.get() == "new"
    assert tokens.get() == "new"  # cached until near expiry


def _nrps(members: list[dict[str, Any]], *, fail_page_2: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth2/token":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["client_credentials"]
            assert form["scope"] == [services.NRPS_SCOPE]
            return httpx.Response(200, json={"access_token": "svc", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer svc"
        assert request.headers["accept"] == services.NRPS_MEDIA_TYPE
        if request.url.params.get("page") == "2":
            if fail_page_2:
                return httpx.Response(500)
            return httpx.Response(200, json={"members": members[1:]})
        assert request.url.params["rlid"] == "rl-1"
        return httpx.Response(
            200,
            json={"members": members[:1]},
            headers={"link": f'<{NRPS_URL}?page=2>; rel="next"'},
        )

    return httpx.MockTransport(handler)


def _member(
    sub: str, name: str, roles: list[str], canvas_id: str | None, status: str = "Active"
) -> dict[str, Any]:
    msg = [{CUSTOM: {"canvas_user_id": canvas_id or "$Canvas.user.id"}}]
    return {"user_id": sub, "name": name, "roles": roles, "status": status, "message": msg}


def test_roster_sync_provisions_and_revokes(setup: dict[str, Any]) -> None:
    settings = get_settings()
    members = [
        _member("sub-t", "Tess Teacher", [INSTRUCTOR], "2"),
        _member("sub-s1", "Sam Student", [LEARNER], "4"),
        _member("sub-s2", "Sasha Student", [LEARNER], None),
    ]
    members[1]["lis_person_sourcedid"] = "201234567"  # student ID number, for list awards
    with tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        res = sync_roster(db, settings, integ, course, transport=_nrps(members))  # type: ignore[arg-type]
    assert (res.members, res.learners, res.staff, res.without_canvas_id) == (3, 2, 1, 1)

    def roles() -> dict[str, set[str]]:
        with owner_session() as db:
            out: dict[str, set[str]] = {}
            for ms, u in db.execute(
                select(m.Membership, m.User)
                .join(m.User, m.User.id == m.Membership.user_id)
                .where(m.Membership.scope_id == setup["course"], m.Membership.revoked_at.is_(None))
            ):
                out.setdefault(u.display_name or "", set()).add(ms.role)
            return out

    assert roles() == {
        "Tess Teacher": {"lecturer"},
        "Sam Student": {"student"},
        "Sasha Student": {"student"},
    }
    with owner_session() as db:
        ids = {
            (e.kind, e.value)
            for e in db.scalars(
                select(m.ExternalIdentity).where(m.ExternalIdentity.institution_id == setup["iid"])
            )
        }
    assert ("canvas_user_id", "4") in ids and ("lti_sub", "sub-s2") in ids
    assert ("sis_user_id", "201234567") in ids

    # Sam drops the course, Sasha becomes inactive.
    members2 = [
        _member("sub-t", "Tess Teacher", [INSTRUCTOR], "2"),
        _member("sub-s2", "Sasha Student", [LEARNER], None, status="Inactive"),
    ]
    with tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        sync_roster(db, settings, integ, course, transport=_nrps(members2))  # type: ignore[arg-type]
    assert roles() == {"Tess Teacher": {"lecturer"}}


def test_erased_person_is_not_brought_back_by_canvas(setup: dict[str, Any]) -> None:
    """Erasure deletes the person's Canvas identifiers, so the next class-list refresh or launch
    used to create them again, name and email included, while they were still enrolled."""
    from typer.testing import CliRunner

    from opencredential.cli import app as cli_app
    from opencredential.lti.provision import ErasedPerson, upsert_user

    settings = get_settings()
    members = [
        _member("sub-t", "Tess Teacher", [INSTRUCTOR], "2"),
        _member("sub-s1", "Sam Student", [LEARNER], "4"),
    ]
    members[1]["lis_person_sourcedid"] = "201234567"

    def refresh() -> Any:
        services.clear_token_cache()
        with tenant_session(setup["iid"]) as db:
            integ = db.get(m.CanvasIntegration, setup["integ"])
            course = db.get(m.Course, setup["course"])
            return sync_roster(db, settings, integ, course, transport=_nrps(members))  # type: ignore[arg-type]

    def people() -> dict[str | None, str]:
        with owner_session() as db:
            return {
                u.display_name: u.status
                for u in db.scalars(select(m.User).where(m.User.institution_id == setup["iid"]))
            }

    refresh()
    with owner_session() as db:
        sam = db.scalar(
            select(m.User.id).where(
                m.User.institution_id == setup["iid"], m.User.display_name == "Sam Student"
            )
        )
    r = _client().post(
        f"/api/v1/admin/people/{sam}/erase",
        json={"confirm": "ERASE"},
        headers=_auth(setup["iid"], setup["admin"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["return_blocked_for_identifiers"] == 3  # sub, Canvas id, student ID
    assert "Sam Student" not in people()

    # The markers hold fingerprints, never the identifiers themselves.
    with owner_session() as db:
        markers = list(db.scalars(select(m.ErasedIdentity).where(m.ErasedIdentity.user_id == sam)))
        assert {x.kind for x in markers} == {"lti_sub", "canvas_user_id", "sis_user_id"}
        assert all(len(x.value_digest) == 64 for x in markers)
        assert not {x.value_digest for x in markers} & {"sub-s1", "4", "201234567"}

    # Still on the Canvas class list: left out, and everyone else is read as usual.
    result = refresh()
    assert (result.members, result.learners, result.staff, result.erased_skipped) == (2, 0, 1, 1)
    assert "Sam Student" not in people() and people()["Tess Teacher"] == "active"

    # Opening Badges from Canvas is refused too, by any identifier that names them.
    for identifiers in (
        {"sub": "sub-s1", "canvas_user_id": None},
        {"sub": "a-new-sub", "canvas_user_id": "4"},
        {"sub": "a-new-sub", "canvas_user_id": None, "sis_user_id": "201234567"},
    ):
        with pytest.raises(ErasedPerson), tenant_session(setup["iid"]) as db:
            upsert_user(
                db,
                setup["iid"],
                setup["integ"],
                name="Sam Student",
                given_name=None,
                family_name=None,
                email="sam@x.test",
                verified_by="lti",
                **identifiers,  # type: ignore[arg-type]
            )
    assert "Sam Student" not in people()

    # If they ask to come back, the operator removes the markers; they start again from empty.
    with owner_session() as db:
        slug = db.get(m.Institution, setup["iid"]).slug  # type: ignore[union-attr]
    runner = CliRunner()
    args = ["admin", "readmit", "--institution", slug, "--user-id"]
    assert runner.invoke(cli_app, [*args, str(setup["admin"])]).exit_code == 1  # not erased
    out = runner.invoke(cli_app, [*args, str(sam)])
    assert out.exit_code == 0 and "removed 3 marker(s)" in out.output
    assert refresh().erased_skipped == 0
    assert people()["Sam Student"] == "active"
    with owner_session() as db:
        again = db.scalar(
            select(m.User.id).where(
                m.User.institution_id == setup["iid"], m.User.display_name == "Sam Student"
            )
        )
        assert again != sam and db.get(m.User, sam).status == "deleted"  # type: ignore[union-attr]


def test_partial_roster_never_revokes(setup: dict[str, Any]) -> None:
    from opencredential.integrations.base import LmsTransientError

    settings = get_settings()
    members = [_member("sub-t", "Tess", [INSTRUCTOR], "2"), _member("sub-s", "Sam", [LEARNER], "4")]
    with tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        sync_roster(db, settings, integ, course, transport=_nrps(members))  # type: ignore[arg-type]
    services.clear_token_cache()
    with pytest.raises(LmsTransientError), tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        sync_roster(  # type: ignore[arg-type]
            db, settings, integ, course, transport=_nrps(members[:1], fail_page_2=True)
        )
    with owner_session() as db:
        active = db.scalars(
            select(m.Membership.role).where(
                m.Membership.scope_id == setup["course"], m.Membership.revoked_at.is_(None)
            )
        ).all()
    assert sorted(active) == ["lecturer", "student"]


def test_registry_builds_canvas_adapter_for_active_integration(setup: dict[str, Any]) -> None:
    from opencredential.integrations.canvas.adapter import CanvasAdapter
    from opencredential.integrations.registry import AdapterUnavailable, get_adapter

    with owner_session() as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        assert integ is not None
        db.expunge(integ)
    with pytest.raises(AdapterUnavailable):
        get_adapter(integ, "4")  # pending: not authorised yet
    integ.status = "active"
    assert isinstance(get_adapter(integ, "4"), CanvasAdapter)


# ---- whole-product review, 16 Nov 2026, finding 19 -----------------------------------------


def _roster_roles(course_id: uuid.UUID) -> dict[str, set[str]]:
    with owner_session() as db:
        out: dict[str, set[str]] = {}
        for ms, u in db.execute(
            select(m.Membership, m.User)
            .join(m.User, m.User.id == m.Membership.user_id)
            .where(m.Membership.scope_id == course_id, m.Membership.revoked_at.is_(None))
        ):
            out.setdefault(u.display_name or "", set()).add(ms.role)
        return out


def test_one_record_that_cannot_be_stored_does_not_stop_the_class_list(
    setup: dict[str, Any],
) -> None:
    """Two Canvas accounts claiming one identifier used to fail the whole course refresh, so
    nobody in the course was updated until someone fixed Canvas."""
    settings = get_settings()

    def refresh(members: list[dict[str, Any]]) -> Any:
        services.clear_token_cache()
        with tenant_session(setup["iid"]) as db:
            integ = db.get(m.CanvasIntegration, setup["integ"])
            course = db.get(m.Course, setup["course"])
            return sync_roster(db, settings, integ, course, transport=_nrps(members))  # type: ignore[arg-type]

    refresh(
        [
            _member("sub-t", "Tess Teacher", [INSTRUCTOR], "2"),
            _member("sub-x", "Xan Student", [LEARNER], None),
            _member("sub-y", "Yui Student", [LEARNER], "7"),
        ]
    )
    # Canvas now says Xan's account has the Canvas id that Yui's account holds, a new student
    # has joined, and Tess has left.
    res = refresh(
        [
            _member("sub-x", "Xan Renamed", [LEARNER], "7"),
            _member("sub-y", "Yui Student", [LEARNER], "7"),
            _member("sub-z", "Zed Student", [LEARNER], "9"),
        ]
    )
    assert (res.members, res.skipped, res.learners) == (3, 1, 2)
    assert res.revoked == 1  # Tess only
    # Xan is left exactly as they were (name included) and keeps their place; the rest of
    # the class is up to date.
    assert _roster_roles(setup["course"]) == {
        "Xan Student": {"student"},
        "Yui Student": {"student"},
        "Zed Student": {"student"},
    }


def test_test_student_on_the_class_list_is_flagged(setup: dict[str, Any]) -> None:
    """Canvas's Student View user can be on the class list before anyone opens Badges as them.
    Unflagged, an automatic award would give "Test Student" a real badge."""
    from opencredential.eligibility.service import course_students
    from opencredential.lti.claims import TEST_USER_ROLE

    settings = get_settings()
    members = [
        _member("sub-t", "Tess Teacher", [INSTRUCTOR], "2"),
        _member("sub-s", "Sam Student", [LEARNER], "4"),
        _member("sub-ts", "Test Student", [LEARNER, TEST_USER_ROLE], "99"),
    ]
    with tenant_session(setup["iid"]) as db:
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        sync_roster(db, settings, integ, course, transport=_nrps(members))  # type: ignore[arg-type]
    with tenant_session(setup["iid"]) as db:
        flagged = {
            u.display_name: u.is_test_user
            for u in db.scalars(
                select(m.User).where(m.User.display_name.in_(["Sam Student", "Test Student"]))
            )
        }
        students = {
            db.get(m.User, uid).display_name for uid in course_students(db, setup["course"])
        }  # type: ignore[union-attr]
    assert flagged == {"Sam Student": False, "Test Student": True}
    assert students == {"Sam Student"}


def test_class_list_token_is_never_sent_to_another_site(setup: dict[str, Any]) -> None:
    """The address of the next page comes from the response. One that points somewhere else
    must be refused, not followed with the service token."""
    from opencredential.integrations.base import LmsPermissionError

    settings = get_settings()
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.path == "/login/oauth2/token":
            return httpx.Response(200, json={"access_token": "svc", "expires_in": 3600})
        return httpx.Response(
            200,
            json={"members": [_member("sub-t", "Tess", [INSTRUCTOR], "2")]},
            headers={"link": '<https://elsewhere.example/collect?page=2>; rel="next"'},
        )

    services.clear_token_cache()
    with (
        pytest.raises(LmsPermissionError, match=r"elsewhere\.example"),
        tenant_session(setup["iid"]) as db,
    ):
        integ = db.get(m.CanvasIntegration, setup["integ"])
        course = db.get(m.Course, setup["course"])
        sync_roster(  # type: ignore[arg-type]
            db, settings, integ, course, transport=httpx.MockTransport(handler)
        )
    assert "elsewhere.example" not in asked
    assert _roster_roles(setup["course"]) == {}  # and a refused list changes nobody
