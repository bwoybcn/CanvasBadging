# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deferring jobs from anywhere (api requests, other jobs) without managing app lifecycles."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued, AppNotOpen

from opencredential.jobs.app import build_app


@lru_cache
def _app() -> procrastinate.App:
    return build_app().open()


def defer(
    task: str,
    *,
    lock: str | None = None,
    schedule_in: dict[str, int] | None = None,
    **kwargs: Any,
) -> int | None:
    """Queue ``oc:<task>``. Returns the job id, or ``None`` if an identical job is queued.

    The procrastinate app is a process-wide singleton (``jobs.app.build_app``); if something
    else (a worker run, a test) closed it after we opened it, open it again once.
    """
    for attempt in (1, 2):
        try:
            return (
                _app()
                .configure_task(f"oc:{task}", queueing_lock=lock, schedule_in=schedule_in)
                .defer(**kwargs)
            )
        except AlreadyEnqueued:
            return None
        except AppNotOpen:
            if attempt == 2:
                raise
            _app.cache_clear()
    return None


def reset() -> None:
    """Close the cached app (tests switch databases)."""
    if _app.cache_info().currsize:
        _app().close()
    _app.cache_clear()
