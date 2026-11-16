# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one definition of whether a badge still stands (credentials/state.py): the Python rule
and the SQL rule must give the same answer for every combination of facts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import DateTime, String, cast, literal, select

from opencredential.credentials.state import ALL_STATES, credential_state, state_sql
from opencredential.db.session import tenant_session

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
PAST, FUTURE = NOW - timedelta(days=1), NOW + timedelta(days=1)

EXPECTED = {
    (None, None): "active",
    (None, FUTURE): "active",
    (None, PAST): "expired",
    ("active", None): "active",
    ("active", FUTURE): "active",
    ("active", PAST): "expired",
    # Withdrawal by the issuer wins over the expiry date.
    ("revoked", None): "revoked",
    ("revoked", FUTURE): "revoked",
    ("revoked", PAST): "revoked",
    ("suspended", None): "suspended",
    ("suspended", FUTURE): "suspended",
    ("suspended", PAST): "suspended",
}


@pytest.mark.parametrize(("status_state", "valid_until"), list(EXPECTED))
def test_python_and_sql_give_the_same_state(
    database: None, status_state: str | None, valid_until: datetime | None
) -> None:
    expected = EXPECTED[(status_state, valid_until)]
    assert credential_state(status_state, valid_until, NOW) == expected
    expression = state_sql(
        NOW,
        status_state=cast(literal(status_state), String),
        valid_until=cast(literal(valid_until), DateTime(timezone=True)),
    )
    with tenant_session(None) as db:
        assert db.scalar(select(expression)) == expected


def test_expiry_is_judged_at_the_moment_asked() -> None:
    assert credential_state(None, NOW, NOW) == "active"  # not yet past
    assert credential_state(None, NOW, NOW + timedelta(seconds=1)) == "expired"
    assert credential_state(None, PAST) == "expired"  # "now" defaults to the clock


def test_every_state_is_reachable() -> None:
    assert set(EXPECTED.values()) == set(ALL_STATES)
