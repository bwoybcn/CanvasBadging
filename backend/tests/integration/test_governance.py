# SPDX-License-Identifier: AGPL-3.0-or-later
"""W7: institutional governance through the API (spec §10, §12.5, Phase 7 exit condition).

Every step an institution needs is done through the HTTP API, never by editing rows: issuers
are created and authorised, delegated, roles granted, policy and retention set, templates
used, credentials revoked, records reported, audit inspected, personal data exported and
erased, failed issuance reconciled. Includes spec §19.3 scenarios 8 and 10.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.errors import Conflict
from opencredential.governance.institution import set_verification_host
from opencredential.integrations import registry
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient
from opencredential.verification.service import Outcome, Verifier
from opencredential.verification.sources import DefaultSources, own_origins
from tests.integration.world import World, build_world

pytestmark = pytest.mark.db

MANUAL_RULES = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}
BASIS = "Senate resolution S/2026/14: Library may award study-skills badges"


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


def _org_unit(world: World) -> str:
    units = world.get("admin", "/api/v1/admin/org-units").json()
    return str(units[0]["id"])


def _new_issuer(world: World, who: str = "reviewer", **kw: Any) -> dict[str, Any]:
    body = {
        "name": "Library Skills Centre",
        "slug": f"library-{uuid.uuid4().hex[:6]}",
        "level": "department",
        "org_unit_id": _org_unit(world),
        "url": "https://library.example.ac.uk/",
        **kw,
    }
    r = world.post(who, "/api/v1/admin/issuers", body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def _authorised_issuer(world: World) -> str:
    """Create, authorise (real signer key) and delegate an issuer to the world's course."""
    issuer = _new_issuer(world)
    r = world.post(
        "admin", f"/api/v1/admin/issuers/{issuer['id']}/authorise", {"authority_basis": BASIS}
    )
    assert r.status_code == 200, r.text
    r = world.post(
        "reviewer",
        f"/api/v1/admin/issuers/{issuer['id']}/delegations",
        {"scope_type": "course", "scope_id": str(world.course_id)},
    )
    assert r.status_code == 201, r.text
    return str(issuer["id"])


def _manual_badge(world: World, issuer_id: str) -> str:
    world.issuer_id = uuid.UUID(issuer_id)
    body = world.publish(
        MANUAL_RULES,
        title="Seminar Participation",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )
    return str(body["id"])


def _issue_to(world: World, definition_id: str, student: str) -> str:
    """Manual award through the API, then run the issuance job inline (as the worker would)."""
    with world.db() as db:  # Canvas would have supplied the learner's email at launch
        user = db.get(m.User, world.users[student])
        assert user is not None
        user.email = user.email or f"{student}@student.example.ac.uk"
        user.email_verified_by = "lti"
    r = world.post(
        "lecturer",
        "/api/v1/awards/manual",
        {
            "definition_id": definition_id,
            "user_id": str(world.users[student]),
            "justification": "Contributed to six of eight seminars, observed by the tutor.",
        },
    )
    assert r.status_code == 201, r.text
    decision_id = r.json()["id"]
    assert tasks.issue_credential(str(world.iid), decision_id=decision_id) == "issued"
    with world.db() as db:
        cred = db.scalar(
            select(m.Credential).where(m.Credential.award_decision_id == uuid.UUID(decision_id))
        )
        assert cred is not None and cred.status == "issued"
        return str(cred.id)


def _actions(world: World) -> set[str]:
    with world.db() as db:
        return set(db.scalars(select(m.AuditEvent.action)))


# ---- issuers and delegated authority (§10.2) ----------------------------------------------


def test_issuer_needs_explicit_authority_before_it_can_be_used(
    world: World, signer_available: bool
) -> None:
    issuer = _new_issuer(world)
    assert issuer["status"] == "draft" and issuer["did"] is None and issuer["active_key"] is None

    # Creating an issuer does not create an awarding body: authors cannot use it yet.
    r = world.post(
        "reviewer",
        f"/api/v1/admin/issuers/{issuer['id']}/delegations",
        {"scope_type": "course", "scope_id": str(world.course_id)},
    )
    assert r.status_code == 201
    world.issuer_id = uuid.UUID(issuer["id"])
    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {"issuer_id": issuer["id"], "course_id": str(world.course_id), "fields": {}},
    )
    assert r.status_code == 403 and r.json()["code"] == "ISSUER_NOT_DELEGATED"

    # Only an institution administrator authorises, and must record the basis of authority.
    path = f"/api/v1/admin/issuers/{issuer['id']}/authorise"
    assert world.post("reviewer", path, {"authority_basis": BASIS}).status_code == 403
    assert world.post("admin", path, {"authority_basis": "short"}).status_code == 422
    r = world.post("admin", path, {"authority_basis": BASIS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active" and body["authority_basis"] == BASIS
    assert body["did"].startswith("did:key:") and body["active_key"]["is_dev"] is True
    assert world.post("admin", path, {"authority_basis": BASIS}).status_code == 409

    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {"issuer_id": issuer["id"], "course_id": str(world.course_id), "fields": {}},
    )
    assert r.status_code == 201, r.text
    assert {"issuer.create", "issuer.delegate", "issuer.authorise", "issuer_key.activate"} <= (
        _actions(world)
    )


def test_department_admin_scope_for_issuers(world: World) -> None:
    r = world.post(
        "reviewer",
        "/api/v1/admin/issuers",
        {"name": "University of Test", "slug": "uni-test", "level": "university"},
    )
    assert r.status_code == 403 and r.json()["code"] == "OUT_OF_SCOPE"
    other = world.post(
        "admin", "/api/v1/admin/org-units", {"name": "Chemistry", "kind": "department"}
    ).json()
    r = world.post(
        "reviewer",
        "/api/v1/admin/issuers",
        {
            "name": "Chemistry Badges",
            "slug": "chem",
            "level": "department",
            "org_unit_id": other["id"],
        },
    )
    assert r.status_code == 403
    assert world.get("lecturer", "/api/v1/admin/issuers").status_code == 403
    assert world.get("s1", "/api/v1/admin/issuers").status_code == 403


def test_departments_that_may_not_issue(world: World, signer_available: bool) -> None:
    issuer_id = _authorised_issuer(world)
    unit = _org_unit(world)
    # Only an institution administrator decides which departments may issue.
    r = world.patch("reviewer", f"/api/v1/admin/org-units/{unit}", {"may_issue": False})
    assert r.status_code == 403
    r = world.patch("admin", f"/api/v1/admin/org-units/{unit}", {"may_issue": False})
    assert r.status_code == 200 and r.json()["effective_may_issue"] is False
    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {"issuer_id": issuer_id, "course_id": str(world.course_id), "fields": {}},
    )
    assert r.status_code == 403
    world.patch("admin", f"/api/v1/admin/org-units/{unit}", {"may_issue": True})
    assert (
        world.post(
            "lecturer",
            "/api/v1/achievements",
            {"issuer_id": issuer_id, "course_id": str(world.course_id), "fields": {}},
        ).status_code
        == 201
    )


# ---- delegated administrative permissions (§2.3, §2.4) -------------------------------------


def test_delegated_role_management(world: World) -> None:
    grant = {
        "user_id": str(world.users["outsider"]),
        "role": "lecturer",
        "scope_type": "course",
        "scope_id": str(world.course_id),
    }
    assert world.post("lecturer", "/api/v1/admin/memberships", grant).status_code == 403
    r = world.post("reviewer", "/api/v1/admin/memberships", grant)
    assert r.status_code == 201, r.text
    membership = r.json()
    assert membership["scope_name"] == "Study Skills 101"
    # The new lecturer can act in the course immediately.
    assert world.get("outsider", f"/api/v1/courses/{world.course_id}/progress").status_code != 403

    # A department administrator cannot create institution administrators.
    r = world.post(
        "reviewer",
        "/api/v1/admin/memberships",
        {
            "user_id": str(world.users["outsider"]),
            "role": "inst_admin",
            "scope_type": "institution",
        },
    )
    assert r.status_code == 403
    # Students come from Canvas and cannot be granted here.
    bad = {**grant, "role": "student"}
    assert world.post("admin", "/api/v1/admin/memberships", bad).status_code == 422

    # The institution can switch delegation off.
    world.patch("admin", "/api/v1/institutions/current/policy", {"dept_admins_may_delegate": False})
    r = world.client.delete(
        f"/api/v1/admin/memberships/{membership['id']}", headers=world.h("reviewer")
    )
    assert r.status_code == 403
    r = world.client.delete(
        f"/api/v1/admin/memberships/{membership['id']}", headers=world.h("admin")
    )
    assert r.status_code == 204

    # The last institution administrator cannot be removed.
    admins = [
        x
        for x in world.get("admin", "/api/v1/admin/memberships").json()
        if x["role"] == "inst_admin"
    ]
    assert len(admins) == 1
    r = world.client.delete(
        f"/api/v1/admin/memberships/{admins[0]['id']}", headers=world.h("admin")
    )
    assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"
    assert {"membership.grant", "membership.revoke", "institution.policy_update"} <= _actions(world)


def test_expired_roles_stop_working(world: World) -> None:
    with world.db() as db:
        db.add(
            m.Membership(
                institution_id=world.iid,
                user_id=world.users["outsider"],
                scope_type="institution",
                scope_id=world.iid,
                role="inst_admin",
                source="grant",
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    assert world.get("outsider", "/api/v1/admin/issuers").status_code == 403


# ---- policy, configuration and retention (§10.1, §10.3, §12.5) ----------------------------


def test_policy_configuration(world: World) -> None:
    r = world.patch(
        "admin",
        "/api/v1/institutions/current/policy",
        {
            "revokers": ["lecturer"],
            "approver_roles": ["dept_admin"],
            "score_rules_default_policy": "automatic",
        },
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert set(p["revokers"]) == {"lecturer", "inst_admin"}  # admins can always revoke
    assert p["score_rules_default_policy"] == "automatic"
    r = world.patch("admin", "/api/v1/institutions/current/policy", {"revokers": ["student"]})
    assert r.status_code == 422
    assert (
        world.patch(
            "reviewer", "/api/v1/institutions/current/policy", {"revokers": ["lecturer"]}
        ).status_code
        == 403
    )


def test_institution_configuration(world: World) -> None:
    r = world.patch(
        "admin",
        "/api/v1/institutions/current",
        {
            "name": "University of Liverpool (TEST)",
            "description": "Test tenant",
            "website_url": "https://www.liverpool.ac.uk/",
            "branding": {"primary_colour": "#212b58", "secondary_colour": "#c8102e"},
            "categories": ["Academic Skills", "Employability", "Academic Skills"],
        },
    )
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["categories"] == ["Academic Skills", "Employability"]
    # The verification domain is operator-only (review finding S3).
    bad = world.patch(
        "admin", "/api/v1/institutions/current", {"verification_host": "badges.example.ac.uk"}
    )
    assert bad.status_code == 403 and bad.json()["code"] == "VERIFICATION_HOST_OPERATOR_ONLY"
    assert (
        world.patch(
            "admin", "/api/v1/institutions/current", {"website_url": "http://insecure"}
        ).status_code
        == 422
    )
    assert world.get("lecturer", "/api/v1/institutions/current").status_code == 403

    # Who to ask for help: set by the administrator, shown to everyone on the Help page.
    assert world.get("s1", "/api/v1/learners/me").json()["help"] == {
        "contact_name": None,
        "email": None,
        "url": None,
    }
    contact = {
        "help_contact_name": " Digital Education team ",
        "help_email": "badges-help@liverpool.example",
        "help_url": "https://www.liverpool.example/badges-help",
    }
    r = world.patch("admin", "/api/v1/institutions/current", contact)
    assert r.status_code == 200, r.text
    assert r.json()["help_contact_name"] == "Digital Education team"
    assert world.get("s1", "/api/v1/learners/me").json()["help"] == {
        "contact_name": "Digital Education team",
        "email": "badges-help@liverpool.example",
        "url": "https://www.liverpool.example/badges-help",
    }
    for bad_contact, code in (
        ({"help_email": "not an address"}, "EMAIL_INVALID"),
        ({"help_url": "http://insecure.example"}, "URL_INVALID"),
    ):
        r = world.patch("admin", "/api/v1/institutions/current", bad_contact)
        assert r.status_code == 422 and r.json()["code"] == code
    # Clearing a field removes it.
    r = world.patch("admin", "/api/v1/institutions/current", {"help_email": ""})
    assert r.status_code == 200 and r.json()["help_email"] is None

    r = world.patch("admin", "/api/v1/institutions/current/retention", {"audit_event_years": 0})
    assert r.status_code == 422
    r = world.patch("admin", "/api/v1/institutions/current/retention", {"evaluation_days": 400})
    assert r.status_code == 200 and r.json()["evaluation_days"] == 400


def test_did_web_issuer_on_configured_host(world: World, signer_available: bool) -> None:
    host = f"badges-{uuid.uuid4().hex[:6]}.test.ac.uk"
    _operator_sets_host(world, host)
    issuer = _new_issuer(world, who="admin", slug="library-web")
    r = world.post(
        "admin", f"/api/v1/admin/issuers/{issuer['id']}/authorise", {"authority_basis": BASIS}
    )
    assert r.status_code == 200, r.text
    assert r.json()["did"] == f"did:web:{host}:issuers:library-web"
    # Now that credentials could be signed on this host, moving it is refused.
    with pytest.raises(Conflict) as exc:
        _operator_sets_host(world, "other.ac.uk")
    assert exc.value.code == "VERIFICATION_HOST_IN_USE"


def _operator_sets_host(world: World, host: str | None) -> None:
    with owner_session() as db:
        inst = db.get(m.Institution, world.iid)
        assert inst is not None
        set_verification_host(db, inst, host)


# ---- templates (§10.4) ----------------------------------------------------------------------


def test_templates_prefill_new_badges(world: World) -> None:
    defaults = {
        "title": "Academic Skills: ",
        "criteria_narrative": "Complete the module and its quiz.",
        "evidence_description": "Quiz attempt recorded in Canvas.",
        "validity_days": 1095,
        "skills": [{"name": "Academic writing", "framework": "UoL Skills"}],
        "artwork": {"template": "shield", "primary_colour": "#212b58", "guidance": "Use navy."},
    }
    r = world.post(
        "lecturer", "/api/v1/admin/templates", {"name": "Skills Passport", "defaults": defaults}
    )
    assert r.status_code == 403
    inst = world.post(
        "admin", "/api/v1/admin/templates", {"name": "Skills Passport", "defaults": defaults}
    )
    assert inst.status_code == 201, inst.text
    dept = world.post(
        "reviewer",
        "/api/v1/admin/templates",
        {
            "name": "Library workshop",
            "org_unit_id": _org_unit(world),
            "defaults": {"validity_days": 365},
        },
    )
    assert dept.status_code == 201, dept.text
    offered = world.get("lecturer", f"/api/v1/templates?course_id={world.course_id}").json()
    assert {t["name"] for t in offered} == {"Skills Passport", "Library workshop"}

    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(world.issuer_id),
            "course_id": str(world.course_id),
            "template_id": inst.json()["id"],
            "fields": {"title": "Academic Skills: Referencing"},
        },
    )
    assert r.status_code == 201, r.text
    v = r.json()["working_version"]
    assert v["title"] == "Academic Skills: Referencing"  # typed value wins
    assert v["criteria_narrative"] == defaults["criteria_narrative"]
    assert v["validity_days"] == 1095 and v["skills"][0]["name"] == "Academic writing"

    world.patch("admin", f"/api/v1/admin/templates/{inst.json()['id']}", {"status": "archived"})
    offered = world.get("lecturer", f"/api/v1/templates?course_id={world.course_id}").json()
    assert {t["name"] for t in offered} == {"Library workshop"}


# ---- Scenario 8: revocation, with records, reporting and audit -----------------------------


def test_scenario_8_authorised_admin_revokes(world: World, signer_available: bool) -> None:
    issuer_id = _authorised_issuer(world)
    definition_id = _manual_badge(world, issuer_id)
    cred_id = _issue_to(world, definition_id, "s1")

    # The learner downloads their credential before anything happens.
    r = world.get("s1", f"/api/v1/credentials/{cred_id}/export")
    assert r.status_code == 200
    downloaded = r.json()
    signer = SignerClient(get_settings())
    verifier = Verifier(signer, DefaultSources(own_origins(get_settings().public_base_url)))
    try:
        with world.db() as db:
            cred = db.get(m.Credential, uuid.UUID(cred_id))
            assert cred is not None and cred.status_list_id is not None
            list_id = cred.status_list_id
        tasks.publish_status_list(str(world.iid), str(list_id))
        assert verifier.verify(downloaded).result == Outcome.verified

        # A lecturer is not a revoker under the default policy: they can only ask.
        revoke = {"reason_code": "issued_in_error", "reason_text": "Awarded to the wrong learner"}
        r = world.post("lecturer", f"/api/v1/credentials/{cred_id}/revoke", revoke)
        assert r.status_code == 403
        r = world.post(
            "lecturer",
            f"/api/v1/credentials/{cred_id}/revocation-requests",
            {"reason": "Awarded to the wrong learner"},
        )
        assert r.status_code == 201, r.text
        requests = world.get("reviewer", "/api/v1/admin/revocation-requests").json()
        assert len(requests) == 1 and requests[0]["can_decide"] is True

        # The department administrator (a revoker by policy) approves, which revokes.
        r = world.post(
            "reviewer",
            f"/api/v1/admin/revocation-requests/{requests[0]['id']}/approve",
            {"reason_code": "issued_in_error"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # The status list was republished in the same request (signer reachable).
        result = verifier.verify(downloaded)
        assert result.result == Outcome.revoked
    finally:
        signer.close()

    # Revoking again changes nothing; the record is kept.
    r = world.post(
        "admin",
        f"/api/v1/credentials/{cred_id}/revoke",
        {"reason_code": "other", "reason_text": "again"},
    )
    assert r.status_code == 200 and r.json()["changed"] is False

    # Records, reporting and CSV show it (§10.5).
    rows = world.get("admin", "/api/v1/admin/credentials").json()
    assert [(r["credential_id"], r["status"]) for r in rows] == [(cred_id, "revoked")]
    assert rows[0]["learner_name"] == "S1" and "email" not in rows[0]
    summary = world.get("admin", "/api/v1/admin/reports/summary").json()
    assert (summary["issued"], summary["revoked"], summary["active"]) == (1, 1, 0)
    assert summary["by_course"][0]["course_title"] == "Study Skills 101"
    assert summary["by_badge"][0]["badge_title"] == "Seminar Participation"
    r = world.get("admin", "/api/v1/admin/reports/issuance.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    table = list(csv.DictReader(io.StringIO(r.text)))
    assert table[0]["status"] == "revoked" and table[0]["revocation_reason"] == "issued_in_error"
    assert "@" not in r.text  # no email addresses
    assert world.get("admin", "/api/v1/admin/reports/summary.csv").status_code == 200
    assert world.get("lecturer", "/api/v1/admin/reports/summary").status_code == 403
    assert world.get("s1", "/api/v1/admin/reports/issuance.csv").status_code == 403

    # The audit log covers every §10.6 category this flow touched, without learner names.
    log = world.get("admin", "/api/v1/admin/audit?limit=500").json()["items"]
    cats = {e["category"] for e in log}
    assert {
        "Issuer creation and authority",
        "Badge definitions",
        "Definition approval",
        "Publication",
        "Manual awards",
        "Automated awards",
        "Revocations",
        "Key management",
    } <= cats
    revoke_event = next(e for e in log if e["action"] == "credential.revoke")
    assert revoke_event["actor_name"] == "Reviewer"
    assert revoke_event["resource_id"] == cred_id
    assert "reason_text" not in revoke_event["data"]
    assert all(e["actor_name"] != "S1" for e in log)
    only = world.get("admin", "/api/v1/admin/audit?category=Revocations").json()["items"]
    assert only and all(e["category"] == "Revocations" for e in only)
    assert world.get("admin", "/api/v1/admin/audit.csv").status_code == 200
    assert world.get("reviewer", "/api/v1/admin/audit").status_code == 403


# ---- Scenario 10: unauthorised access --------------------------------------------------------


def test_scenario_10_unauthorized_access(client: TestClient, signer_available: bool) -> None:
    a = build_world(client)
    b = build_world(client)
    with registry.override(a.lms):
        a_def = _manual_badge(a, _authorised_issuer(a))
        a_s1 = _issue_to(a, a_def, "s1")
        a_s2 = _issue_to(a, a_def, "s2")
    with registry.override(b.lms):
        b_def = _manual_badge(b, _authorised_issuer(b))
        b_s1 = _issue_to(b, b_def, "s1")
    missing = str(uuid.uuid4())

    def same_as_missing(r: Any, path: str, who: World, user: str) -> None:
        ref = who.get(user, path.replace("{id}", missing))
        assert r.status_code == ref.status_code == 404
        assert r.json()["code"] == ref.json()["code"]
        assert r.json()["title"] == ref.json()["title"]

    # A student cannot read another student's private credential in their own institution…
    path = "/api/v1/credentials/{id}/export"
    assert a.get("s1", path.replace("{id}", a_s1)).status_code == 200
    # exists, but not theirs: indistinguishable from a missing record
    same_as_missing(a.get("s1", path.replace("{id}", a_s2)), path, a, "s1")
    # …or anything in Institution B, which is indistinguishable from a missing record.
    same_as_missing(a.get("s1", path.replace("{id}", b_s1)), path, a, "s1")
    # Nor ask to revoke, or reach admin data.
    r = a.post("s1", f"/api/v1/credentials/{a_s2}/revocation-requests", {"reason": "please"})
    assert r.status_code == 404
    for admin_path in (
        "/api/v1/admin/credentials",
        "/api/v1/admin/audit",
        "/api/v1/admin/reports/summary",
        "/api/v1/admin/memberships",
        "/api/v1/admin/reconciliation",
        f"/api/v1/admin/people/{a.users['s2']}/data-export",
    ):
        assert a.get("s1", admin_path).status_code == 403, admin_path

    # Institution A's administrator sees none of Institution B's records.
    rows = a.get("admin", "/api/v1/admin/credentials").json()
    assert {r["credential_id"] for r in rows} == {a_s1, a_s2}
    assert b_s1 not in a.get("admin", "/api/v1/admin/reports/issuance.csv").text
    ids = {
        e["resource_id"] for e in a.get("admin", "/api/v1/admin/audit?limit=500").json()["items"]
    }
    assert b_s1 not in ids
    revoke = {"reason_code": "other", "reason_text": "cross-tenant attempt"}
    same_as_missing(
        a.post("admin", f"/api/v1/credentials/{b_s1}/revoke", revoke),
        "/api/v1/credentials/{id}/export",
        a,
        "admin",
    )
    assert a.get("admin", f"/api/v1/admin/people/{b.users['s1']}/data-export").status_code == 404
    assert (
        a.post(
            "admin", f"/api/v1/admin/people/{b.users['s1']}/erase", {"confirm": "ERASE"}
        ).status_code
        == 404
    )
    assert (
        a.patch("admin", f"/api/v1/admin/issuers/{b.issuer_id}", {"name": "Hijack"}).status_code
        == 404
    )
    r = a.post(
        "admin",
        "/api/v1/admin/memberships",
        {
            "user_id": str(b.users["s1"]),
            "role": "lecturer",
            "scope_type": "course",
            "scope_id": str(a.course_id),
        },
    )
    assert r.status_code == 404
    with b.db() as db:
        status = db.scalar(
            select(m.CredentialStatus).where(m.CredentialStatus.credential_id == uuid.UUID(b_s1))
        )
        assert status is None or status.state == "active"


# ---- personal data and retention (§12.5) ----------------------------------------------------


def test_personal_data_export_and_erasure_are_separate_from_revocation(
    world: World, signer_available: bool, owner_conn: psycopg.Connection
) -> None:
    definition_id = _manual_badge(world, _authorised_issuer(world))
    cred_id = _issue_to(world, definition_id, "s1")
    with world.db() as db:
        db.add(
            m.ShareGrant(
                institution_id=world.iid,
                credential_id=uuid.UUID(cred_id),
                share_id=uuid.uuid4().hex,
                created_by=world.users["s1"],
            )
        )

    r = world.get("s1", "/api/v1/learners/me/data-export")
    assert r.status_code == 200
    doc = r.json()
    assert doc["profile"]["display_name"] == "S1"
    assert [c["id"] for c in doc["credentials"]] == [cred_id]
    assert doc["credentials"][0]["signed_json"]["type"][-1] == "OpenBadgeCredential"
    assert "recipient_salt" not in doc["credentials"][0]
    assert len(doc["share_links"]) == 1
    assert (
        world.get("s1", f"/api/v1/admin/people/{world.users['s2']}/data-export").status_code == 403
    )
    assert (
        world.get("admin", f"/api/v1/admin/people/{world.users['s1']}/data-export").status_code
        == 200
    )

    path = f"/api/v1/admin/people/{world.users['s1']}/erase"
    assert world.post("reviewer", path, {"confirm": "ERASE"}).status_code == 403
    assert world.post("admin", path, {"confirm": "yes"}).status_code == 422
    r = world.post("admin", path, {"confirm": "ERASE"})
    assert r.status_code == 200, r.text
    counts = r.json()
    assert counts["credentials_kept"] == 1 and counts["share_links_withdrawn"] == 1
    assert counts["identities_deleted"] == 1 and counts["roles_ended"] == 1
    assert world.post("admin", path, {"confirm": "ERASE"}).status_code == 409

    with world.db() as db:
        user = db.get(m.User, world.users["s1"])
        assert user is not None and user.status == "deleted"
        assert (user.display_name, user.email, user.family_name) == (None, None, None)
        cred = db.get(m.Credential, uuid.UUID(cred_id))
        assert cred is not None and cred.status == "issued"  # not revoked by erasure
        status = db.scalar(
            select(m.CredentialStatus).where(m.CredentialStatus.credential_id == cred.id)
        )
        assert status is None or status.state == "active"
        share = db.scalar(select(m.ShareGrant).where(m.ShareGrant.credential_id == cred.id))
        assert share is not None and share.revoked_at is not None  # public page taken down
    rows = world.get("admin", "/api/v1/admin/credentials").json()
    assert rows[0]["learner_name"] is None
    assert "privacy.erase" in _actions(world)


def _expire(owner_conn: psycopg.Connection, cred_id: str) -> None:
    """Back-date a credential's expiry (the issued-credential trigger normally forbids it)."""
    with owner_conn.transaction():
        owner_conn.execute(
            "ALTER TABLE app.credentials DISABLE TRIGGER trg_credentials_issued_immutable"
        )
        owner_conn.execute(
            "UPDATE app.credentials SET valid_until = now() - interval '1 day' WHERE id = %s",
            [uuid.UUID(cred_id)],
        )
        owner_conn.execute(
            "ALTER TABLE app.credentials ENABLE TRIGGER trg_credentials_issued_immutable"
        )


def test_records_paging_and_summary_count_expired_credentials_correctly(
    world: World, signer_available: bool, owner_conn: psycopg.Connection
) -> None:
    """Outside review finding 4 (14 Nov 2026): status filters run in SQL, so pages are full,
    and the summary is counted in PostgreSQL."""
    definition_id = _manual_badge(world, _authorised_issuer(world))
    active = _issue_to(world, definition_id, "s3")
    revoked = _issue_to(world, definition_id, "s1")
    expired = _issue_to(world, definition_id, "s2")  # newest
    r = world.post(
        "admin",
        f"/api/v1/credentials/{revoked}/revoke",
        {"reason_code": "issued_in_error", "reason_text": "test"},
    )
    assert r.status_code == 200, r.text
    _expire(owner_conn, expired)

    def ids(path: str) -> list[str]:
        r = world.get("admin", path)
        assert r.status_code == 200, r.text
        return [row["credential_id"] for row in r.json()]

    # The newest credential is expired; an "active" page of one must still hold one row.
    assert ids("/api/v1/admin/credentials?status=active&limit=1") == [active]
    assert ids("/api/v1/admin/credentials?status=active&limit=1&offset=1") == []
    assert ids("/api/v1/admin/credentials?status=expired") == [expired]
    assert ids("/api/v1/admin/credentials?status=revoked") == [revoked]
    assert ids("/api/v1/admin/credentials?limit=2") == [expired, revoked]
    assert ids("/api/v1/admin/credentials?limit=2&offset=2") == [active]
    course = f"/api/v1/courses/{world.course_id}/credentials"
    assert ids(f"{course}?status=expired") == [expired]
    assert [r["status"] for r in world.get("admin", course).json()] == [
        "expired",
        "revoked",
        "active",
    ]

    s = world.get("admin", "/api/v1/admin/reports/summary").json()
    assert (s["issued"], s["revoked"], s["active"]) == (3, 1, 1)
    assert [(c["issued"], c["revoked"]) for c in s["by_course"]] == [(3, 1)]
    assert [(b["badge_title"], b["issued"], b["revoked"]) for b in s["by_badge"]] == [
        ("Seminar Participation", 3, 1)
    ]
    assert sum(m["issued"] for m in s["by_month"]) == 3
    assert (
        world.get(
            "admin", "/api/v1/admin/reports/summary?issued_from=2000-01-01&issued_to=2000-01-02"
        ).json()["issued"]
        == 0
    )

    for path in (
        "/api/v1/admin/reports/issuance.csv?status=expired",
        f"{course}.csv?status=expired",
    ):
        r = world.get("admin", path)
        assert r.status_code == 200, r.text
        table = list(csv.DictReader(io.StringIO(r.text)))
        assert [(row["credential_id"], row["status"]) for row in table] == [(expired, "expired")]
    table = list(
        csv.DictReader(io.StringIO(world.get("admin", "/api/v1/admin/reports/issuance.csv").text))
    )
    assert [row["credential_id"] for row in table] == [expired, revoked, active]
    exports = [
        e
        for e in world.get("admin", "/api/v1/admin/audit?limit=500").json()["items"]
        if e["action"] in ("institution.report_export", "course.report_export")
    ]
    assert exports  # still audited, with the row count


def test_session_stops_working_once_the_account_is_erased(
    world: World, signer_available: bool
) -> None:
    """Outside review finding 3 (14 Nov 2026): a token issued before erasure must not keep
    working until it expires. Nothing is allowed with it afterwards, including sharing."""
    definition_id = _manual_badge(world, _authorised_issuer(world))
    cred_id = _issue_to(world, definition_id, "s1")
    share = f"/api/v1/credentials/{cred_id}/share"
    # The same token, issued before the erasure, works now...
    assert world.get("s1", "/api/v1/learners/me/credentials").status_code == 200
    r = world.put("s1", share, {"show_name": False, "show_evidence": False})
    assert r.status_code == 200, r.text
    with world.db() as db:
        share_id = db.scalar(
            select(m.ShareGrant.share_id).where(m.ShareGrant.credential_id == uuid.UUID(cred_id))
        )
    assert world.client.get(f"/verify/{share_id}").status_code == 200

    r = world.post("admin", f"/api/v1/admin/people/{world.users['s1']}/erase", {"confirm": "ERASE"})
    assert r.status_code == 200, r.text

    # ...and is refused everywhere afterwards.
    attempts = [
        world.get("s1", "/api/v1/learners/me"),
        world.get("s1", "/api/v1/learners/me/credentials"),
        world.get("s1", "/api/v1/learners/me/data-export"),
        world.get("s1", share),
        world.put("s1", share, {"show_name": True, "show_evidence": True}),
        world.delete("s1", share),
        world.get("s1", f"/api/v1/credentials/{cred_id}/export"),
    ]
    for resp in attempts:
        assert resp.status_code == 401, (resp.request.url, resp.text)
        assert resp.json()["code"] == "ACCOUNT_INACTIVE"
    with world.db() as db:
        grant = db.scalar(
            select(m.ShareGrant).where(m.ShareGrant.credential_id == uuid.UUID(cred_id))
        )
        assert grant is not None and grant.show_name is False  # the PUT above changed nothing
        assert grant.revoked_at is not None  # erasure took the public page down
    assert world.client.get(f"/verify/{share_id}").status_code == 404
    # Other people are unaffected.
    assert world.get("s2", "/api/v1/learners/me/credentials").status_code == 200
    assert world.get("admin", "/api/v1/admin/credentials").status_code == 200


def test_retention_purges_expired_data_but_keeps_credentials(
    world: World, owner_conn: psycopg.Connection, app_conn: psycopg.Connection
) -> None:
    old = datetime.now(UTC) - timedelta(days=3 * 365)
    owner_conn.execute(
        "INSERT INTO app.audit_events (id, institution_id, actor_kind, action, resource_type, at,"
        " data, created_at, updated_at) VALUES (%s, %s, 'system', 'test.old', 'test', %s, '{}',"
        " now(), now())",
        [uuid.uuid4(), world.iid, old],
    )
    owner_conn.commit()
    # Nobody can delete audit events directly, not even old ones.
    with pytest.raises(psycopg.Error):
        owner_conn.execute("DELETE FROM app.audit_events WHERE action = 'test.old'")
    owner_conn.rollback()

    world.patch("admin", "/api/v1/institutions/current/retention", {"audit_event_years": 2})
    assert world.post("reviewer", "/api/v1/admin/retention/run").status_code == 403
    r = world.post("admin", "/api/v1/admin/retention/run")
    assert r.status_code == 200, r.text
    assert r.json()["audit_events"] == 1
    assert "test.old" not in _actions(world) and "retention.apply" in _actions(world)
    # The database refuses a retention shorter than one year.
    with pytest.raises(psycopg.Error):
        app_conn.execute("SELECT app.purge_audit_events(%s, 0)", [world.iid])


# ---- reconciliation of failed issuance (§10.5, §17.2) ---------------------------------------


def test_reconciliation_of_awards_not_issued(world: World, owner_conn: psycopg.Connection) -> None:
    body = world.publish(
        MANUAL_RULES,
        title="Seminar Participation",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )
    decisions = []
    for s in ("s1", "s2"):
        r = world.post(
            "lecturer",
            "/api/v1/awards/manual",
            {
                "definition_id": body["id"],
                "user_id": str(world.users[s]),
                "justification": "Contributed to six of eight seminars, observed by the tutor.",
            },
        )
        decisions.append(r.json()["id"])
    # The worker never ran (or crashed): the awards are older than the stuck threshold.
    owner_conn.execute(
        "UPDATE app.award_decisions SET decided_at = now() - interval '1 hour' WHERE id = ANY(%s)",
        [[uuid.UUID(d) for d in decisions]],
    )
    owner_conn.commit()

    assert world.get("reviewer", "/api/v1/admin/reconciliation").status_code == 403
    view = world.get("admin", "/api/v1/admin/reconciliation").json()
    assert {a["decision_id"] for a in view["awards_not_issued"]} == set(decisions)
    assert all(a["problem"] == "never_started" for a in view["awards_not_issued"])

    r = world.post("admin", f"/api/v1/admin/reconciliation/awards/{decisions[0]}/requeue")
    assert r.status_code == 200, r.text
    r = world.post(
        "admin",
        f"/api/v1/admin/reconciliation/awards/{decisions[1]}/cancel",
        {"reason": "Duplicate of a paper certificate already issued"},
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = world.post("admin", f"/api/v1/admin/reconciliation/awards/{decisions[1]}/requeue")
    assert r.status_code == 409
    view = world.get("admin", "/api/v1/admin/reconciliation").json()
    assert {a["decision_id"] for a in view["awards_not_issued"]} == {decisions[0]}
    pending = world.get("admin", "/api/v1/admin/reports/summary").json()["pending_awards"]
    assert pending["awaiting_issuance"] == 1
    assert {"reconciliation.requeue", "reconciliation.cancel"} <= _actions(world)


# ---- whole-product review, 16 Nov 2026, finding 19 -----------------------------------------


def test_a_revoked_badge_is_not_shown_as_earned(world: World, signer_available: bool) -> None:
    """The student's progress page said "Earned" for a badge the issuer had revoked, while the
    public check of the same badge said "Revoked"."""
    issuer_id = _authorised_issuer(world)
    definition_id = _manual_badge(world, issuer_id)
    cred_id = _issue_to(world, definition_id, "s1")

    def mine() -> dict[str, Any]:
        badges = world.get("s1", "/api/v1/learners/me/achievements").json()
        return next(b for b in badges if b["definition_id"] == definition_id)

    def cell() -> dict[str, Any]:
        progress = world.get("lecturer", f"/api/v1/courses/{world.course_id}/progress").json()
        row = next(r for r in progress["learners"] if r["user_id"] == str(world.users["s1"]))
        return dict(row["cells"][0])

    assert (mine()["status"], mine()["credential_id"]) == ("earned", cred_id)
    # Staff see which issued badge it is, so "Request revocation" can be offered for it.
    assert (cell()["credential_id"], cell()["credential_state"]) == (cred_id, "active")
    other = world.get("lecturer", f"/api/v1/courses/{world.course_id}/progress").json()
    s2 = next(r for r in other["learners"] if r["user_id"] == str(world.users["s2"]))
    assert (s2["cells"][0]["credential_id"], s2["cells"][0]["credential_state"]) == (None, None)

    r = world.post(
        "admin",
        f"/api/v1/credentials/{cred_id}/revoke",
        {"reason_code": "issued_in_error", "reason_text": "Awarded to the wrong student"},
    )
    assert r.status_code == 200, r.text
    assert (mine()["status"], mine()["credential_id"]) == ("revoked", cred_id)
    assert (cell()["credential_id"], cell()["credential_state"]) == (cred_id, "revoked")


def test_course_progress_reads_only_the_newest_evaluation(world: World) -> None:
    """A course evaluated every half hour for a term has thousands of evaluation rows; the
    progress screen shows the newest one for each student and must not load the rest."""
    world.publish({"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]})
    world.sync_and_evaluate()
    world.lms.complete_module("course-101", "lms-s1", "m1")
    world.sync_and_evaluate()
    assert len(world.evaluations("s1")) >= 2  # history is kept
    progress = world.get("lecturer", f"/api/v1/courses/{world.course_id}/progress").json()
    row = next(r for r in progress["learners"] if r["user_id"] == str(world.users["s1"]))
    assert row["cells"][0]["outcome"] == "met"  # the newest, not the first
    other = next(r for r in progress["learners"] if r["user_id"] == str(world.users["s2"]))
    assert other["cells"][0]["outcome"] == "not_met"


def test_an_expired_role_can_be_granted_again(world: World) -> None:
    """Granting a role that had run out answered with the old, expired grant, so the person
    stayed without the role until someone removed the old row by hand."""
    grant = {
        "user_id": str(world.users["outsider"]),
        "role": "inst_admin",
        "scope_type": "institution",
    }
    first = world.post(
        "admin",
        "/api/v1/admin/memberships",
        {**grant, "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    assert first.status_code == 201, first.text
    # Asking again while it still runs changes nothing.
    again = world.post("admin", "/api/v1/admin/memberships", grant)
    assert again.json()["id"] == first.json()["id"]

    with world.db() as db:
        row = db.get(m.Membership, uuid.UUID(first.json()["id"]))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    renewed = world.post("admin", "/api/v1/admin/memberships", grant)
    assert renewed.status_code == 201, renewed.text
    assert renewed.json()["id"] != first.json()["id"]
    with world.db() as db:
        old = db.get(m.Membership, uuid.UUID(first.json()["id"]))
        new = db.get(m.Membership, uuid.UUID(renewed.json()["id"]))
        assert old is not None and old.revoked_at == old.expires_at  # closed when it ran out
        assert new is not None and new.revoked_at is None and new.expires_at is None


def test_an_expired_administrator_does_not_count_as_one(world: World) -> None:
    """Removing the last working administrator was allowed when another administrator's grant
    existed but had already run out, leaving the institution with nobody who could administer."""
    with world.db() as db:
        db.add(
            m.Membership(
                institution_id=world.iid,
                user_id=world.users["outsider"],
                scope_type="institution",
                scope_id=world.iid,
                role="inst_admin",
                source="grant",
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    with world.db() as db:
        only = db.scalar(
            select(m.Membership.id).where(
                m.Membership.user_id == world.users["admin"], m.Membership.role == "inst_admin"
            )
        )
    r = world.client.delete(f"/api/v1/admin/memberships/{only}", headers=world.h("admin"))
    assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"


def test_a_field_the_author_cleared_stays_cleared(world: World) -> None:
    """The template's wording came back into a field the author had deliberately emptied."""
    defaults = {
        "title": "Volunteering: [number] hours",
        "criteria_narrative": "Complete [number] hours with [Scheme name].",
        "evidence_description": "Hours signed off by the scheme coordinator.",
        "validity_days": 365,
    }
    template = world.post(
        "admin", "/api/v1/admin/templates", {"name": "Volunteering", "defaults": defaults}
    )
    assert template.status_code == 201, template.text
    created = world.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(world.issuer_id),
            "course_id": str(world.course_id),
            "template_id": template.json()["id"],
            # What the wizard sends: every field, the emptied ones as null.
            "fields": {
                "title": "Volunteering: 10 hours",
                "criteria_narrative": "Complete [number] hours with [Scheme name].",
                "evidence_description": None,
                "validity_days": None,
            },
        },
    )
    assert created.status_code == 201, created.text
    v = created.json()["working_version"]
    assert v["evidence_description"] is None and v["validity_days"] is None
    assert v["title"] == "Volunteering: 10 hours"

    # Template wording left in [square brackets] stops the badge being submitted.
    codes = {i["code"]: i for i in created.json()["readiness"]}
    assert codes["TEMPLATE_PLACEHOLDER"]["severity"] == "error"
    did = created.json()["id"]
    fixed = world.patch(
        "lecturer",
        f"/api/v1/achievements/{did}",
        {"criteria_narrative": "Complete 10 hours with the Library volunteers scheme."},
    )
    assert fixed.status_code == 200, fixed.text
    assert "TEMPLATE_PLACEHOLDER" not in {i["code"] for i in fixed.json()["readiness"]}


def test_square_brackets_in_a_badge_not_made_from_a_template_are_left_alone(
    world: World,
) -> None:
    d = world.draft(MANUAL_RULES, title="Chemistry [Year 2] practical skills")
    detail = world.get("lecturer", f"/api/v1/achievements/{d['id']}").json()
    assert "TEMPLATE_PLACEHOLDER" not in {i["code"] for i in detail["readiness"]}


def test_a_canvas_failure_does_not_undo_a_good_class_list(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The class list and the progress data were saved together, so when Canvas failed while
    progress was read, the class list that had just been read correctly was thrown away."""
    from opencredential.integrations.base import LmsPermissionError
    from opencredential.lti import roster

    def joined(db: Any, settings: Any, integration: Any, course: Any, **_: Any) -> Any:
        db.add(
            m.Membership(
                institution_id=world.iid,
                user_id=world.users["outsider"],
                scope_type="course",
                scope_id=course.id,
                role="student",
                source="nrps",
            )
        )
        db.flush()
        return roster.RosterResult(1, 1, 0, 0, 0)

    monkeypatch.setattr(roster, "sync_roster", joined)
    with world.db() as db:
        course = db.get(m.Course, world.course_id)
        assert course is not None
        course.lti_nrps_url = "https://canvas.example/api/lti/courses/101/names_and_roles"
    world.publish({"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]})
    world.lms.failures[("modules",)] = LmsPermissionError("Canvas refused")

    assert world.sync()["status"] == "failed"
    with world.db() as db:
        kept = db.scalar(
            select(m.Membership.id).where(
                m.Membership.user_id == world.users["outsider"],
                m.Membership.scope_id == world.course_id,
                m.Membership.role == "student",
                m.Membership.revoked_at.is_(None),
            )
        )
    assert kept is not None
