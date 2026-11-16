# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worker entrypoint: ``oc worker`` (same image as the api, different command)."""

from __future__ import annotations

from opencredential.jobs.app import get_app
from opencredential.logging import configure_logging
from opencredential.settings import get_settings
from opencredential.startup import check_production_safety


def run(queues: list[str] | None = None, wait: bool = True) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # The worker is what signs badges, so it makes the same check as the api before taking jobs.
    check_production_safety(settings)
    app = get_app()
    with app.open():
        app.run_worker(queues=queues, wait=wait, install_signal_handlers=wait)
