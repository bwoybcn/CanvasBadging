# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether an issued badge still stands: the one definition, for Python and for SQL.

A badge that has been issued is in exactly one of four states:

* ``revoked`` or ``suspended``: the issuer has withdrawn it (its entry in the status list);
* ``expired``: nobody withdrew it, but its ``valid_until`` date has passed;
* ``active``: none of the above.

Withdrawal wins over expiry: a badge revoked last year and expired last month is "revoked",
which is also what an outside verifier reports.

Every screen, report, export and count that says whether a badge is valid goes through
:func:`credential_state` (one row in Python) or :func:`state_sql` (a filter or a count in
PostgreSQL). Both read the same two facts and are tested against each other, so a list, its
filter and its totals cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

from sqlalchemy import ColumnElement, case, literal

from opencredential.db.models import Credential, CredentialStatus

CredentialState = Literal["active", "revoked", "suspended", "expired"]
WithdrawnState = Literal["revoked", "suspended"]

ACTIVE: Final = "active"
REVOKED: Final = "revoked"
SUSPENDED: Final = "suspended"
EXPIRED: Final = "expired"

#: States in which the issuer has withdrawn the badge, so the holder no longer holds it.
WITHDRAWN_STATES: Final[tuple[WithdrawnState, ...]] = ("revoked", "suspended")
#: Every state, in the order screens list them.
ALL_STATES: Final[tuple[CredentialState, ...]] = ("active", "expired", "revoked", "suspended")


def credential_state(
    status_state: str | None, valid_until: datetime | None, now: datetime | None = None
) -> CredentialState:
    """The state of one issued badge, from its status-list state (``None`` when it has no
    status row) and its expiry date."""
    if status_state in WITHDRAWN_STATES:
        return cast(CredentialState, status_state)
    if valid_until is not None and valid_until < (now or datetime.now(UTC)):
        return "expired"
    return "active"


def state_of(
    cred: Credential, status: CredentialStatus | None, now: datetime | None = None
) -> CredentialState:
    """:func:`credential_state` for a loaded credential and its status row."""
    return credential_state(status.state if status is not None else None, cred.valid_until, now)


def is_withdrawn(state: str | None) -> bool:
    return state in WITHDRAWN_STATES


def state_sql(
    now: datetime, *, status_state: Any = None, valid_until: Any = None
) -> ColumnElement[str]:
    """The same rule as :func:`credential_state`, as a SQL expression.

    By default it reads ``credential_status.state`` and ``credentials.valid_until``, for a query
    that outer-joins the status row. Pass the two columns when they come from a subquery.
    """
    state_col = CredentialStatus.state if status_state is None else status_state
    until_col = Credential.valid_until if valid_until is None else valid_until
    return case(
        (state_col.in_(WITHDRAWN_STATES), state_col),
        (until_col < now, literal("expired")),
        else_=literal("active"),
    )
