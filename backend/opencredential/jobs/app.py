# SPDX-License-Identifier: AGPL-3.0-or-later
"""The procrastinate application shared by the api (to defer) and the worker (to run).

Tasks are declared on a :class:`procrastinate.Blueprint` (``jobs.tasks``) so the app can be
built lazily from the current settings.
"""

from __future__ import annotations

from functools import lru_cache

import procrastinate

from opencredential.db.session import SEARCH_PATH
from opencredential.settings import get_settings


def _conninfo(url: str) -> str:
    # SQLAlchemy URL -> libpq URL
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def build_app() -> procrastinate.App:
    from opencredential.jobs.tasks import blueprint

    connector = procrastinate.PsycopgConnector(
        conninfo=_conninfo(get_settings().database_url),
        kwargs={"options": f"-c search_path={SEARCH_PATH}"},
    )
    app = procrastinate.App(connector=connector)
    app.add_tasks_from(blueprint, namespace="oc")
    return app


@lru_cache
def get_app() -> procrastinate.App:
    return build_app()
