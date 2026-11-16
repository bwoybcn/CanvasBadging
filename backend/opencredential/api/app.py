# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from opencredential import __version__
from opencredential.api import errors, health
from opencredential.api.middleware import RequestIdMiddleware
from opencredential.api.ratelimit import Limiter, RateLimitMiddleware
from opencredential.api.routes import (
    achievements,
    admin,
    assets,
    awards,
    canvas,
    collection,
    courses,
    credentials,
    dev,
    governance,
    learners,
    lti,
    session,
)
from opencredential.logging import configure_logging, get_logger
from opencredential.public import routes as public_routes
from opencredential.public import share as share_routes
from opencredential.settings import Settings, get_settings
from opencredential.startup import check_production_safety

log = get_logger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        check_production_safety(settings)
        log.info("startup", env=settings.env.value, dev_login=settings.dev_login_enabled)
        yield

    app = FastAPI(
        title="OpenCredential API",
        version=__version__,
        license_info={"name": "AGPL-3.0-or-later", "identifier": "AGPL-3.0-or-later"},
        lifespan=lifespan,
    )
    # Added first so the request-id middleware wraps it: a refused request still gets an id,
    # the security headers and a log line.
    app.add_middleware(
        RateLimitMiddleware,
        limiter=Limiter(
            {
                "verify": settings.rate_limit_verify_per_minute,
                "signin": settings.rate_limit_signin_per_minute,
            }
        ),
    )
    app.add_middleware(RequestIdMiddleware)
    errors.install(app)
    app.include_router(health.router)
    app.include_router(learners.router)
    app.include_router(session.router)
    for module in (achievements, assets, courses, awards, admin, governance, lti, canvas):
        app.include_router(module.router)
    app.include_router(collection.router)
    app.include_router(credentials.router)
    app.include_router(public_routes.router)
    app.include_router(share_routes.router)
    if settings.dev_login_enabled:
        app.include_router(dev.router)

    _mount_spa(app, settings)
    return app


def _mount_spa(app: FastAPI, settings: Settings) -> None:
    """Serve the built frontend at ``/app`` with client-side routing fallback."""
    if not settings.static_dir:
        return
    root = Path(settings.static_dir)
    if not (root / "index.html").is_file():
        log.warning("static_dir_missing", path=str(root))
        return
    app.mount("/app/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.get("/app/{path:path}", include_in_schema=False)
    def _spa(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
