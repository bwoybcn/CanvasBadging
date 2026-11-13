# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain errors raised by services and mapped to RFC 9457 problems by the API layer."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """A refusal with a stable machine-readable ``code`` and an actionable message."""

    status = 400

    def __init__(
        self,
        code: str,
        title: str,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(title)
        self.code, self.title, self.detail, self.errors = code, title, detail, errors
        if status is not None:
            self.status = status


class NotFound(DomainError):
    status = 404


class Forbidden(DomainError):
    status = 403


class Conflict(DomainError):
    status = 409


class Invalid(DomainError):
    status = 422


class RateLimited(DomainError):
    status = 429
