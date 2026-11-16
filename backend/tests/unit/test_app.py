# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import uuid

from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.paths import REPO_DIR
from opencredential.settings import Settings

STRONG = "s" * 48


def _paths(app) -> set[str]:  # type: ignore[no-untyped-def]
    return set(app.openapi()["paths"])


def test_healthz() -> None:
    with TestClient(create_app(Settings(env="test"))) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dev_login_routes_absent_in_production() -> None:
    prod = create_app(
        Settings(
            env="production",
            secret_key=STRONG,
            signer_shared_secret=STRONG,
            token_encryption_key=STRONG,
        )
    )
    dev = create_app(Settings(env="development"))
    assert "/dev/login" in _paths(dev)
    assert not any(p.startswith("/dev") for p in _paths(prod))


def test_unauthenticated_is_problem_json_with_request_id() -> None:
    rid = str(uuid.uuid4())
    with TestClient(create_app(Settings(env="test"))) as client:
        r = client.get("/api/v1/learners/me", headers={"x-request-id": rid})
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["x-request-id"] == rid
    body = r.json()
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"] == rid


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app(Settings(env="test"))) as client:
        r = client.get("/healthz", headers={"x-request-id": "not-a-uuid"})
    assert uuid.UUID(r.headers["x-request-id"]).version == 7


def test_openapi_snapshot_is_current() -> None:
    """docs/api/openapi.json must match the code. Regenerate: ``oc openapi --out ...``."""
    snapshot = REPO_DIR / "docs" / "api" / "openapi.json"
    current = create_app(Settings(env="development")).openapi()
    assert json.loads(snapshot.read_text()) == json.loads(json.dumps(current)), (
        "OpenAPI changed: run `uv run oc openapi --out ../docs/api/openapi.json` and review"
    )


def test_generated_typescript_types_are_current() -> None:
    """frontend/src/api.gen.ts must match the code. Regenerate: ``oc api-types --out ...``."""
    from opencredential.api.typescript import render

    generated = REPO_DIR / "frontend" / "src" / "api.gen.ts"
    current = create_app(Settings(env="development")).openapi()
    assert generated.read_text() == render(current), (
        "The API changed: run `uv run oc api-types --out ../frontend/src/api.gen.ts` and review"
    )
