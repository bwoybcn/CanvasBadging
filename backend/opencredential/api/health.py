# SPDX-License-Identifier: AGPL-3.0-or-later
"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Any

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from opencredential import __version__
from opencredential.api.deps import SettingsDep
from opencredential.db.session import app_engine
from opencredential.paths import ALEMBIC_INI

router = APIRouter(tags=["health"])


def expected_revision() -> str | None:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Process is up. Does not touch dependencies."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz(settings: SettingsDep) -> JSONResponse:
    """Ready to serve: database reachable, schema at the expected revision, signer up."""
    checks: dict[str, Any] = {}
    try:
        with app_engine().connect() as conn:
            conn.execute(text("select 1"))
            current = conn.execute(text("select version_num from app.alembic_version")).scalar()
        head = expected_revision()
        checks["database"] = "ok"
        checks["migrations"] = "ok" if current == head else f"at {current}, expected {head}"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        checks["migrations"] = "unknown"
    try:
        r = httpx.get(f"{settings.signer_url}/healthz", timeout=2.0)
        checks["signer"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except httpx.HTTPError as exc:
        checks["signer"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status_code=200 if ok else 503,
    )
