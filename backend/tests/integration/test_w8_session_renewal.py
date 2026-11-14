# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keeping a session alive while someone is working (``POST /api/v1/session/renew``).

Product review, 14 Nov 2026: the create-badge wizard lost up to half an hour of typing because a
session ended 30 minutes after the Canvas launch whatever the person was doing. The app now swaps
a still-valid token for a fresh one while the person is active. These tests pin the limits: only a
valid token can be renewed, an inactive account never gets one, and no session outlives
``session_max_minutes`` from its launch.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db

RENEW = "/api/v1/session/renew"


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


def _bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _token(
    world: World, who: str, *, started_at: datetime | None = None, now: datetime | None = None
) -> str:
    token, _ = sessions.issue(
        get_settings(),
        user_id=world.users[who],
        institution_id=world.iid,
        method="lti",
        course_id=world.course_id,
        started_at=started_at,
        now=now,
    )
    return token


def test_a_valid_session_is_swapped_for_a_fresh_one(world: World) -> None:
    settings = get_settings()
    # Twenty minutes into a session: the token has ten minutes left.
    started = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=20)
    old = _token(world, "lecturer", started_at=started, now=started)
    r = world.client.post(RENEW, headers=_bearer(old))
    assert r.status_code == 200, r.text
    body = r.json()

    before, after = sessions.verify(settings, old), sessions.verify(settings, body["token"])
    assert (after.user_id, after.institution_id, after.course_id, after.method) == (
        before.user_id,
        before.institution_id,
        before.course_id,
        "lti",
    )
    assert after.started_at == started  # the clock on the whole session does not restart
    assert after.expires_at > before.expires_at + timedelta(minutes=15)
    assert datetime.fromisoformat(body["renewable_until"]) == started + timedelta(
        minutes=settings.session_max_minutes
    )
    # The fresh token is an ordinary session: same person, same launch course.
    me = world.client.get("/api/v1/learners/me", headers=_bearer(body["token"]))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == str(world.users["lecturer"])
    assert me.json()["launch_course"]["id"] == str(world.course_id)


def test_an_expired_or_missing_token_cannot_be_renewed(world: World) -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    expired = _token(world, "lecturer", now=long_ago)
    r = world.client.post(RENEW, headers=_bearer(expired))
    assert (r.status_code, r.json()["code"]) == (401, "SESSION_INVALID")
    assert world.client.post(RENEW).status_code == 401


def test_a_session_cannot_be_kept_alive_past_its_limit(world: World) -> None:
    settings = get_settings()
    # Ten minutes before the limit a token is cut off at the limit...
    started = datetime.now(UTC).replace(microsecond=0) - timedelta(
        minutes=settings.session_max_minutes - 10
    )
    limit = started + timedelta(minutes=settings.session_max_minutes)
    last = _token(world, "lecturer", started_at=started)
    assert sessions.verify(settings, last).expires_at == limit
    # ...and a token that already runs to the limit gets nothing more.
    r = world.client.post(RENEW, headers=_bearer(last))
    assert (r.status_code, r.json()["code"]) == (401, "SESSION_TOO_OLD")
    assert "Canvas" in r.json()["detail"]


def test_an_erased_account_cannot_renew(world: World) -> None:
    token = _token(world, "s1")
    assert world.client.post(RENEW, headers=_bearer(token)).status_code == 200
    r = world.post("admin", f"/api/v1/admin/people/{world.users['s1']}/erase", {"confirm": "ERASE"})
    assert r.status_code == 200, r.text
    r = world.client.post(RENEW, headers=_bearer(token))
    assert (r.status_code, r.json()["code"]) == (401, "ACCOUNT_INACTIVE")
