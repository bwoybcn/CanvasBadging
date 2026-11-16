# SPDX-License-Identifier: AGPL-3.0-or-later
"""A refused form says which field and what limit (product review, 14 Nov 2026).

The screens turn a 422's ``errors`` into sentences such as "Short description is too long: use
up to 280 characters". These tests pin what they rely on: the path of the field, a stable code,
and the number behind the limit in ``limits``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.world import World, build_world

pytestmark = pytest.mark.db


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


def _errors(r: Any) -> dict[str, dict[str, Any]]:
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "VALIDATION_FAILED"
    return {e["field"]: e for e in body["errors"]}


def test_a_refused_draft_names_each_field_and_its_limit(world: World) -> None:
    r = world.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(world.issuer_id),
            "course_id": str(world.course_id),
            "fields": {
                "title": "T" * 121,
                "short_description": "S" * 281,
                "validity_days": 0,
                "learning_outcomes": ["x"] * 13,
            },
        },
    )
    errors = _errors(r)
    short = errors["body.fields.short_description"]
    assert short["code"] == "string_too_long"
    assert short["limits"] == {"max_length": 280}
    assert errors["body.fields.title"]["limits"] == {"max_length": 120}
    assert errors["body.fields.validity_days"]["code"] == "greater_than_equal"
    assert errors["body.fields.validity_days"]["limits"] == {"ge": 1}
    outcomes = errors["body.fields.learning_outcomes"]
    assert outcomes["code"] == "too_long"
    assert outcomes["limits"]["max_length"] == 12


def test_a_missing_field_has_no_limits_and_nothing_unserialisable(world: World) -> None:
    errors = _errors(world.post("lecturer", "/api/v1/achievements", {"fields": {}}))
    missing = errors["body.issuer_id"]
    assert missing["code"] == "missing"
    assert "limits" not in missing


def test_brand_colours_must_be_colours(world: World) -> None:
    errors = _errors(
        world.patch(
            "admin",
            "/api/v1/institutions/current",
            {"branding": {"primary_colour": "navy; background:url(x)"}},
        )
    )
    assert errors["body.branding.primary_colour"]["code"] == "string_pattern_mismatch"
    ok = world.patch(
        "admin",
        "/api/v1/institutions/current",
        {"branding": {"primary_colour": "#212B58", "secondary_colour": None}},
    )
    assert ok.status_code == 200, ok.text
