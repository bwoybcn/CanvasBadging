# SPDX-License-Identifier: AGPL-3.0-or-later
"""LTI 1.3 claim names, the validated launch record and server-side role mapping.

Role mapping (ADR-0013) is decided here, from the signed ``roles`` claim only. Nothing the
browser sends afterwards can change it, and every privileged API call re-reads memberships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LTI = "https://purl.imsglobal.org/spec/lti/claim/"
CLAIM_MESSAGE_TYPE = LTI + "message_type"
CLAIM_VERSION = LTI + "version"
CLAIM_DEPLOYMENT_ID = LTI + "deployment_id"
CLAIM_TARGET_LINK_URI = LTI + "target_link_uri"
CLAIM_RESOURCE_LINK = LTI + "resource_link"
CLAIM_ROLES = LTI + "roles"
CLAIM_CONTEXT = LTI + "context"
CLAIM_CUSTOM = LTI + "custom"
CLAIM_TOOL_PLATFORM = LTI + "tool_platform"
CLAIM_LIS = LTI + "lis"
CLAIM_NRPS = "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice"
CANVAS_CLAIM_LTI11_ID = LTI + "lti1p1"

MESSAGE_TYPE = "LtiResourceLinkRequest"
VERSION = "1.3.0"
COURSE_CONTEXT_TYPES = {
    "http://purl.imsglobal.org/vocab/lis/v2/course#CourseOffering",
    "http://purl.imsglobal.org/vocab/lis/v2/course#CourseSection",
    "http://purl.imsglobal.org/vocab/lis/v2/course#CourseTemplate",
    "CourseOffering",
}

_MEMBERSHIP = "http://purl.imsglobal.org/vocab/lis/v2/membership#"
_MEMBERSHIP_SUB = "http://purl.imsglobal.org/vocab/lis/v2/membership/"
TEST_USER_ROLE = "http://purl.imsglobal.org/vocab/lti/system/person#TestUser"

#: Context (course) roles → OpenCredential course roles. Institution and system roles are
#: deliberately ignored: org-wide roles are granted in the app, never inferred from Canvas.
_ROLE_MAP = {
    "Administrator": "course_admin",
    "Instructor": "lecturer",
    "ContentDeveloper": "lecturer",
    "Mentor": None,
    "Learner": "student",
}


def _principal(role: str) -> tuple[str, str | None]:
    """``(principal, sub_role)`` for a context role URI, or ``("", None)`` if not a context
    role. Accepts full URIs, sub-role URIs (``membership/Instructor#TeachingAssistant``) and the
    short forms the LTI spec allows for context roles."""
    if role.startswith(_MEMBERSHIP):
        return role[len(_MEMBERSHIP) :], None
    if role.startswith(_MEMBERSHIP_SUB):
        principal, _, sub = role[len(_MEMBERSHIP_SUB) :].partition("#")
        return principal, sub or None
    if "/" not in role and "#" not in role:
        return role, None
    return "", None


def map_roles(roles: list[str]) -> set[str]:
    """Course roles granted by a launch. TAs map to ``lecturer`` (ADR-0013)."""
    out: set[str] = set()
    for role in roles:
        principal, sub = _principal(role)
        if principal == "Instructor" and sub == "TeachingAssistant":
            out.add("lecturer")
            continue
        if principal == "Learner" and sub in {"NonCreditLearner", "Learner", None}:
            out.add("student")
            continue
        mapped = _ROLE_MAP.get(principal)
        if mapped:
            out.add(mapped)
    if TEST_USER_ROLE in roles:
        # Canvas "Student view": the fake test student is a learner only, never staff.
        out &= {"student"}
    if "course_admin" in out:
        out.add("lecturer")
    return out


@dataclass(frozen=True)
class LaunchData:
    """A fully validated resource-link launch. Built only by :mod:`opencredential.lti.launch`."""

    issuer: str
    client_id: str
    deployment_id: str
    subject: str
    roles: tuple[str, ...]
    course_roles: frozenset[str]
    context_id: str
    context_title: str | None
    context_label: str | None
    resource_link_id: str
    canvas_course_id: str | None
    canvas_user_id: str | None
    sis_user_id: str | None
    name: str | None
    given_name: str | None
    family_name: str | None
    email: str | None
    nrps_url: str | None
    is_test_user: bool
    target_link_uri: str
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Serialisable form for parking a launch while the browser is verified."""
        return {"raw": self.raw, "client_id": self.client_id}


def _str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def launch_from_claims(claims: dict[str, Any], client_id: str) -> LaunchData:
    """Project already-validated claims into :class:`LaunchData`."""
    context = claims.get(CLAIM_CONTEXT) or {}
    custom = claims.get(CLAIM_CUSTOM) or {}
    nrps = claims.get(CLAIM_NRPS) or {}
    roles = [str(r) for r in claims.get(CLAIM_ROLES) or []]

    def custom_id(key: str) -> str | None:
        value = _str(custom.get(key))
        # An unsubstituted Canvas variable ("$Canvas.course.id") means "not available".
        return None if value is None or value.startswith("$") else value

    return LaunchData(
        issuer=str(claims["iss"]),
        client_id=client_id,
        deployment_id=str(claims[CLAIM_DEPLOYMENT_ID]),
        subject=str(claims["sub"]),
        roles=tuple(roles),
        course_roles=frozenset(map_roles(roles)),
        context_id=str(context["id"]),
        context_title=_str(context.get("title")),
        context_label=_str(context.get("label")),
        resource_link_id=str((claims.get(CLAIM_RESOURCE_LINK) or {}).get("id")),
        canvas_course_id=custom_id("canvas_course_id"),
        canvas_user_id=custom_id("canvas_user_id"),
        sis_user_id=custom_id("canvas_user_sis_id")
        or _str((claims.get(CLAIM_LIS) or {}).get("person_sourcedid")),
        name=_str(claims.get("name")),
        given_name=_str(claims.get("given_name")),
        family_name=_str(claims.get("family_name")),
        email=_str(claims.get("email")),
        nrps_url=_str(nrps.get("context_memberships_url")),
        is_test_user=TEST_USER_ROLE in roles,
        target_link_uri=str(claims.get(CLAIM_TARGET_LINK_URI)),
        raw=claims,
    )
