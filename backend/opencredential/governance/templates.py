# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institutional badge templates (spec §10.4).

A template fixes conventions authors would otherwise retype: title pattern, description,
criteria structure, evidence expectations, artwork conventions, skills terminology and a
standard validity period. A template is institution-wide (``org_unit_id`` null) or belongs to a
faculty/department and is offered to courses inside it. Starting a badge from a template copies
the defaults into the draft; the author can then change anything before review.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authoring.service import DraftFields
from opencredential.authz import policy as authz
from opencredential.db.models import BadgeTemplate, Course, OrgUnit
from opencredential.errors import Forbidden, Invalid, NotFound


class ArtworkConvention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str | None = Field(default=None, max_length=40)
    primary_colour: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_colour: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    guidance: str | None = Field(default=None, max_length=1000)


class TemplateDefaults(DraftFields):
    """Draft fields a template pre-fills, plus artwork conventions (not a draft field)."""

    artwork: ArtworkConvention | None = None


def out(db: Session, t: BadgeTemplate) -> dict[str, Any]:
    unit = db.get(OrgUnit, t.org_unit_id) if t.org_unit_id else None
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "org_unit_id": str(t.org_unit_id) if t.org_unit_id else None,
        "org_unit_name": unit.name if unit else None,
        "status": t.status,
        "defaults": t.defaults or {},
    }


def _applies_to(db: Session, t: BadgeTemplate, course: Course | None) -> bool:
    if t.org_unit_id is None:
        return True
    if course is None or course.org_unit_id is None:
        return False
    return t.org_unit_id in authz._org_chain(db, course.org_unit_id)


def list_for(
    db: Session,
    actor: authz.Actor,
    course_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Templates offered to an author in ``course_id``, or (admins) all they manage."""
    templates = db.scalars(select(BadgeTemplate).order_by(BadgeTemplate.name)).all()
    if course_id is not None:
        course = db.get(Course, course_id)
        if course is None or not authz.is_course_staff(db, actor, course):
            raise NotFound("COURSE_NOT_FOUND", "No such course.")
        return [
            out(db, t) for t in templates if t.status == "active" and _applies_to(db, t, course)
        ]
    authz.require_admin(actor)
    scope = authz.admin_org_units(db, actor)
    return [
        out(db, t)
        for t in templates
        if (include_archived or t.status == "active")
        and (scope is None or t.org_unit_id is None or t.org_unit_id in scope)
    ]


def _require_manage(db: Session, actor: authz.Actor, org_unit_id: uuid.UUID | None) -> None:
    if org_unit_id is None:
        authz.require_inst_admin(actor)
    else:
        authz.require_manage_org_unit(db, actor, org_unit_id)


def create(
    db: Session,
    actor: authz.Actor,
    *,
    name: str,
    description: str | None,
    org_unit_id: uuid.UUID | None,
    defaults: TemplateDefaults,
    request_id: str | None = None,
) -> BadgeTemplate:
    _require_manage(db, actor, org_unit_id)
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise NotFound("ORG_UNIT_NOT_FOUND", "No such unit.")
    name = (name or "").strip()
    if not 3 <= len(name) <= 120:
        raise Invalid("NAME_INVALID", "The template name must be 3 to 120 characters.")
    t = BadgeTemplate(
        institution_id=actor.institution_id,
        org_unit_id=org_unit_id,
        name=name,
        description=description,
        defaults=defaults.model_dump(mode="json", exclude_none=True),
        created_by=actor.user_id,
        status="active",
    )
    db.add(t)
    db.flush()
    _audit(db, actor, "template.create", t, request_id)
    return t


def update(
    db: Session,
    actor: authz.Actor,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    defaults: TemplateDefaults | None = None,
    status: str | None = None,
    request_id: str | None = None,
) -> BadgeTemplate:
    t = get(db, template_id)
    _require_manage(db, actor, t.org_unit_id)
    if name is not None:
        if not 3 <= len(name.strip()) <= 120:
            raise Invalid("NAME_INVALID", "The template name must be 3 to 120 characters.")
        t.name = name.strip()
    if description is not None:
        t.description = description
    if defaults is not None:
        t.defaults = defaults.model_dump(mode="json", exclude_none=True)
    if status is not None:
        if status not in ("active", "archived"):
            raise Invalid("STATUS_INVALID", "Status must be active or archived.")
        t.status = status
    _audit(db, actor, "template.update", t, request_id)
    return t


def get(db: Session, template_id: uuid.UUID) -> BadgeTemplate:
    t = db.get(BadgeTemplate, template_id)
    if t is None:
        raise NotFound("TEMPLATE_NOT_FOUND", "No such template.")
    return t


def apply(
    db: Session,
    actor: authz.Actor,
    template_id: uuid.UUID,
    course: Course | None,
    fields: DraftFields,
) -> DraftFields:
    """Fields for a new draft: the template's defaults, overridden by what the author typed."""
    t = get(db, template_id)
    if t.status != "active" or not _applies_to(db, t, course):
        raise Forbidden("TEMPLATE_NOT_AVAILABLE", "That template is not available for this course.")
    base = {k: v for k, v in (t.defaults or {}).items() if k in DraftFields.model_fields}
    typed = fields.model_dump(exclude_none=True)
    return DraftFields.model_validate({**base, **typed})


def _audit(
    db: Session, actor: authz.Actor, action: str, t: BadgeTemplate, request_id: str | None
) -> None:
    audit.record(
        db,
        action=action,
        resource_type="badge_template",
        resource_id=t.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"template_id": str(t.id), "status": t.status},
    )
