# SPDX-License-Identifier: AGPL-3.0-or-later
"""RFC 9457 problem+json errors with stable machine-readable ``code`` values."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from opencredential.errors import DomainError

PROBLEM = "application/problem+json"


class ApiError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        self.status, self.code, self.title, self.detail = status, code, title, detail


def problem(
    request: Request,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://opencredential.dev/problems/{code.lower().replace('_', '-')}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


_STATUS_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def _field_error(e: Any) -> dict[str, Any]:
    """One entry of a 422's ``errors``: which field, why (``code``), and the limit it broke.

    ``limits`` carries the numbers behind the message (``max_length``, ``min_length``, ``ge``,
    ``le`` and so on), so a client can say "up to 280 characters" in its own words.
    """
    out: dict[str, Any] = {
        "field": ".".join(str(p) for p in e["loc"]),
        "code": e["type"],
        "message": e["msg"],
    }
    limits = {
        k: v
        for k, v in (e.get("ctx") or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if limits:
        out["limits"] = limits
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem(request, exc.status, exc.code, exc.title, exc.detail)

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return problem(request, exc.status, exc.code, exc.title, exc.detail, exc.errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return problem(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [_field_error(e) for e in exc.errors()]
        return problem(request, 422, "VALIDATION_FAILED", "Request validation failed", None, errors)
