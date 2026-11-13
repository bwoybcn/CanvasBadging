# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation against the official 1EdTech JSON Schema (ADR-0002, C-OB3-02).

The schema file ``schemas/ob_v3p0_achievementcredential_schema.json`` is pinned in the repository
(copied byte-for-byte from purl.imsglobal.org, SHA-256 recorded in ``schemas/README.md``) so
validation never depends on the network. Every credential is validated before it is signed, and
the verification service validates incoming credentials the same way.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft201909Validator, Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator

SCHEMA_DIR = Path(__file__).with_name("schemas")
ACHIEVEMENT_CREDENTIAL = SCHEMA_DIR / "ob_v3p0_achievementcredential_schema.json"


@lru_cache
def _validator() -> Validator:
    schema = json.loads(ACHIEVEMENT_CREDENTIAL.read_text(encoding="utf-8"))
    dialect = str(schema.get("$schema", ""))
    cls = Draft202012Validator if "2020-12" in dialect else Draft201909Validator
    return cls(schema, format_checker=FormatChecker())  # type: ignore[no-any-return]


def validate_achievement_credential(doc: dict[str, Any]) -> list[str]:
    """Return human-readable schema violations (empty when valid)."""
    errors = sorted(_validator().iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]
