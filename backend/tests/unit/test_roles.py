# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one list of roles (authz/roles.py) agrees with itself and with the database."""

from __future__ import annotations

from typing import get_args

from opencredential.authz import roles
from opencredential.db.models.identity import ROLES


def test_the_role_type_is_the_database_list() -> None:
    assert get_args(roles.Role) == ROLES
    assert set(get_args(roles.GrantableRole)) == set(roles.GRANTABLE) == set(ROLES) - {"student"}


def test_every_role_has_exactly_one_kind_of_scope() -> None:
    assert set(roles.ROLE_SCOPE) == set(ROLES)
    assert set(roles.ROLE_SCOPE.values()) == set(get_args(roles.ScopeType))


def test_the_groups_are_made_of_known_roles() -> None:
    for group in (roles.COURSE_STAFF, roles.ADMIN_ROLES, roles.STAFF_ROLES):
        assert group <= set(ROLES)
    assert set(roles.DEPT_GRANTABLE) < set(roles.GRANTABLE)
    assert "inst_admin" not in roles.DEPT_GRANTABLE  # a department cannot make one
    assert roles.is_staff({"issuer_manager"}) and not roles.is_staff({"student", "reviewer"})
    assert roles.is_admin({"dept_admin"}) and not roles.is_admin({"lecturer"})
