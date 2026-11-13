# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured logging (structlog) with request correlation ids."""

from __future__ import annotations

import logging
import sys

import structlog

_SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "private_key", "id_token"}


def _scrub(_logger: object, _method: str, event_dict: dict) -> dict:
    for key in list(event_dict):
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    return structlog.get_logger(name)
