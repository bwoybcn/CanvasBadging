# SPDX-License-Identifier: AGPL-3.0-or-later
"""The administrator's setup checklist (product review recommendation 13).

Six things have to be true before a lecturer can create a badge that the public can check.
Nothing told an administrator which of them were done, so a missing one showed up later as an
empty issuer list in a lecturer's wizard. This reads the current state and says, for each step,
whether it is done, what is there, and where to go to finish it.

The first two steps are done by whoever runs the service, not on the administration pages; the
checklist says so instead of sending the administrator to a page that cannot help.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.authz import policy as authz
from opencredential.db.models import (
    CanvasIntegration,
    CanvasToken,
    Institution,
    Issuer,
    IssuerDelegation,
    OrgUnit,
)

OPERATOR = "This step is done by whoever runs the service, not on these pages."


def _names(names: list[str], limit: int = 3) -> str:
    """ "A, B and C", or "A, B, C and 2 more"."""
    names = sorted(names, key=str.casefold)
    if len(names) > limit:
        return f"{', '.join(names[:limit])} and {len(names) - limit} more"
    if len(names) > 1:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return names[0] if names else ""


def _step(
    key: str, title: str, done: bool, detail: str, *, to: str | None = None, operator: bool = False
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "done": done,
        "detail": detail,
        #: Page in the administration area where the step is done; ``None`` for operator steps.
        "to": to,
        "operator": operator,
    }


def _canvas(db: Session) -> dict[str, Any]:
    integrations = db.scalars(select(CanvasIntegration).order_by(CanvasIntegration.name)).all()
    connected = [
        i
        for i in integrations
        if i.status == "active"
        and db.scalar(
            select(CanvasToken.id).where(
                CanvasToken.canvas_integration_id == i.id,
                CanvasToken.purpose == "integration_account",
            )
        )
        is not None
    ]
    if connected:
        detail = f"Connected to {_names([i.name for i in connected])}."
    elif integrations:
        detail = (
            "Canvas can open this tool, but the tool cannot read "
            f"{_names([i.name for i in integrations])} yet, so progress and class lists stay "
            f"empty. {OPERATOR} They finish it with "
            'step 6 of the guide "Connecting OpenCredential to Canvas".'
        )
    else:
        detail = (
            f"No Canvas has been registered. {OPERATOR} They follow the guide "
            '"Connecting OpenCredential to Canvas".'
        )
    return _step("canvas", "Canvas is connected", bool(connected), detail, operator=True)


def _address(inst: Institution, production: bool) -> dict[str, Any]:
    if inst.verification_host:
        detail = f"Badges are checked at {inst.verification_host}."
    else:
        detail = (
            "Not set. "
            + (
                "Issuers cannot be authorised until it is. "
                if production
                else "Badges issued now are signed with a development identity, so they are "
                "for trying things out and will not verify as the university's. "
            )
            + f"{OPERATOR} They set it once they have checked that the university controls the "
            "address (administration guide, section 1)."
        )
    return _step(
        "address",
        "The public address for checking badges is set",
        bool(inst.verification_host),
        detail,
        operator=True,
    )


def checklist(db: Session, actor: authz.Actor, *, production: bool) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    inst = db.get(Institution, actor.institution_id)
    assert inst is not None

    units = db.scalars(select(OrgUnit).where(OrgUnit.status == "active")).all()
    issuing = [u for u in units if authz.org_unit_may_issue(db, u.id)]
    if issuing:
        area_detail = f"{_names([u.name for u in issuing])} may issue badges."
    elif units:
        area_detail = (
            f'None of your {len(units)} areas may issue badges. Tick "May issue badges" for '
            "the ones that should."
        )
    else:
        area_detail = (
            "Add your faculties, departments or services, or link them from Canvas sub-accounts."
        )

    issuers = db.scalars(select(Issuer).order_by(Issuer.name)).all()
    authorised = [
        i for i in issuers if i.status == "active" and authz.org_unit_may_issue(db, i.org_unit_id)
    ]
    if issuers:
        issuer_detail = f"{_names([i.name for i in issuers])}."
    else:
        issuer_detail = (
            "Create the body that awards badges, for example the university or a faculty. "
            "Its name appears on every badge."
        )
    if authorised:
        authorised_detail = f"{_names([i.name for i in authorised])} can sign badges."
    elif issuers:
        authorised_detail = (
            "No issuer can sign badges yet. Open an issuer, choose Authorise and record the "
            "basis of its authority, for example a committee decision."
        )
    else:
        authorised_detail = "Create an issuer first."

    authorised_ids = {i.id for i in authorised}
    delegated = {
        d.issuer_id
        for d in db.scalars(select(IssuerDelegation).where(IssuerDelegation.revoked_at.is_(None)))
        if d.issuer_id in authorised_ids
    }
    if delegated:
        delegated_detail = (
            f"{_names([i.name for i in authorised if i.id in delegated])} can be used by staff "
            "in the departments or courses it is delegated to."
        )
    elif authorised:
        delegated_detail = (
            "Until an issuer is delegated to a department or a course, lecturers have no issuer "
            "to choose and cannot create badges. Open an authorised issuer and add a delegation."
        )
    else:
        delegated_detail = "Authorise an issuer first."

    steps = [
        _canvas(db),
        _address(inst, production),
        _step(
            "area",
            "A faculty, department or service may issue badges",
            bool(issuing),
            area_detail,
            to="/admin/areas",
        ),
        _step(
            "issuer",
            "An issuer has been created",
            bool(issuers),
            issuer_detail,
            to="/admin/issuers",
        ),
        _step(
            "authorised",
            "An issuer is authorised",
            bool(authorised),
            authorised_detail,
            to="/admin/issuers",
        ),
        _step(
            "delegated",
            "An authorised issuer is delegated to a department or course",
            bool(delegated),
            delegated_detail,
            to="/admin/issuers",
        ),
    ]
    done = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "done": done,
        "total": len(steps),
        "complete": done == len(steps),
        #: The first step still to do, so the screen can point at it.
        "next": next((s["key"] for s in steps if not s["done"]), None),
    }
