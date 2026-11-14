# SPDX-License-Identifier: AGPL-3.0-or-later
"""Student ID numbers (SIS user ids) are read from launches and rosters for list awards."""

from __future__ import annotations

from typing import Any

from opencredential.lti.claims import CLAIM_CUSTOM, CLAIM_LIS, launch_from_claims
from opencredential.lti.services import _member

LTI = "https://purl.imsglobal.org/spec/lti/claim/"


def _claims(**extra: Any) -> dict[str, Any]:
    return {
        "iss": "https://canvas.example",
        "sub": "sub-1",
        LTI + "deployment_id": "d",
        LTI + "roles": [],
        LTI + "context": {"id": "ctx"},
        LTI + "resource_link": {"id": "rl"},
        LTI + "target_link_uri": "https://tool/lti/launch",
        **extra,
    }


def test_launch_reads_sis_id_from_custom_field_then_lis_claim() -> None:
    custom = {CLAIM_CUSTOM: {"canvas_user_sis_id": "201111111"}}
    assert launch_from_claims(_claims(**custom), "c").sis_user_id == "201111111"
    lis = {CLAIM_LIS: {"person_sourcedid": "202222222"}}
    assert launch_from_claims(_claims(**lis), "c").sis_user_id == "202222222"
    # Canvas leaves the variable unsubstituted when the user has no SIS id.
    unset = {CLAIM_CUSTOM: {"canvas_user_sis_id": "$Person.sourcedId"}}
    assert launch_from_claims(_claims(**unset), "c").sis_user_id is None


def test_roster_member_sis_id() -> None:
    raw = {"user_id": "s", "roles": [], "lis_person_sourcedid": " 203333333 "}
    assert _member(raw).sis_user_id == "203333333"
    raw = {"user_id": "s", "roles": [], "lis_person_sourcedid": ""}
    assert _member(raw).sis_user_id is None
