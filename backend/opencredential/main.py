# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI entrypoint: ``uvicorn opencredential.main:app``."""

from opencredential.api.app import create_app

app = create_app()
