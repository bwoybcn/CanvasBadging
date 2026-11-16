# SPDX-License-Identifier: AGPL-3.0-or-later
"""Liveness and readiness probes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from opencredential.jobs import health as job_health
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


@router.get(
    "/healthz/jobs",
    summary="Background work: is a worker running, and has a job failed in the last day",
    responses={503: {"description": "No worker is running, or a job failed in the last 24 hours"}},
)
def jobs_health() -> JSONResponse:
    """For a monitoring tool to poll. Not for a load balancer: an API that cannot issue badges
    in the background can still serve pages, so ``/readyz`` does not look at this.

    Counts only, across the whole installation: no institution, course or person.
    """
    now = datetime.now(UTC)
    try:
        with app_engine().connect() as conn:
            state = job_health.snapshot(
                conn, since=now - timedelta(seconds=job_health.RECENT_FAILURE_SECONDS), now=now
            )
    except Exception as exc:
        return JSONResponse(
            {"status": "unavailable", "checks": {"database": f"error: {type(exc).__name__}"}},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    checks = {
        "worker": "ok" if state.worker_ok else "no worker has reported in the last two minutes",
        "failed_jobs": "ok"
        if state.failed_recent_count == 0
        else f"{state.failed_recent_count} failed in the last 24 hours",
    }
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {
            "status": "ok" if ok else "attention",
            "checks": checks,
            "failed_last_24_hours": state.failed_recent_count,
            "failed_waiting": state.failed_total,
        },
        status_code=200 if ok else 503,
        headers={"Cache-Control": "no-store"},
    )
