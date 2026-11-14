# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for the lower-priority findings of the 13 Nov 2026 review.

See docs/reports/code-review-2026-11-13.md:

* C5: the stale-data guard stays on however many syncs fail in a row.
* C6: a rejected manual award does not block a corrected one.
* C7: the lecturer's awards list is filtered in SQL, so other courses cannot crowd it out.
* C8: destroyed keys are recorded, audited and never sent to the signer again.
* C9: eligibility builds decisions through ``issuance.decisions`` only.
* S3: a verification host belongs to one institution, and local DID answers respect it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.eligibility import service as eligibility
from opencredential.eligibility.snapshots import load_course
from opencredential.institutions import keys as key_service
from opencredential.integrations import registry
from opencredential.integrations.base import LmsTransientError
from opencredential.issuance import decisions
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from opencredential.verification.sources import known_issuer_local, local_did_document
from tests.integration.w4_factory import build_tenant
from tests.integration.w5_world import COURSE_REF, World, build_world

pytestmark = pytest.mark.db

MODULE_RULES = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}
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
        yield w


def _publish_manual(w: World) -> str:
    return str(
        w.publish(
            MANUAL_RULES,
            title="Seminar Participation",
            category="Participation",
            demonstration_kind="participating",
            award_policy="manual",
        )["id"]
    )


# ---- C5 ---------------------------------------------------------------------------------------


def test_c5_many_failed_syncs_keep_the_stale_data_guard_on(world: World) -> None:
    world.publish(MODULE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.sync()  # a good run that says s1 completed m1; not evaluated yet

    world.lms.failures[("modules",)] = LmsTransientError("Canvas returned 429")
    for _ in range(7):  # more failures than the old five-run window
        with pytest.raises(LmsTransientError):
            world.sync()
    with world.db() as db:
        assert db.scalar(select(func.count()).select_from(m.SyncRun)) == 8
        assert load_course(db, world.course_id).failed == {"*": ["modules", "submissions"]}

    world.evaluate()
    code = world.evaluations("s1")[-1].detail["rules"][0]["explanation_code"]
    assert code == "DATA_UNAVAILABLE"
    assert world.decisions() == []

    # Once Canvas answers again the award goes ahead.
    world.lms.failures.clear()
    world.sync_and_evaluate()
    assert [d.user_id for d in world.decisions()] == [world.users["s1"]]


# ---- C6 / C9 ----------------------------------------------------------------------------------


def test_c6_rejected_manual_award_does_not_block_a_corrected_one(client: TestClient) -> None:
    w = build_world(client, policy={"manual_awards_require_second_approval": True})
    with registry.override(w.lms):
        did = _publish_manual(w)
        award = {
            "definition_id": did,
            "user_id": str(w.users["s1"]),
            "justification": "Led the group presentation preparation sessions.",
        }
        first = w.post("lecturer", "/api/v1/awards/manual", award)
        assert first.status_code == 201, first.text
        r = w.post(
            "reviewer",
            f"/api/v1/awards/{first.json()['id']}/reject",
            {"reason": "Wrong learner: it was the other group."},
        )
        assert r.json()["status"] == "rejected"

        award["justification"] = "Led the presentation sessions; register checked again."
        second = w.post("lecturer", "/api/v1/awards/manual", award)
        assert second.status_code == 201, second.text
        assert second.json()["id"] != first.json()["id"]
        assert second.json()["status"] == "awaiting_confirmation"
        # Replaying the corrected award is still idempotent.
        again = w.post("lecturer", "/api/v1/awards/manual", award)
        assert again.json()["id"] == second.json()["id"]

        # Reject that one too: a third attempt still works and gets its own key.
        w.post("reviewer", f"/api/v1/awards/{second.json()['id']}/reject", {"reason": "Not yet."})
        award["justification"] = "Third attempt with the signed seminar register attached."
        third = w.post("lecturer", "/api/v1/awards/manual", award)
        assert third.status_code == 201, third.text

        with w.db() as db:
            rows = list(db.scalars(select(m.AwardDecision).order_by(m.AwardDecision.decided_at)))
            version_id = rows[0].version_id
        keys = [
            decisions.idempotency_key(w.iid, w.users["s1"], version_id, "manual", 1, attempt)
            for attempt in (0, 1, 2)
        ]
        assert [r.idempotency_key for r in rows] == keys
        assert [r.status for r in rows] == ["rejected", "rejected", "awaiting_confirmation"]


def test_c9_eligibility_uses_the_single_decision_module(world: World) -> None:
    assert not hasattr(eligibility, "idempotency_key")
    assert not hasattr(eligibility, "_insert_decision")
    # Attempt 0 keeps the original key format, so existing decisions keep their keys.
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    import hashlib

    legacy = hashlib.sha256(f"{a}|{b}|{c}|automatic|1".encode()).hexdigest()
    assert decisions.idempotency_key(a, b, c, "automatic") == legacy

    world.publish(MODULE_RULES)
    world.lms.complete_module(COURSE_REF, "lms-s1", "m1")
    world.sync_and_evaluate()
    world.evaluate()  # replay: still one decision
    (d,) = world.decisions()
    assert d.idempotency_key == decisions.idempotency_key(
        world.iid, world.users["s1"], d.version_id, "automatic"
    )
    with world.db() as db:
        actions = set(db.scalars(select(m.AuditEvent.action)))
    assert "award.ready" in actions and "award.decide" not in actions


# ---- C7 ---------------------------------------------------------------------------------------


def test_c7_awards_list_is_not_crowded_out_by_other_courses(world: World) -> None:
    did = _publish_manual(world)
    # The lecturer's own award, waiting for confirmation (made newest).
    with world.db() as db:
        definition = db.get(m.AchievementDefinition, uuid.UUID(did))
        assert definition is not None
        mine, _ = decisions.decide(
            db,
            institution_id=world.iid,
            user_id=world.users["s1"],
            version_id=definition.current_version_id,  # type: ignore[arg-type]
            kind="manual",
            justification="Presented the seminar summary to the class.",
            decided_by=world.users["lecturer"],
            status="awaiting_confirmation",
        )
        mine_id, version_id = mine.id, definition.current_version_id

    # Another course in the same institution with older awards waiting for confirmation.
    old = datetime.now(UTC) - timedelta(days=3)
    with owner_session() as db:
        src = db.get(m.AchievementVersion, version_id)
        assert src is not None
        course = m.Course(
            institution_id=world.iid,
            canvas_integration_id=db.scalar(
                select(m.CanvasIntegration.id).where(
                    m.CanvasIntegration.institution_id == world.iid
                )
            ),
            canvas_course_id="course-202",
            title="Other course",
            status="active",
        )
        db.add(course)
        db.flush()
        other_def = m.AchievementDefinition(
            institution_id=world.iid,
            issuer_id=world.issuer_id,
            owner_user_id=world.users["admin"],
            course_id=course.id,
            state="published",
            award_policy="manual",
        )
        db.add(other_def)
        db.flush()
        other_version = m.AchievementVersion(
            institution_id=world.iid,
            definition_id=other_def.id,
            version_no=1,
            title="Other badge",
            short_description=src.short_description,
            description=src.description,
            learning_outcomes=src.learning_outcomes,
            criteria_narrative=src.criteria_narrative,
            category=src.category,
            achievement_type=src.achievement_type,
            demonstration_kind=src.demonstration_kind,
            skills=[],
            published_at=old,
            published_by=world.users["admin"],
        )
        db.add(other_version)
        db.flush()
        other_version.frozen = True
        other_def.current_version_id = other_version.id
        other_version_id = other_version.id
    with world.db() as db:
        for who in ("s1", "s2", "s3"):
            decisions.decide(
                db,
                institution_id=world.iid,
                user_id=world.users[who],
                version_id=other_version_id,
                kind="manual",
                justification="Older award in a course this lecturer does not teach.",
                decided_by=world.users["admin"],
                status="awaiting_confirmation",
                now=old,
            )

    for limit in (1, 2, 100):
        r = world.get("lecturer", "/api/v1/awards", params={"limit": limit})
        assert r.status_code == 200, r.text
        assert [a["id"] for a in r.json()] == [str(mine_id)], limit
    # The institution admin still sees everything, oldest first.
    everything = world.get("admin", "/api/v1/awards").json()
    assert len(everything) == 4 and everything[-1]["id"] == str(mine_id)
    # A department admin over the course's org unit sees the lecturer's course only.
    dept = world.get("reviewer", "/api/v1/awards").json()
    assert [a["id"] for a in dept] == [str(mine_id)]


# ---- C8 ---------------------------------------------------------------------------------------


def _retire_long_ago(iid: uuid.UUID, key_id: uuid.UUID) -> None:
    with owner_session() as db:
        key = db.get(m.IssuerKey, key_id)
        assert key is not None
        key.state = "retired"
        key.retired_at = datetime.now(UTC) - timedelta(days=40)


def test_c8_retired_keys_are_destroyed_once_and_recorded(signer_available: bool) -> None:
    t = build_tenant(get_settings())
    _retire_long_ago(t.institution_id, t.key_id)
    with tenant_session(t.institution_id) as db:
        assert [k.id for k in key_service.keys_due_for_destruction(db)] == [t.key_id]

    tasks.destroy_retired_keys(0)

    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None and key.destroyed_at is not None
        assert key_service.keys_due_for_destruction(db) == []
        events = list(
            db.scalars(
                select(m.AuditEvent).where(
                    m.AuditEvent.action == "issuer_key.destroyed",
                    m.AuditEvent.resource_id == str(t.key_id),
                )
            )
        )
        assert len(events) == 1 and events[0].data["reason"] == "retired"
        first = key.destroyed_at

    tasks.destroy_retired_keys(0)  # the next night: nothing more for this key
    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None and key.destroyed_at == first
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.action == "issuer_key.destroyed")
            )
            == 1
        )


def test_c8_destruction_after_compromise_is_recorded(signer_available: bool) -> None:
    t = build_tenant(get_settings())
    meta = {"institution_id": str(t.institution_id)}
    tasks.signer_key_lifecycle(str(t.key_id), "destroy", **meta)
    tasks.signer_key_lifecycle(str(t.key_id), "destroy", **meta)  # retried job: idempotent
    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None and key.destroyed_at is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.action == "issuer_key.destroyed")
            )
            == 1
        )


# ---- S3 ---------------------------------------------------------------------------------------


def test_s3_a_verification_host_belongs_to_one_institution(client: TestClient) -> None:
    a, b = build_world(client), build_world(client)
    host = f"badges-{uuid.uuid4().hex[:6]}.example.ac.uk"
    path = "/api/v1/institutions/current"
    assert a.patch("admin", path, {"verification_host": host}).status_code == 200
    r = b.patch("admin", path, {"verification_host": host.upper()})
    assert r.status_code == 409 and r.json()["code"] == "VERIFICATION_HOST_TAKEN"
    assert b.get("admin", path).json()["verification_host"] is None
    # The owner can still save other settings with the same host.
    r = a.patch("admin", path, {"verification_host": host, "name": "Renamed University"})
    assert r.status_code == 200, r.text


def test_s3_local_did_answers_only_under_the_owning_host(signer_available: bool) -> None:
    host = f"badges-{uuid.uuid4().hex[:6]}.example.ac.uk"
    t = build_tenant(get_settings(), did_method="web", verification_host=host)
    assert local_did_document(t.did) is not None
    assert known_issuer_local(t.did) is not None

    # The institution's host no longer matches the issuer's DID: nothing is vouched for.
    with owner_session() as db:
        inst = db.get(m.Institution, t.institution_id)
        assert inst is not None
        inst.verification_host = f"elsewhere-{uuid.uuid4().hex[:6]}.example.ac.uk"
    assert local_did_document(t.did) is None
    assert known_issuer_local(t.did) is None
