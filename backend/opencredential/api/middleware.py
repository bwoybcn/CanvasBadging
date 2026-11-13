# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request correlation id (``X-Request-ID``) bound into every log line."""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from opencredential.ids import uuid7
from opencredential.logging import get_logger

log = get_logger("http")


def _valid_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


# W8 hardening (spec §15.3, threat model T-XSS): baseline headers on every response. Routes that
# need something stricter (share pages, uploaded SVGs, status lists) set their own first, and
# setdefault leaves those alone.
SPA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'"
)


def _security_headers(request: Request, response: Response) -> None:
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        # The SPA runs inside Canvas's iframe, so no frame-ancestors restriction here; LTI
        # launches are bound to the browser that started them (ADR-0008) instead.
        h.setdefault("Content-Security-Policy", SPA_CSP)
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
    if forwarded == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _valid_uuid(request.headers.get("x-request-id")) or str(uuid7())
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Spec §8.4 and open question Q17: nothing this service serves is meant for search
        # engines, including pages a student chose to share. Sharing is not discovery.
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
        _security_headers(request, response)
        if not request.url.path.startswith(("/healthz", "/readyz")):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
            )
        return response
