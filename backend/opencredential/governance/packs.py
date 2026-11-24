# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template packs: an institution's graduate attributes and badge templates in one go.

A pack is a TOML file in ``packs/`` so its wording can be edited without touching code (the
Liverpool pack is a draft to agree with the University). Installing a pack only adds what is
missing: attributes matched by key or name, templates by name in the chosen scope. Nothing an
administrator already has is changed.
"""

from __future__ import annotations

import tomllib
import uuid
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from opencredential.authoring.attributes import GraduateAttribute
from opencredential.authz import policy as authz
from opencredential.db.models import BadgeTemplate
from opencredential.errors import NotFound
from opencredential.governance import attributes, templates

PACK_DIR = Path(__file__).with_name("packs")


class PackTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    defaults: templates.TemplateDefaults


class PackInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    description: str


class Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack: PackInfo
    attributes: list[GraduateAttribute] = []
    templates: list[PackTemplate] = []


@cache
def load_all() -> dict[str, Pack]:
    packs = {}
    for path in sorted(PACK_DIR.glob("*.toml")):
        pack = Pack.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        packs[pack.pack.key] = pack
    return packs


def get(key: str) -> Pack:
    pack = load_all().get(key)
    if pack is None:
        raise NotFound("PACK_NOT_FOUND", "No template pack with that name.")
    return pack


def listing() -> list[dict[str, Any]]:
    return [
        {
            **p.pack.model_dump(),
            "attributes": [a.name for a in p.attributes],
            "templates": [t.name for t in p.templates],
        }
        for p in load_all().values()
    ]


def install(
    db: Session,
    actor: authz.Actor,
    key: str,
    *,
    org_unit_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[BadgeTemplate]]:
    """Add the pack's missing attributes (institution admins only, as the list is
    institution-wide) and its missing templates. Returns what was added."""
    pack = get(key)
    authz.require_inst_admin(actor)
    added_attributes = attributes.add_missing(db, actor, pack.attributes, request_id=request_id)
    added_templates = templates.install(
        db,
        actor,
        [(t.name, t.description, t.defaults) for t in pack.templates],
        org_unit_id=org_unit_id,
        request_id=request_id,
    )
    return added_attributes, added_templates
