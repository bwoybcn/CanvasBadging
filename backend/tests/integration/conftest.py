# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import httpx
import pytest

pytestmark = pytest.mark.db


def make_institution(conn, slug: str, *, demo: bool = True) -> uuid.UUID:  # type: ignore[no-untyped-def]
    iid = uuid.uuid4()
    conn.execute(
        "INSERT INTO app.institutions (id, slug, name, branding, policy, retention, categories,"
        " is_demo, status) VALUES (%s, %s, %s, '{}', '{}', '{}', '{}', %s, 'active')",
        [iid, slug, slug.title(), demo],
    )
    return iid


def make_user(conn, iid: uuid.UUID, name: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    uid = uuid.uuid4()
    conn.execute(
        "INSERT INTO app.users (id, institution_id, display_name, status)"
        " VALUES (%s, %s, %s, 'active')",
        [uid, iid, name],
    )
    return uid


@pytest.fixture
def two_tenants(owner_conn) -> Iterator[dict[str, uuid.UUID]]:  # type: ignore[no-untyped-def]
    suffix = uuid.uuid4().hex[:8]
    a = make_institution(owner_conn, f"alpha-{suffix}")
    b = make_institution(owner_conn, f"beta-{suffix}")
    ua = make_user(owner_conn, a, "Alice Alpha")
    ub = make_user(owner_conn, b, "Bob Beta")
    owner_conn.commit()
    yield {"a": a, "b": b, "user_a": ua, "user_b": ub}


@pytest.fixture(scope="session")
def signer_available() -> bool:
    url = os.environ.get("OC_SIGNER_URL", "http://localhost:8790")
    try:
        ok = httpx.get(f"{url}/readyz", timeout=2).status_code == 200
    except httpx.HTTPError:
        ok = False
    if not ok:
        msg = f"signer not reachable at {url}"
        if os.environ.get("OC_TEST_REQUIRE_SIGNER") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    return ok
