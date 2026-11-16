# SPDX-License-Identifier: AGPL-3.0-or-later
"""The roles a person can hold, and what each one is: the one list.

Every other module, and every screen, takes its role lists from here. The screens never keep a
list of their own: the API tells them what the signed-in person may do
(``/learners/me``) and which roles they may grant (``/admin/grantable-roles``).

The names are also a database constraint (``db.models.identity.ROLES``); a test keeps the two
in step.
"""

from __future__ import annotations

from typing import Final, Literal

Role = Literal[
    "student",
    "lecturer",
    "course_admin",
    "issuer_manager",
    "reviewer",
    "dept_admin",
    "inst_admin",
]
#: Roles granted in OpenCredential itself. Students come from Canvas enrolments only.
GrantableRole = Literal[
    "lecturer", "course_admin", "issuer_manager", "reviewer", "dept_admin", "inst_admin"
]
ScopeType = Literal["institution", "org_unit", "issuer", "course"]

#: Staff of one course: they create, edit and award that course's badges.
COURSE_STAFF: Final[frozenset[str]] = frozenset({"lecturer", "course_admin"})
#: Administrators: of the whole institution, or of the departments they are given.
ADMIN_ROLES: Final[frozenset[str]] = frozenset({"dept_admin", "inst_admin"})
#: Everyone who works on badges rather than earning them: they see the staff screens.
STAFF_ROLES: Final[frozenset[str]] = COURSE_STAFF | ADMIN_ROLES | {"issuer_manager"}

#: Where each role is held. A role is granted at exactly one kind of scope.
ROLE_SCOPE: Final[dict[str, ScopeType]] = {
    "student": "course",
    "lecturer": "course",
    "course_admin": "course",
    "issuer_manager": "issuer",
    "reviewer": "org_unit",
    "dept_admin": "org_unit",
    "inst_admin": "institution",
}

#: Roles a department administrator may delegate inside their own org units (spec §2.3).
DEPT_GRANTABLE: Final[tuple[str, ...]] = (
    "lecturer",
    "course_admin",
    "issuer_manager",
    "reviewer",
    "dept_admin",
)
#: Roles granted in OpenCredential itself, in the order the screens offer them.
GRANTABLE: Final[tuple[str, ...]] = (*DEPT_GRANTABLE, "inst_admin")


def is_staff(roles: set[str] | frozenset[str]) -> bool:
    return bool(roles & STAFF_ROLES)


def is_admin(roles: set[str] | frozenset[str]) -> bool:
    return bool(roles & ADMIN_ROLES)
