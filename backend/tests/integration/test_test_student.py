# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas's Student View "Test Student" is never listed, synced or awarded (round 3, L5).

A launch with Canvas's test-user role marks the user ``is_test_user``. The user can still open
the tool as a student, but staff do not see them on progress lists or in the award picker, and
a manual award to them is refused like any non-student.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.db.models import User
from opencredential.db.session import tenant_session
from opencredential.eligibility.service import course_students
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.world import World, build_world

pytestmark = pytest.mark.db

MODULE_RULES = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}


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


def test_the_test_student_is_left_out_of_staff_lists(world: World) -> None:
    with tenant_session(world.iid) as db:
        user = db.get(User, world.users["s3"])
        assert user is not None
        user.is_test_user = True
    with tenant_session(world.iid) as db:
        students = set(course_students(db, world.course_id))
    assert world.users["s3"] not in students
    assert world.users["s1"] in students

    world.sync()
    world.publish(MODULE_RULES)
    progress = world.get("lecturer", f"/api/v1/courses/{world.course_id}/progress").json()
    listed = {r["user_id"] for r in progress["learners"]}
    assert str(world.users["s3"]) not in listed
    assert str(world.users["s1"]) in listed
