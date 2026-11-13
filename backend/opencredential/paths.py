# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
REPO_DIR = BACKEND_DIR.parent
EXAMPLES_DIR = REPO_DIR / "examples"
