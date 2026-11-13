# SPDX-License-Identifier: AGPL-3.0-or-later
"""LinkedIn "Add to Profile" for certifications (spec §9.3, ADR-0014).

LinkedIn's supported route for third parties is a prefilled link to the learner's own
"Add license or certification" form (https://addtoprofile.linkedin.com). It needs no API key,
no LinkedIn login on our side and no automation: the learner reviews and saves the form
themselves. LinkedIn does not import Open Badges files, and may ignore some prefilled values, so
we always show the values for copying as well.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

ADD_TO_PROFILE = "https://www.linkedin.com/profile/add"


def _month_year(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.year, dt.month


def fields(view: dict[str, Any], verification_url: str | None) -> list[dict[str, str | None]]:
    """The certification values, in the order LinkedIn's form asks for them."""
    issued = view.get("issued_on") or ""
    return [
        {"key": "name", "label": "Name", "value": view["credential_name"]},
        {
            "key": "organization",
            "label": "Issuing organization",
            "value": view["issuer"]["institution"],
        },
        {"key": "issue_date", "label": "Issue date", "value": issued[:10] or None},
        {
            "key": "expiration_date",
            "label": "Expiration date",
            "value": (view.get("valid_until") or "")[:10] or "This credential does not expire",
        },
        {"key": "credential_id", "label": "Credential ID", "value": view.get("credential_id")},
        {"key": "credential_url", "label": "Credential URL", "value": verification_url},
    ]


def add_to_profile_url(
    view: dict[str, Any],
    verification_url: str,
    *,
    organization_id: str | None = None,
) -> str:
    """Prefilled Add-to-Profile link. ``organizationId`` (the LinkedIn company page id, set by
    the institution) is preferred; otherwise LinkedIn gets the organisation name as text."""
    params: dict[str, str | int] = {
        "startTask": "CERTIFICATION_NAME",
        "name": view["credential_name"],
    }
    if organization_id:
        params["organizationId"] = organization_id
    else:
        params["organizationName"] = view["issuer"]["institution"]
    issued = _month_year(view.get("issued_on"))
    if issued:
        params["issueYear"], params["issueMonth"] = issued
    expires = _month_year(view.get("valid_until"))
    if expires:
        params["expirationYear"], params["expirationMonth"] = expires
    params["certUrl"] = verification_url
    if view.get("credential_id"):
        params["certId"] = str(view["credential_id"])
    return f"{ADD_TO_PROFILE}?{urlencode(params)}"
