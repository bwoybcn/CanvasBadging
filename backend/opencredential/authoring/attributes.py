# SPDX-License-Identifier: AGPL-3.0-or-later
"""Graduate attributes: the institution's own list of qualities its badges develop.

An institution administrator keeps the list (``Institution.graduate_attributes``); an author
tags a badge with attributes from it by key. The draft stores a copy of each chosen attribute,
so a published version, and every badge issued from it, does not change when the list is
edited later. Issued badges carry the attributes as Open Badges 3.0 ``Alignment`` entries
(``issuance.service.alignments``).

An attribute is a description of what the badge develops, not a score: there are no levels.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from opencredential.db.models import Institution
from opencredential.errors import Invalid

MAX_ATTRIBUTES = 20
#: Open Badges ``Alignment.targetType`` for a graduate attribute (an extension value).
GRADUATE_ATTRIBUTE_TYPE = "ext:GraduateAttribute"
KEY_RE = r"^[a-z0-9][a-z0-9-]{0,39}$"


class GraduateAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=KEY_RE, description="Fixed identifier; badges refer to it")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=600)
    framework: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https://")


def slug(name: str) -> str:
    """A key for a new attribute, from its name ("Digital Fluency" -> "digital-fluency")."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s or "attribute"


def institution_list(db: Session, institution_id: uuid.UUID) -> list[dict[str, Any]]:
    inst = db.get(Institution, institution_id)
    return list(inst.graduate_attributes or []) if inst else []


def snapshot(
    db: Session,
    institution_id: uuid.UUID,
    keys: list[str],
    current: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The attributes for a draft, in the order given, copied from the institution's list.

    An attribute the draft already has keeps its copy even if an administrator has since
    removed it from the list, so saving an old draft never fails because the list changed.
    """
    known = {a["key"]: a for a in institution_list(db, institution_id)}
    kept = {a["key"]: a for a in (current or [])}
    out: list[dict[str, Any]] = []
    for key in dict.fromkeys(k.strip() for k in keys if k and k.strip()):
        attribute = known.get(key) or kept.get(key)
        if attribute is None:
            raise Invalid(
                "GRADUATE_ATTRIBUTE_UNKNOWN",
                "That graduate attribute is not on your institution's list.",
                "Choose from the list, or ask an administrator to add it.",
            )
        out.append(GraduateAttribute.model_validate(attribute).model_dump(exclude_none=True))
    if len(out) > MAX_ATTRIBUTES:
        raise Invalid("GRADUATE_ATTRIBUTES_TOO_MANY", "Choose at most 20 graduate attributes.")
    return out
