# SPDX-License-Identifier: AGPL-3.0-or-later
"""The institution's graduate attribute list, kept by institution administrators.

Badges refer to an attribute by its key and keep their own copy of it (see
``opencredential.authoring.attributes``), so editing or removing an attribute here changes what
authors can choose from next, never a badge already published or issued.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authoring.attributes import (
    KEY_RE,
    MAX_ATTRIBUTES,
    GraduateAttribute,
    institution_list,
    slug,
)
from opencredential.authz import policy as authz
from opencredential.db.models import Institution
from opencredential.errors import Invalid


class AttributeIn(BaseModel):
    """One attribute as an administrator edits it; a new one may leave the key out."""

    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, pattern=KEY_RE)
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=600)
    framework: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)


def listing(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    return institution_list(db, actor.institution_id)


def replace(
    db: Session,
    actor: authz.Actor,
    items: list[AttributeIn],
    *,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Save the whole list, in the order given. A new attribute gets a key from its name."""
    authz.require_inst_admin(actor)
    if len(items) > MAX_ATTRIBUTES:
        raise Invalid(
            "GRADUATE_ATTRIBUTES_TOO_MANY", f"List at most {MAX_ATTRIBUTES} graduate attributes."
        )
    taken = {i.key for i in items if i.key}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = " ".join(item.name.split())
        key = item.key
        if key is None:
            base = slug(name)
            key, n = base, 2
            while key in taken or key in seen:
                key, n = f"{base[:36]}-{n}", n + 1
        if key in seen:
            raise Invalid("GRADUATE_ATTRIBUTE_DUPLICATE", "Two graduate attributes share a key.")
        seen.add(key)
        url = (item.url or "").strip() or None
        if url and not url.startswith("https://"):
            raise Invalid("URL_INVALID", f"The link for {name} must be an https:// address.")
        attribute = GraduateAttribute(
            key=key,
            name=name,
            description=(item.description or "").strip() or None,
            framework=(item.framework or "").strip() or None,
            url=url,
        )
        out.append(attribute.model_dump(exclude_none=True))
    names = [a["name"].casefold() for a in out]
    if len(set(names)) != len(names):
        raise Invalid("GRADUATE_ATTRIBUTE_DUPLICATE", "Two graduate attributes have the same name.")
    inst = db.get(Institution, actor.institution_id)
    assert inst is not None
    before = {a["key"] for a in inst.graduate_attributes or []}
    inst.graduate_attributes = out
    audit.record(
        db,
        action="institution.graduate_attributes_update",
        resource_type="institution",
        resource_id=inst.id,
        institution_id=inst.id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={
            "added": sorted(seen - before),
            "removed": sorted(before - seen),
            "count": len(out),
        },
    )
    return out


def add_missing(
    db: Session,
    actor: authz.Actor,
    attributes: list[GraduateAttribute],
    *,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Append the attributes whose key is not on the list yet. Returns the ones added."""
    current = institution_list(db, actor.institution_id)
    keys = {a["key"] for a in current}
    names = {a["name"].casefold() for a in current}
    added = [
        a.model_dump(exclude_none=True)
        for a in attributes
        if a.key not in keys and a.name.casefold() not in names
    ]
    if added:
        replace(
            db,
            actor,
            [AttributeIn.model_validate(a) for a in current + added],
            request_id=request_id,
        )
    return added
