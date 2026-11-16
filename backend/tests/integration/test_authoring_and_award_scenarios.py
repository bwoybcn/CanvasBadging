# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §19.3 scenarios 1-5 against PostgreSQL and a fake Canvas (W5 exit evidence).

Background jobs are executed inline by calling the task functions, exactly as the worker would.
Credential signing itself belongs to the issuance module (W4); here "issues the credential"
means the award decision is ``ready`` and exactly one ``oc:issue_credential`` job is queued in
the same transaction (ADR-0012), which is the hand-off W4 consumes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.integrations import registry
from opencredential.integrations.base import LmsTransientError
from opencredential.settings import get_settings
from tests.integration.world import CHECKLIST, COURSE_REF, World, build_world

pytestmark = pytest.mark.db

MODULE_RULES = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}
SCORE_RULES = {
    "mode": "ALL",
    "rules": [
        {"type": "module_completed", "module_id": "m1"},
        {"type": "assignment_score", "assignment_id": "a1", "threshold_percent": 70},
    ],
}
ISSUE = "oc:issue_credential"


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


# ---- Scenario 1: lecturer creates a badge ----


def test_scenario_1_lecturer_creates_previews_and_publishes(world: World, owner_conn) -> None:  # type: ignore[no-untyped-def]
    world.sync()
    d = world.draft(MODULE_RULES)
    did = d["id"]
    assert d["state"] == "draft"
    assert [i for i in d["readiness"] if i["severity"] == "error"] == []

    # Preview is available before publication and clearly not a credential.
    p = world.get("lecturer", f"/api/v1/achievements/{did}/preview").json()
    assert p["preview"] is True and "NOT VERIFIABLE" in p["notice"]
    assert "proof" not in p["sample_credential"]
    assert p["sample_credential"]["id"].endswith("00000000-0000-0000-0000-000000000000")
    assert p["achievement"]["requirements"] == ["Complete the module “Writing Foundations”"]
    assert p["artwork"]["data_url"].startswith("data:image/svg+xml;base64,")
    assert p["example_verification_page"]["result"] == "preview_only"

    # Publication follows the configured workflow: review is required, no self-approval.
    assert world.post("lecturer", f"/api/v1/achievements/{did}/publish").status_code == 409
    assert world.post("lecturer", f"/api/v1/achievements/{did}/submit").json()["state"] == (
        "in_review"
    )
    assert world.patch("lecturer", f"/api/v1/achievements/{did}", {"title": "x"}).status_code == (
        409
    )
    r = world.post("lecturer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
    assert r.status_code == 403
    r = world.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": {}})
    assert r.json()["code"] == "CHECKLIST_INCOMPLETE"
    queue = world.get("reviewer", "/api/v1/achievements?review_queue=true").json()["items"]
    assert [i["id"] for i in queue] == [did]
    r = world.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
    assert r.status_code == 200 and r.json()["state"] == "approved"
    r = world.post("lecturer", f"/api/v1/achievements/{did}/publish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "published" and body["working_version"]["frozen"] is True
    assert body["live_version_id"] == body["working_version"]["id"]
    assert body["award_policy"] == "automatic"
    assert len(world.jobs("oc:evaluate_course")) == 1

    # The published version, and its rules, cannot be changed (spec §5.4, §12.3).
    vid = body["live_version_id"]
    with pytest.raises(psycopg.errors.Error):
        owner_conn.execute("UPDATE app.achievement_versions SET title = 'x' WHERE id = %s", [vid])
    owner_conn.rollback()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        owner_conn.execute(
            "UPDATE app.award_rules SET params = '{}' WHERE rule_set_id IN"
            " (SELECT id FROM app.award_rule_sets WHERE version_id = %s)",
            [vid],
        )
    owner_conn.rollback()

    # A substantive change is a new version; v1 stays live until v2 is published.
    r = world.post("lecturer", f"/api/v1/achievements/{did}/new-version")
    assert r.json()["state"] == "draft" and r.json()["working_version"]["version_no"] == 2
    assert r.json()["live_version_id"] == vid
    with world.db() as db:
        audit = db.scalars(
            select(m.AuditEvent.action).where(m.AuditEvent.resource_id.is_not(None))
        ).all()
    for action in (
        "achievement.create",
        "achievement.submit",
        "achievement.approve",
        "achievement.publish",
        "achievement.new_version",
    ):
        assert action in audit


def test_reject_returns_to_draft_and_review_checks(world: World) -> None:
    world.sync()
    did = world.draft(MODULE_RULES)["id"]
    world.post("lecturer", f"/api/v1/achievements/{did}/submit")
    r = world.post(
        "reviewer", f"/api/v1/achievements/{did}/reject", {"comment": "Clarify the outcomes."}
    )
    assert r.status_code == 200 and r.json()["state"] == "draft"
    assert r.json()["reviews"][-1]["decision"] == "reject"
    # Editing is possible again and a resubmission goes back to review.
    assert (
        world.patch(
            "lecturer",
            f"/api/v1/achievements/{did}",
            {"learning_outcomes": ["Structure an argument", "Reference sources"]},
        ).status_code
        == 200
    )
    assert world.post("lecturer", f"/api/v1/achievements/{did}/submit").json()["state"] == (
        "in_review"
    )


def test_completion_badge_cannot_claim_competency(world: World) -> None:
    world.sync()
    did = world.draft(MODULE_RULES, category="Competency", demonstration_kind="attending")["id"]
    r = world.post("lecturer", f"/api/v1/achievements/{did}/submit")
    assert r.status_code == 422
    assert "COMPETENCY_MISMATCH" in {e["code"] for e in r.json()["errors"]}


def test_credit_wording_needs_reviewer_approval(world: World) -> None:
    world.sync()
    did = world.draft(MODULE_RULES, short_description="Worth 5 CATS credits towards your degree.")[
        "id"
    ]
    warnings = world.post("lecturer", f"/api/v1/achievements/{did}/submit").json()["warnings"]
    assert "CREDIT_TERMS" in {w["code"] for w in warnings}
    world.post("reviewer", f"/api/v1/achievements/{did}/approve", {"checklist": CHECKLIST})
    r = world.post("lecturer", f"/api/v1/achievements/{did}/publish")
    assert r.status_code == 422 and r.json()["code"] == "NOT_PUBLISHABLE"


def test_rules_are_checked_against_canvas(world: World) -> None:
    world.sync()
    rules = {
        "mode": "ALL",
        "rules": [
            {"type": "module_completed", "module_id": "m-noreq"},
            {"type": "module_completed", "module_id": "gone"},
        ],
    }
    did = world.draft(rules)["id"]
    codes = {
        e["code"]
        for e in world.post("lecturer", f"/api/v1/achievements/{did}/submit").json()["errors"]
    }
    assert codes == {"MODULE_HAS_NO_REQUIREMENTS", "RULE_SOURCE_MISSING"}


def test_issuer_must_be_delegated_and_outsiders_are_refused(world: World) -> None:
    body = {
        "issuer_id": str(world.issuer_id),
        "course_id": str(world.course_id),
        "fields": {"title": "x"},
    }
    assert world.post("outsider", "/api/v1/achievements", body).status_code == 403
    assert world.post("s1", "/api/v1/achievements", body).status_code == 403
    did = world.draft(MODULE_RULES)["id"]
    assert world.get("outsider", f"/api/v1/achievements/{did}").status_code == 404
    assert world.get("s1", f"/api/v1/achievements/{did}").status_code == 404


def test_malicious_svg_upload_is_sanitised(world: World) -> None:
    import base64

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)">'
        b'<script>alert(2)</script><circle r="4"/></svg>'
    )
    r = world.post(
        "lecturer",
        "/api/v1/assets",
        {
            "media_type": "image/svg+xml",
            "data_base64": base64.b64encode(svg).decode(),
            "alt_text": "A dot",
        },
    )
    assert r.status_code == 201
    stored = base64.b64decode(r.json()["data_url"].split(",", 1)[1])
    assert b"script" not in stored and b"onload" not in stored
    assert r.json()["warnings"]
    content = world.get("lecturer", f"/api/v1/assets/{r.json()['id']}/content")
    assert "sandbox" in content.headers["content-security-policy"]
    missing_alt = world.post(
        "lecturer",
        "/api/v1/assets",
        {
            "media_type": "image/svg+xml",
            "data_base64": base64.b64encode(svg).decode(),
            "alt_text": " ",
        },
    )
    assert missing_alt.json()["code"] == "ALT_TEXT_REQUIRED"


# ---- Scenario 2: student completes requirements ----


def test_scenario_2_completion_records_eligibility_and_requests_issuance(world: World) -> None:
    world.publish(MODULE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    counts = world.sync_and_evaluate()
    assert counts == {"evaluated": 3, "met": 1, "decisions": 1}

    ev = world.evaluations("s1")[-1]
    assert ev.outcome == "met" and ev.triggered_by == "sync"
    rule = ev.detail["rules"][0]
    assert rule["explanation_code"] == "MODULE_COMPLETED"
    assert rule["source"]["canvas_module_id"] == "m1" and rule["source"]["fetched_at"]
    assert world.evaluations("s2")[-1].outcome == "not_met"

    (decision,) = world.decisions()
    assert (decision.kind, decision.status) == ("automatic", "ready")
    assert decision.user_id == world.users["s1"] and decision.evaluation_id == ev.id
    assert decision.issuer_id == world.issuer_id
    jobs = world.jobs(ISSUE)
    assert len(jobs) == 1 and jobs[0]["args"]["decision_id"] == str(decision.id)
    assert jobs[0]["args"]["subject_type"] == "award_decision"

    mine = world.get("s1", "/api/v1/learners/me/achievements").json()
    assert mine[0]["status"] == "awarded" and mine[0]["requirements"][0]["confirmed"] is True
    other = world.get("s2", "/api/v1/learners/me/achievements").json()
    assert other[0]["status"] == "in_progress"
    assert other[0]["requirements"][0]["label"] == "Not yet complete"


# ---- Scenario 3: duplicate event ----


def test_scenario_3_duplicate_events_create_nothing_new(world: World, owner_conn) -> None:  # type: ignore[no-untyped-def]
    world.publish(MODULE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.sync_and_evaluate()
    first = world.evaluations("s1")
    for _ in range(3):  # the same completion "event" processed again
        world.sync_and_evaluate()
        world.evaluate()
    assert len(world.decisions()) == 1
    assert len(world.jobs(ISSUE)) == 1
    assert len(world.evaluations("s1")) == len(first)  # unchanged inputs: no new history rows

    # Even a racing writer cannot add a second live decision (spec §6.6).
    (d,) = world.decisions()
    with pytest.raises(psycopg.errors.UniqueViolation):
        owner_conn.execute(
            "INSERT INTO app.award_decisions (id, institution_id, version_id, user_id, issuer_id,"
            " kind, justification, decided_at, status, issuance_seq, idempotency_key)"
            " VALUES (gen_random_uuid(), %s, %s, %s, %s, 'manual', 'race', now(), 'ready', 1,"
            " 'another-key')",
            [d.institution_id, d.version_id, d.user_id, d.issuer_id],
        )
    owner_conn.rollback()


# ---- Scenario 4: incomplete grade ----


@pytest.mark.parametrize(
    ("submission", "code", "label"),
    [
        (
            {"workflow_state": "graded", "score": 18.0, "posted_at": None},
            "AWAITING_RELEASE",
            "Awaiting published result",
        ),
        ({"workflow_state": "submitted", "score": None}, "AWAITING_GRADE", "Awaiting marking"),
        (
            {"workflow_state": "graded", "excused": True, "submitted_at": None},
            "EXCUSED",
            "Excused: course staff will decide",
        ),
    ],
)
def test_scenario_4_missing_or_unreleased_grade_stays_pending(
    world: World, submission: dict, code: str, label: str
) -> None:
    world.sync()
    body = world.publish(SCORE_RULES)
    assert body["award_policy"] == "lecturer_confirmed"  # institution default for score badges
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.lms.set_submission(COURSE_REF, "lms-s1", "a1", **submission)
    world.sync_and_evaluate()

    ev = world.evaluations("s1")[-1]
    assert ev.outcome == "unknown"
    assert [r["explanation_code"] for r in ev.detail["rules"]] == ["MODULE_COMPLETED", code]
    assert "score_percent" not in ev.detail["rules"][1]["source"]
    assert world.decisions() == [] and world.jobs(ISSUE) == []

    (badge,) = world.get("s1", "/api/v1/learners/me/achievements").json()
    assert badge["status"] == "pending"
    assert badge["progress"] == {"completed": 1, "total": 2, "mode": "ALL"}
    req = badge["requirements"][1]
    assert req["status"] == "pending" and req["confirmed"] is False and req["label"] == label

    staff = world.get("lecturer", f"/api/v1/courses/{world.course_id}/progress").json()
    row = next(r for r in staff["learners"] if r["user_id"] == str(world.users["s1"]))
    assert row["cells"][0]["outcome"] == "unknown" and code in row["cells"][0]["codes"]


def test_released_grade_then_lecturer_confirmation(world: World) -> None:
    world.sync()
    world.publish(SCORE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.lms.set_submission(
        COURSE_REF, "lms-s1", "a1", workflow_state="graded", score=15.0, posted_at=datetime.now(UTC)
    )
    world.sync_and_evaluate()
    (decision,) = world.decisions()
    assert decision.status == "awaiting_confirmation" and world.jobs(ISSUE) == []

    queue = world.get("lecturer", "/api/v1/awards").json()
    assert [q["id"] for q in queue] == [str(decision.id)]
    assert queue[0]["current_eligibility"]["outcome"] == "met"

    # The mark is lowered before the lecturer confirms: confirmation is refused.
    world.lms.set_submission(COURSE_REF, "lms-s1", "a1", score=10.0)
    world.sync()
    r = world.post("lecturer", f"/api/v1/awards/{decision.id}/confirm", {})
    assert r.status_code == 409 and r.json()["code"] == "ELIGIBILITY_CHANGED"

    world.lms.set_submission(COURSE_REF, "lms-s1", "a1", score=16.0)
    world.sync()
    r = world.post("lecturer", f"/api/v1/awards/{decision.id}/confirm", {})
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert len(world.jobs(ISSUE)) == 1
    again = world.post("lecturer", f"/api/v1/awards/{decision.id}/confirm", {})
    assert again.status_code == 200 and len(world.jobs(ISSUE)) == 1  # idempotent


def test_badge_can_choose_automatic_unless_institution_forces_confirmation(client) -> None:  # type: ignore[no-untyped-def]
    for force, expected in ((False, "automatic"), (True, "lecturer_confirmed")):
        w = build_world(client, policy={"score_rules_force_confirmation": force})
        with registry.override(w.lms):
            w.sync()
            body = w.publish(SCORE_RULES, award_policy="automatic")
        assert body["award_policy"] == expected


def test_stale_or_failed_canvas_data_never_issues(world: World) -> None:
    world.publish(MODULE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.lms.failures[("modules",)] = LmsTransientError("Canvas returned 503")
    with pytest.raises(LmsTransientError):
        world.sync()  # bounded retry happens in the queue; the failure is recorded
    world.evaluate()
    assert world.evaluations("s1")[-1].detail["rules"][0]["explanation_code"] == "DATA_NOT_SYNCED"
    assert world.decisions() == []

    world.lms.failures.clear()
    world.lms.failures[("progress", "lms-s1")] = __import__(
        "opencredential.integrations.base", fromlist=["x"]
    ).LmsPermissionError("forbidden")
    world.sync_and_evaluate()
    assert world.evaluations("s1")[-1].detail["rules"][0]["explanation_code"] == "DATA_UNAVAILABLE"
    assert world.decisions() == []

    # Snapshot older than the institution's maximum age: unknown, not met.
    world.lms.failures.clear()
    world.sync()
    with world.db() as db:
        for p in db.scalars(select(m.LmsModuleProgress)):
            p.fetched_at = datetime.now(UTC) - timedelta(hours=5)
    world.evaluate()
    assert world.evaluations("s1")[-1].detail["rules"][0]["explanation_code"] == "DATA_STALE"
    assert world.decisions() == []


def test_canvas_change_pauses_affected_badges(world: World) -> None:
    world.sync()
    world.publish(MODULE_RULES)
    del world.lms.course(COURSE_REF).modules["m1"]
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    result = world.sync()
    assert len(result["flagged_rules"]) == 1
    world.evaluate()
    assert world.evaluations("s1")[-1].detail["rules"][0]["explanation_code"] == (
        "RULE_SOURCE_MISSING"
    )
    assert world.decisions() == []
    with world.db() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.action == "rule.source_flagged")
            )
            == 1
        )


# ---- Scenario 5: manual award ----


def test_scenario_5_manual_award_with_justification(world: World) -> None:
    body = world.publish(
        {"mode": "ALL", "rules": [{"type": "manual_approval"}]},
        title="Seminar Participation",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )
    did = body["id"]
    award = {"definition_id": did, "user_id": str(world.users["s2"]), "justification": "Good."}
    r = world.post("lecturer", "/api/v1/awards/manual", award)
    assert r.status_code == 422 and r.json()["code"] == "JUSTIFICATION_REQUIRED"
    assert world.post("s1", "/api/v1/awards/manual", award).status_code == 403

    award["justification"] = "Contributed to six of eight seminars, observed by the tutor."
    award["evidence"] = [{"kind": "lecturer_confirmation", "narrative": "Seminar register"}]
    r = world.post("lecturer", "/api/v1/awards/manual", award)
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["kind"], d["status"]) == ("manual", "ready")
    assert d["justification"] == award["justification"] and d["evidence"][0]["kind"] == (
        "lecturer_confirmation"
    )
    assert d["decided_by"] == str(world.users["lecturer"]) and d["decided_at"]
    assert len(world.jobs(ISSUE)) == 1

    # Replaying the same request is idempotent; a different second award is refused.
    assert world.post("lecturer", "/api/v1/awards/manual", award).json()["id"] == d["id"]
    award["justification"] = "A different justification for the same learner."
    assert world.post("lecturer", "/api/v1/awards/manual", award).json()["code"] == (
        "ALREADY_AWARDED"
    )
    assert len(world.jobs(ISSUE)) == 1
    with world.db() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.action == "award.manual")
            )
            == 1
        )


def test_second_approval_policy_for_manual_awards(client) -> None:  # type: ignore[no-untyped-def]
    w = build_world(client, policy={"manual_awards_require_second_approval": True})
    with registry.override(w.lms):
        did = w.publish(
            {"mode": "ALL", "rules": [{"type": "manual_approval"}]},
            category="Participation",
            demonstration_kind="participating",
            award_policy="manual",
        )["id"]
        r = w.post(
            "lecturer",
            "/api/v1/awards/manual",
            {
                "definition_id": did,
                "user_id": str(w.users["s1"]),
                "justification": "Led the group presentation preparation sessions.",
            },
        )
        assert r.json()["status"] == "awaiting_confirmation" and w.jobs(ISSUE) == []
        same = w.post("lecturer", f"/api/v1/awards/{r.json()['id']}/confirm", {})
        assert same.json()["code"] == "SECOND_APPROVER_REQUIRED"
        ok = w.post("reviewer", f"/api/v1/awards/{r.json()['id']}/confirm", {})
        assert ok.json()["status"] == "ready" and len(w.jobs(ISSUE)) == 1


def test_lecturer_confirms_a_requirement_rule_e(world: World) -> None:
    body = world.publish(
        {
            "mode": "ALL",
            "rules": [
                {"type": "module_completed", "module_id": "m1"},
                {"type": "manual_approval", "instructions": "Attend the viva"},
            ],
        }
    )
    rule_id = body["rules"]["rules"][1]["id"]
    world.lms.complete_module(COURSE_REF, "lms-s3", "m1")
    world.sync_and_evaluate()
    assert world.evaluations("s3")[-1].outcome == "unknown"
    (badge,) = world.get("s3", "/api/v1/learners/me/achievements").json()
    assert badge["requirements"][1]["label"] == "Awaiting confirmation by course staff"
    r = world.post(
        "lecturer",
        f"/api/v1/achievements/{body['id']}/approvals",
        {"user_id": str(world.users["s3"]), "rule_id": rule_id, "decision": "approve"},
    )
    assert r.status_code == 200 and r.json()["outcome"] == "met"
    assert r.json()["decision_status"] == "ready" and len(world.jobs(ISSUE)) == 1


# ---- job reliability ----


def test_failed_jobs_are_visible_and_retryable_per_tenant(world: World, client, owner_conn) -> None:  # type: ignore[no-untyped-def]
    world.publish(MODULE_RULES)
    (job,) = world.jobs("oc:evaluate_course")
    owner_conn.execute("SET search_path TO app, jobs, public")
    owner_conn.execute(
        "UPDATE jobs.procrastinate_jobs SET status = 'failed' WHERE id = %s", [job["id"]]
    )
    owner_conn.commit()
    failed = world.get("admin", "/api/v1/admin/jobs").json()
    assert [j["id"] for j in failed] == [job["id"]]
    assert world.get("lecturer", "/api/v1/admin/jobs").status_code == 403
    other = build_world(client)
    assert other.post("admin", f"/api/v1/admin/jobs/{job['id']}/retry").status_code == 404
    r = world.post("admin", f"/api/v1/admin/jobs/{job['id']}/retry")
    assert r.status_code == 200
    status = owner_conn.execute(
        "SELECT status FROM jobs.procrastinate_jobs WHERE id = %s", [job["id"]]
    ).fetchone()[0]
    assert status == "todo"


def test_institution_default_policy_is_admin_only(world: World) -> None:
    assert (
        world.patch(
            "lecturer",
            "/api/v1/institutions/current/policy",
            {"score_rules_default_policy": "automatic"},
        ).status_code
        == 403
    )
    r = world.patch(
        "admin", "/api/v1/institutions/current/policy", {"score_rules_default_policy": "automatic"}
    )
    assert r.json()["score_rules_default_policy"] == "automatic"
    world.sync()
    assert world.publish(SCORE_RULES)["award_policy"] == "automatic"
