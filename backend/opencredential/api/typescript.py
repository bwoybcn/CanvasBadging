# SPDX-License-Identifier: AGPL-3.0-or-later
"""TypeScript types for the screens, written from the OpenAPI document.

``oc api-types --out ../frontend/src/api.gen.ts`` writes them, and a test fails when the file
is out of date, so the screens cannot quietly drift from the API. Only the named schemas
(request and response bodies declared with a model) are written; a route that returns a plain
dictionary has no schema to write.

A body that is only ever sent *by* the API has every field present, including those with a
default, so its fields are not optional. A body the screens send *to* the API may leave out
anything that is not required.
"""

from __future__ import annotations

import json
import re
from typing import Any

HEADER = """\
// SPDX-License-Identifier: AGPL-3.0-or-later
// Written by `oc api-types` from the API description (docs/api/openapi.json). Do not edit:
// change the API model, then run, from backend/:
//   uv run oc openapi --out ../docs/api/openapi.json
//   uv run oc api-types --out ../frontend/src/api.gen.ts
// A backend test fails when this file is out of date.
"""

_REF = "#/components/schemas/"
_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def type_name(schema_name: str) -> str:
    """``opencredential__api__routes__assets__TemplateIn`` -> ``AssetsTemplateIn``; other names
    are kept. FastAPI writes the long form when two modules use the same model name."""
    parts = schema_name.split("__")
    if len(parts) < 2:
        return re.sub(r"[^A-Za-z0-9_$]", "_", schema_name)
    return parts[-2][:1].upper() + parts[-2][1:] + parts[-1]


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _union(types: list[str]) -> str:
    seen: list[str] = []
    for t in types:
        if t not in seen:
            seen.append(t)
    return " | ".join(seen) if seen else "never"


def _key(name: str) -> str:
    return name if _IDENT.match(name) else _literal(name)


def ts_type(schema: Any, *, all_present: bool = False, indent: str = "  ") -> str:
    """The TypeScript type for one JSON Schema node."""
    if not isinstance(schema, dict) or not schema:
        return "unknown"
    if "$ref" in schema:
        return type_name(str(schema["$ref"]).removeprefix(_REF))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return _union([ts_type(s, all_present=all_present, indent=indent) for s in schema[key]])
    if "allOf" in schema:
        parts = [ts_type(s, all_present=all_present, indent=indent) for s in schema["allOf"]]
        return " & ".join(parts) if parts else "unknown"
    if "enum" in schema:
        return _union([_literal(v) for v in schema["enum"]])
    if "const" in schema:
        return _literal(schema["const"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return _union(
            [ts_type({**schema, "type": k}, all_present=all_present, indent=indent) for k in kind]
        )
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        if "prefixItems" in schema:
            items = [
                ts_type(s, all_present=all_present, indent=indent) for s in schema["prefixItems"]
            ]
            return "[" + ", ".join(items) + "]"
        item = ts_type(schema.get("items"), all_present=all_present, indent=indent)
        return f"({item})[]" if " | " in item or " & " in item else f"{item}[]"
    if kind == "object" or "properties" in schema:
        if "properties" in schema:
            return _object(schema, all_present=all_present, indent=indent + "  ")
        extra = schema.get("additionalProperties")
        value = (
            ts_type(extra, all_present=all_present, indent=indent)
            if isinstance(extra, dict) and extra
            else "unknown"
        )
        return f"Record<string, {value}>"
    return "unknown"


def _doc(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    lines = [line.rstrip() for line in str(text).replace("*/", "* /").strip().splitlines()]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    return [f"{indent}/**", *[f"{indent} * {line}".rstrip() for line in lines], f"{indent} */"]


def _object(schema: dict[str, Any], *, all_present: bool, indent: str) -> str:
    required = set(schema.get("required") or [])
    lines = ["{"]
    for name, prop in schema["properties"].items():
        lines += _doc(prop.get("description") if isinstance(prop, dict) else None, indent)
        optional = "" if all_present or name in required else "?"
        value = ts_type(prop, all_present=all_present, indent=indent)
        lines.append(f"{indent}{_key(name)}{optional}: {value};")
    extra = schema.get("additionalProperties")
    if extra:
        value = ts_type(extra, all_present=all_present, indent=indent) if extra is not True else ""
        lines.append(f"{indent}[key: string]: {value or 'unknown'};")
    lines.append(indent[:-2] + "}")
    return "\n".join(lines)


def _refs(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(_REF):
                out.add(value.removeprefix(_REF))
            else:
                out |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            out |= _refs(value)
    return out


def _reachable(schemas: dict[str, Any], start: set[str]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        name = todo.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        todo.extend(_refs(schemas[name]))
    return seen


def sent_by_clients(doc: dict[str, Any]) -> set[str]:
    """Names of the schemas that appear (directly or nested) in a request the screens send."""
    schemas = doc.get("components", {}).get("schemas", {})
    start: set[str] = set()
    for operations in doc.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            start |= _refs(operation.get("requestBody"))
            start |= _refs(operation.get("parameters"))
    return _reachable(schemas, start)


def render(doc: dict[str, Any]) -> str:
    """The whole generated file for an OpenAPI document."""
    schemas: dict[str, Any] = doc.get("components", {}).get("schemas", {})
    inputs = sent_by_clients(doc)
    names = {name: type_name(name) for name in schemas}
    if len(set(names.values())) != len(names):
        raise ValueError("two API schemas would get the same TypeScript name")
    blocks: list[str] = [HEADER]
    for name in sorted(schemas, key=lambda n: names[n]):
        schema = schemas[name]
        all_present = name not in inputs
        lines = _doc(schema.get("description"), "")
        if "properties" in schema:
            body = _object(schema, all_present=all_present, indent="  ")
            lines.append(f"export interface {names[name]} {body}")
        else:
            lines.append(f"export type {names[name]} = {ts_type(schema, all_present=all_present)};")
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)
