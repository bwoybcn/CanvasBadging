# SPDX-License-Identifier: AGPL-3.0-or-later
"""The screens' TypeScript types are written from the API description (api/typescript.py)."""

from __future__ import annotations

from typing import Any

from opencredential.api.typescript import render, sent_by_clients, ts_type, type_name

REF = "#/components/schemas/"


def _doc() -> dict[str, Any]:
    return {
        "paths": {
            "/things": {
                "post": {
                    "requestBody": {
                        "content": {"application/json": {"schema": {"$ref": REF + "ThingIn"}}}
                    },
                    "responses": {
                        "200": {
                            "content": {"application/json": {"schema": {"$ref": REF + "ThingOut"}}}
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "ThingIn": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "part": {"$ref": REF + "Part"},
                    },
                },
                "ThingOut": {
                    "type": "object",
                    "description": "A thing, as the API returns it.",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "state": {"enum": ["active", "revoked"], "type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                        "owner": {"anyOf": [{"$ref": REF + "Owner"}, {"type": "null"}]},
                        "extra": {"type": "object", "additionalProperties": True},
                        "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
                        "kebab-case": {"type": "boolean", "description": "Needs quoting."},
                    },
                },
                "Owner": {"type": "object", "properties": {"name": {"type": "string"}}},
                "Part": {"type": "object", "properties": {"size": {"type": "number"}}},
                "pkg__routes__one__Same": {"type": "string"},
            }
        },
    }


def test_only_bodies_the_screens_send_have_optional_fields() -> None:
    assert sent_by_clients(_doc()) == {"ThingIn", "Part"}  # Part is nested in a request
    text = render(_doc())
    # Sent to the API: anything not required may be left out.
    assert (
        "export interface ThingIn {\n  name: string;\n  note?: string | null;\n  part?: Part;\n}"
    ) in text
    assert "export interface Part {\n  size?: number;\n}" in text
    # Only ever returned: every field is there, including those with a default.
    assert "export interface Owner {\n  name: string;\n}" in text
    assert (
        "/** A thing, as the API returns it. */\n"
        "export interface ThingOut {\n"
        "  id: string;\n"
        '  state: "active" | "revoked";\n'
        "  tags: string[];\n"
        "  owner: Owner | null;\n"
        "  extra: Record<string, unknown>;\n"
        "  counts: Record<string, number>;\n"
        "  /** Needs quoting. */\n"
        '  "kebab-case": boolean;\n'
        "}"
    ) in text


def test_types_are_written_in_name_order_under_a_do_not_edit_header() -> None:
    text = render(_doc())
    assert text.startswith("// SPDX-License-Identifier: AGPL-3.0-or-later\n// Written by")
    names = [line.split()[2] for line in text.splitlines() if line.startswith("export ")]
    assert names == sorted(names) == ["OneSame", "Owner", "Part", "ThingIn", "ThingOut"]
    assert render(_doc()) == text  # the same input always gives the same file


def test_long_module_qualified_names_are_shortened() -> None:
    assert type_name("opencredential__api__routes__assets__TemplateIn") == "AssetsTemplateIn"
    assert type_name("MeOut") == "MeOut"


def test_json_schema_kinds() -> None:
    assert ts_type({"type": "array", "items": {"enum": ["a", "b"]}}) == '("a" | "b")[]'
    assert ts_type({"const": "module_completed"}) == '"module_completed"'
    assert ts_type({"type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}]}) == (
        "[string, number]"
    )
    assert ts_type({"oneOf": [{"$ref": REF + "A"}, {"$ref": REF + "B"}]}) == "A | B"
    assert ts_type({}) == "unknown"
    assert ts_type({"type": "object"}) == "Record<string, unknown>"
