# SPDX-License-Identifier: AGPL-3.0-or-later
"""Autogenerate filters shared by migrations/env.py and the schema-drift test."""

from __future__ import annotations

MANAGED_SCHEMAS = {"app"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    if type_ == "table":
        if getattr(obj, "info", {}).get("is_view"):
            return False
        if obj.schema not in MANAGED_SCHEMAS:
            return False
    return True


def include_name(name, type_, parent_names):  # type: ignore[no-untyped-def]
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True
