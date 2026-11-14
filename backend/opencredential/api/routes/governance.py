# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institutional administration API (spec §10, §12.5, Phase 7).

Thin routes over :mod:`opencredential.governance`; every service checks the actor's scope, and
the session is tenant-scoped by row-level security, so nothing here can reach another
institution's rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from opencredential.api.deps import ActorDep, RequestIdDep, SettingsDep, SignerDep, TenantDb
from opencredential.authz import policy as authz
from opencredential.db.models.issuers import ISSUER_LEVELS
from opencredential.governance import (
    audit_log,
    canvas_accounts,
    institution,
    issuers,
    people,
    privacy,
    reconciliation,
    records,
    retention,
    revocation,
    templates,
)

router = APIRouter(prefix="/api/v1", tags=["institutional administration"])


def _csv(body: str, name: str) -> Response:
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


# ---- institution configuration -------------------------------------------------------------


class Branding(BaseModel):
    primary_colour: str | None = None
    secondary_colour: str | None = None


class InstitutionIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    website_url: str | None = Field(default=None, max_length=500)
    logo_asset_id: uuid.UUID | None = None
    branding: Branding | None = None
    #: Read-only here: only the operator sets it (``oc admin set-verification-host``). Sending the
    #: current value is accepted; a different one is refused with 403.
    verification_host: str | None = Field(
        default=None,
        max_length=253,
        description="Operator-only. Send the current value or leave it out; a change is refused.",
    )
    categories: list[str] | None = Field(default=None, max_length=30)
    linkedin_org_id: str | None = Field(default=None, max_length=40)
    linkedin_org_name: str | None = Field(default=None, max_length=200)


@router.get("/institutions/current")
def get_institution(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    return institution.config_out(institution.current(db, actor))


@router.patch("/institutions/current")
def update_institution(
    body: InstitutionIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "logo_asset_id" in changes and changes["logo_asset_id"] is not None:
        changes["logo_asset_id"] = uuid.UUID(changes["logo_asset_id"])
    inst = institution.update_config(db, actor, changes, request_id=rid)
    return institution.config_out(inst)


class RetentionIn(BaseModel):
    snapshot_days_after_course_end: int | None = None
    evaluation_days: int | None = None
    failed_job_days: int | None = None
    audit_event_years: int | None = None


@router.get("/institutions/current/retention")
def get_retention(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    return institution.retention(institution.current(db, actor))


@router.patch("/institutions/current/retention")
def update_retention(
    body: RetentionIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    return institution.update_retention(
        db, actor, body.model_dump(exclude_none=True), request_id=rid
    )


@router.post("/admin/retention/run")
def run_retention(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    return retention.apply(db, actor.institution_id, actor_user_id=actor.user_id)


# ---- organisation and delegated permissions -------------------------------------------------


class OrgUnitIn(BaseModel):
    name: str = Field(max_length=200)
    kind: Literal["faculty", "department", "programme", "service", "other"]
    parent_id: uuid.UUID | None = None


class OrgUnitPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    kind: Literal["faculty", "department", "programme", "service", "other"] | None = None
    parent_id: uuid.UUID | None = None
    may_issue: bool | None = None
    status: Literal["active", "archived"] | None = None
    #: Partial colleague-review overrides; a key set to null inherits again.
    review_policy: dict[str, Any] | None = None


@router.get("/admin/org-units")
def list_org_units(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    return people.list_org_units(db, actor)


@router.post("/admin/org-units", status_code=201)
def create_org_unit(
    body: OrgUnitIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    unit = people.create_org_unit(
        db, actor, name=body.name, kind=body.kind, parent_id=body.parent_id, request_id=rid
    )
    return people.org_unit_out(db, unit)


@router.patch("/admin/org-units/{unit_id}")
def update_org_unit(
    unit_id: uuid.UUID, body: OrgUnitPatch, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    unit = people.update_org_unit(
        db, actor, unit_id, body.model_dump(exclude_unset=True), request_id=rid
    )
    return people.org_unit_out(db, unit)


# ---- Canvas sub-accounts linked to areas ----------------------------------------------------


class CanvasAccountLinkItem(BaseModel):
    id: uuid.UUID
    #: Link to this existing area instead of creating one named after the sub-account.
    org_unit_id: uuid.UUID | None = None
    #: Kind of the new area; default faculty at the top, department below a linked one.
    kind: Literal["faculty", "department", "programme", "service", "other"] | None = None


class CanvasAccountLinkIn(BaseModel):
    items: list[CanvasAccountLinkItem] = Field(min_length=1, max_length=500)


@router.get("/admin/canvas-accounts")
def list_canvas_accounts(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    """Canvas sub-accounts last read from Canvas, as a tree, with their linked area."""
    return canvas_accounts.listing(db, actor)


@router.post("/admin/canvas-accounts/refresh")
def refresh_canvas_accounts(db: TenantDb, actor: ActorDep, rid: RequestIdDep) -> dict[str, Any]:
    """Read the sub-account tree from Canvas again."""
    return canvas_accounts.refresh(db, actor, request_id=rid)


@router.post("/admin/canvas-accounts/link")
def link_canvas_accounts(
    body: CanvasAccountLinkIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    """Link ticked sub-accounts to areas; their courses join those areas from then on."""
    return canvas_accounts.link(db, actor, [i.model_dump() for i in body.items], request_id=rid)


@router.delete("/admin/canvas-accounts/{account_id}/link", status_code=204)
def unlink_canvas_account(
    account_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> Response:
    """Stop placing new courses from this sub-account; the area and its courses stay."""
    canvas_accounts.unlink(db, actor, account_id, request_id=rid)
    return Response(status_code=204)


@router.get("/admin/review/published-without-review")
def published_without_review(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    """Live badges nobody else reviewed, so admins can check them after tightening review."""
    from opencredential.governance import review

    return review.published_without_review(db, actor)


@router.get("/admin/courses")
def list_courses(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    return people.list_courses(db, actor)


class CourseUnitIn(BaseModel):
    org_unit_id: uuid.UUID | None


@router.put("/admin/courses/{course_id}/org-unit")
def assign_course(
    course_id: uuid.UUID, body: CourseUnitIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    c = people.assign_course(db, actor, course_id, body.org_unit_id, request_id=rid)
    return {"id": str(c.id), "org_unit_id": str(c.org_unit_id) if c.org_unit_id else None}


@router.get("/admin/memberships")
def list_memberships(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    return people.list_staff_memberships(db, actor)


class GrantIn(BaseModel):
    user_id: uuid.UUID
    role: Literal[
        "lecturer", "course_admin", "issuer_manager", "reviewer", "dept_admin", "inst_admin"
    ]
    scope_type: Literal["institution", "org_unit", "issuer", "course"]
    scope_id: uuid.UUID | None = None
    expires_at: datetime | None = None


@router.post("/admin/memberships", status_code=201)
def grant_membership(
    body: GrantIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    m = people.grant(
        db,
        actor,
        user_id=body.user_id,
        role=body.role,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        expires_at=body.expires_at,
        request_id=rid,
    )
    return people.membership_out(db, m)


@router.delete("/admin/memberships/{membership_id}", status_code=204)
def revoke_membership(
    membership_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> Response:
    people.revoke(db, actor, membership_id, request_id=rid)
    return Response(status_code=204)


@router.get("/admin/people")
def search_people(
    db: TenantDb, actor: ActorDep, q: str = Query("", max_length=100)
) -> list[dict[str, Any]]:
    return people.search_people(db, actor, q)


# ---- issuers ---------------------------------------------------------------------------------


class IssuerIn(BaseModel):
    name: str = Field(max_length=200)
    slug: str = Field(max_length=63)
    level: str = Field(description=f"One of {', '.join(ISSUER_LEVELS)}")
    org_unit_id: uuid.UUID | None = None
    url: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=320)
    description: str | None = Field(default=None, max_length=4000)


class IssuerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=320)
    description: str | None = Field(default=None, max_length=4000)


class AuthoriseIn(BaseModel):
    authority_basis: str = Field(min_length=10, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DelegationIn(BaseModel):
    scope_type: Literal["org_unit", "course"]
    scope_id: uuid.UUID


@router.get("/admin/issuers")
def list_issuers(db: TenantDb, actor: ActorDep) -> list[dict[str, Any]]:
    return issuers.list_for(db, actor)


@router.post("/admin/issuers", status_code=201)
def create_issuer(
    body: IssuerIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    i = issuers.create(db, actor, **body.model_dump(), request_id=rid)
    return issuers.out(db, i)


@router.patch("/admin/issuers/{issuer_id}")
def update_issuer(
    issuer_id: uuid.UUID, body: IssuerPatch, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    i = issuers.update(
        db, actor, issuers.get(db, issuer_id), body.model_dump(exclude_unset=True), rid
    )
    return issuers.out(db, i)


@router.post("/admin/issuers/{issuer_id}/authorise")
def authorise_issuer(
    issuer_id: uuid.UUID,
    body: AuthoriseIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    signer: SignerDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    i = issuers.authorise(
        db,
        actor,
        issuers.get(db, issuer_id),
        authority_basis=body.authority_basis,
        signer=signer,
        settings=settings,
        request_id=rid,
    )
    return issuers.out(db, i)


@router.post("/admin/issuers/{issuer_id}/suspend")
def suspend_issuer(
    issuer_id: uuid.UUID, body: ReasonIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    i = issuers.suspend(db, actor, issuers.get(db, issuer_id), reason=body.reason, request_id=rid)
    return issuers.out(db, i)


@router.post("/admin/issuers/{issuer_id}/delegations", status_code=201)
def delegate_issuer(
    issuer_id: uuid.UUID, body: DelegationIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    i = issuers.get(db, issuer_id)
    issuers.delegate(
        db, actor, i, scope_type=body.scope_type, scope_id=body.scope_id, request_id=rid
    )
    return issuers.out(db, i)


@router.delete("/admin/issuer-delegations/{delegation_id}", status_code=204)
def undelegate_issuer(
    delegation_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> Response:
    issuers.undelegate(db, actor, delegation_id, request_id=rid)
    return Response(status_code=204)


# ---- templates -------------------------------------------------------------------------------


class TemplateIn(BaseModel):
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    org_unit_id: uuid.UUID | None = None
    defaults: templates.TemplateDefaults = Field(default_factory=templates.TemplateDefaults)


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    defaults: templates.TemplateDefaults | None = None
    status: Literal["active", "archived"] | None = None


@router.get("/templates")
def templates_for_course(
    course_id: uuid.UUID, db: TenantDb, actor: ActorDep
) -> list[dict[str, Any]]:
    """Templates an author can start a badge from in this course."""
    return templates.list_for(db, actor, course_id=course_id)


@router.get("/admin/templates")
def list_templates(
    db: TenantDb, actor: ActorDep, include_archived: bool = False
) -> list[dict[str, Any]]:
    return templates.list_for(db, actor, include_archived=include_archived)


@router.post("/admin/templates", status_code=201)
def create_template(
    body: TemplateIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    t = templates.create(
        db,
        actor,
        name=body.name,
        description=body.description,
        org_unit_id=body.org_unit_id,
        defaults=body.defaults,
        request_id=rid,
    )
    return templates.out(db, t)


class StarterTemplatesIn(BaseModel):
    org_unit_id: uuid.UUID | None = None


@router.post("/admin/templates/starters", status_code=201)
def install_starter_templates(
    body: StarterTemplatesIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> list[dict[str, Any]]:
    """Add the ready-made templates (volunteering hours, workshop attendance, event
    participation, CPD activity) that are not there yet. Returns the ones added."""
    added = templates.install_starters(db, actor, org_unit_id=body.org_unit_id, request_id=rid)
    return [templates.out(db, t) for t in added]


@router.patch("/admin/templates/{template_id}")
def update_template(
    template_id: uuid.UUID, body: TemplatePatch, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    t = templates.update(
        db,
        actor,
        template_id,
        name=body.name,
        description=body.description,
        defaults=body.defaults,
        status=body.status,
        request_id=rid,
    )
    return templates.out(db, t)


# ---- records, reporting and CSV -------------------------------------------------------------


@router.get("/admin/credentials")
def list_credentials(
    db: TenantDb,
    actor: ActorDep,
    course_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    status: Literal["active", "revoked"] | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
    learner: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    return records.records(
        db,
        actor,
        course_id=course_id,
        definition_id=definition_id,
        status=status,
        issued_from=issued_from,
        issued_to=issued_to,
        learner=learner,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/admin/reports/issuance.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def issuance_csv(
    db: TenantDb,
    actor: ActorDep,
    course_id: uuid.UUID | None = None,
    definition_id: uuid.UUID | None = None,
    status: Literal["active", "revoked"] | None = None,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> Response:
    rows = records.records(
        db,
        actor,
        course_id=course_id,
        definition_id=definition_id,
        status=status,
        issued_from=issued_from,
        issued_to=issued_to,
        limit=1_000_000,
    )
    from opencredential import audit as audit_mod

    audit_mod.record(
        db,
        action="institution.report_export",
        resource_type="report",
        resource_id="issuance",
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        data={"counts": {"rows": len(rows)}},
    )
    return _csv(records.to_csv(rows, records.RECORD_COLUMNS), "issuance-records.csv")


@router.get("/admin/reports/summary")
def report_summary(
    db: TenantDb,
    actor: ActorDep,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> dict[str, Any]:
    return records.summary(db, actor, issued_from=issued_from, issued_to=issued_to)


@router.get(
    "/admin/reports/summary.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def report_summary_csv(
    db: TenantDb,
    actor: ActorDep,
    issued_from: date | None = None,
    issued_to: date | None = None,
) -> Response:
    s = records.summary(db, actor, issued_from=issued_from, issued_to=issued_to)
    rows: list[dict[str, Any]] = [
        {"section": "total", "name": "Issued", "issued": s["issued"], "revoked": s["revoked"]},
        *(
            {
                "section": "course",
                "name": c["course_title"],
                "issued": c["issued"],
                "revoked": c["revoked"],
            }
            for c in s["by_course"]
        ),
        *(
            {
                "section": "badge",
                "name": b["badge_title"],
                "course": b["course_title"],
                "issued": b["issued"],
                "revoked": b["revoked"],
            }
            for b in s["by_badge"]
        ),
        *({"section": "month", "name": m["month"], "issued": m["issued"]} for m in s["by_month"]),
        {
            "section": "pending",
            "name": "Awaiting confirmation",
            "issued": s["pending_awards"]["awaiting_confirmation"],
        },
        {
            "section": "pending",
            "name": "Awaiting issuance",
            "issued": s["pending_awards"]["awaiting_issuance"],
        },
        {
            "section": "failed",
            "name": "Credentials not issued",
            "issued": s["failed_issuance"]["credentials_not_issued"],
        },
        {"section": "failed", "name": "Failed jobs", "issued": s["failed_issuance"]["failed_jobs"]},
    ]
    return _csv(
        records.to_csv(rows, ("section", "name", "course", "issued", "revoked")),
        "issuance-summary.csv",
    )


# ---- revocation ------------------------------------------------------------------------------


class RevocationRequestIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DecideRequestIn(BaseModel):
    reason_code: Literal[
        "issued_in_error", "academic_misconduct", "requirements_not_met", "learner_request", "other"
    ] = "other"
    note: str | None = Field(default=None, max_length=2000)


@router.post("/credentials/{credential_id}/revocation-requests", status_code=201)
def request_revocation(
    credential_id: uuid.UUID,
    body: RevocationRequestIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
) -> dict[str, Any]:
    req = revocation.request_revocation(
        db, actor, credential_id, reason=body.reason, request_id=rid
    )
    return {"id": str(req.id), "status": req.status}


@router.get("/admin/revocation-requests")
def list_revocation_requests(
    db: TenantDb,
    actor: ActorDep,
    status: Literal["open", "approved", "rejected"] | None = "open",
) -> list[dict[str, Any]]:
    return revocation.list_requests(db, actor, status)


@router.post("/admin/revocation-requests/{request_id}/approve")
def approve_revocation_request(
    request_id: uuid.UUID,
    body: DecideRequestIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    signer: SignerDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    req = revocation.decide_request(
        db,
        actor,
        request_id,
        approve=True,
        reason_code=body.reason_code,
        note=body.note,
        signer=signer,
        settings=settings,
        request_id=rid,
    )
    return {"id": str(req.id), "status": req.status}


@router.post("/admin/revocation-requests/{request_id}/decline")
def decline_revocation_request(
    request_id: uuid.UUID,
    body: DecideRequestIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    req = revocation.decide_request(
        db,
        actor,
        request_id,
        approve=False,
        note=body.note,
        signer=None,
        settings=settings,
        request_id=rid,
    )
    return {"id": str(req.id), "status": req.status}


# ---- audit log -------------------------------------------------------------------------------


@router.get("/admin/audit/categories")
def audit_categories(actor: ActorDep) -> list[str]:
    authz.require_inst_admin(actor)
    return [*audit_log.CATEGORIES, "Other"]


@router.get("/admin/audit")
def audit_events(
    db: TenantDb,
    actor: ActorDep,
    category: str | None = None,
    action: str | None = Query(None, max_length=80),
    resource_type: str | None = Query(None, max_length=60),
    resource_id: str | None = Query(None, max_length=80),
    actor_user_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    before: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    return audit_log.query(
        db,
        actor,
        category=category,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
        before_id=before,
        limit=limit,
    )


@router.get(
    "/admin/audit.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
def audit_csv(
    db: TenantDb,
    actor: ActorDep,
    category: str | None = None,
    action: str | None = Query(None, max_length=80),
    since: date | None = None,
    until: date | None = None,
) -> Response:
    page = audit_log.query(
        db, actor, category=category, action=action, since=since, until=until, limit=100_000
    )
    rows = [{**i, "data": json.dumps(i["data"], sort_keys=True)} for i in page["items"]]
    return _csv(records.to_csv(rows, audit_log.AUDIT_COLUMNS), "audit-log.csv")


# ---- personal data ---------------------------------------------------------------------------


def _json_download(doc: dict[str, Any], name: str) -> Response:
    return Response(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/learners/me/data-export",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}},
)
def my_data_export(db: TenantDb, actor: ActorDep, rid: RequestIdDep) -> Response:
    return _json_download(privacy.export(db, actor, actor.user_id, rid), "my-data.json")


@router.get(
    "/admin/people/{user_id}/data-export",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}},
)
def person_data_export(
    user_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> Response:
    return _json_download(privacy.export(db, actor, user_id, rid), f"personal-data-{user_id}.json")


class EraseIn(BaseModel):
    confirm: str


@router.post("/admin/people/{user_id}/erase")
def erase_person(
    user_id: uuid.UUID, body: EraseIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    return privacy.erase(db, actor, user_id, confirm=body.confirm, request_id=rid)


# ---- reconciliation --------------------------------------------------------------------------


@router.get("/admin/reconciliation")
def reconciliation_overview(db: TenantDb, actor: ActorDep) -> dict[str, Any]:
    return reconciliation.overview(db, actor)


@router.post("/admin/reconciliation/awards/{decision_id}/requeue")
def requeue_award(
    decision_id: uuid.UUID, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    return reconciliation.requeue(db, actor, decision_id, request_id=rid)


@router.post("/admin/reconciliation/awards/{decision_id}/cancel")
def cancel_award(
    decision_id: uuid.UUID, body: ReasonIn, db: TenantDb, actor: ActorDep, rid: RequestIdDep
) -> dict[str, Any]:
    d = reconciliation.cancel(db, actor, decision_id, reason=body.reason, request_id=rid)
    return {"decision_id": str(d.id), "status": d.status}
