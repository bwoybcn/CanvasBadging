# SPDX-License-Identifier: AGPL-3.0-or-later
"""W8 security tests (spec §15.3, §15.4, §19.6; RTM S-AUTHN-01, S-AUTHZ-STU, S-TENANT-01,
S-FUZZ-01, S-HDR-01, S-TOKEN-01).

The route matrices are generated from the application's own route table, so a route added
later is covered automatically: it must refuse anonymous callers, must not let a student
change anything that is not theirs, and must not let one institution's administrator read or
change another institution's records. Allowlists below name every exception and say why.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.test_w7_governance import _authorised_issuer, _issue_to, _manual_badge
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
PARAM = re.compile(r"{(\w+)}")

# Routes under /api/v1 that work without a session, on purpose.
PUBLIC_API = {
    ("POST", "/api/v1/verify"),  # anyone may check a credential (spec §16.2)
    ("GET", "/api/v1/artwork-templates"),  # the fixed catalogue of artwork shapes; no data
}

# Actions any enrolled learner may take on their own course: asking for a (rate-limited)
# refresh of their progress from Canvas (spec §4.4). Answers 202 or 429, never more.
STUDENT_OWN_COURSE = {("POST", "/api/v1/courses/{course_id}/sync")}

# Mutating routes a student may legitimately call. With another learner's ids they must still
# answer 404 (checked below); with their own they succeed.
STUDENT_MAY_CALL = {
    ("PUT", "/api/v1/credentials/{credential_id}/share"),
    ("DELETE", "/api/v1/credentials/{credential_id}/share"),
    ("POST", "/api/v1/credentials/{credential_id}/share/preview"),
    ("POST", "/api/v1/credentials/{credential_id}/revocation-requests"),
    ("POST", "/api/v1/verify"),
}


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def _api_routes(client: TestClient) -> list[tuple[str, str]]:
    """Every /api/v1 operation, from the app's own OpenAPI document (the route table)."""
    schema = client.app.openapi()  # type: ignore[attr-defined]
    out = [
        (method.upper(), path)
        for path, ops in schema["paths"].items()
        if path.startswith("/api/v1")
        for method in ops
    ]
    assert len(out) > 80, "route table looks incomplete"
    return sorted(out)


def _fill(path: str, ids: dict[str, str]) -> str:
    return PARAM.sub(lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> Any:
    kw: dict[str, Any] = {"headers": headers}
    if method in MUTATING and method != "DELETE":
        kw["json"] = {}
    return client.request(method, path, **kw)


@pytest.fixture
def two_worlds(client: TestClient, signer_available: bool) -> Iterator[dict[str, Any]]:
    a = build_world(client)
    b = build_world(client)
    out: dict[str, Any] = {"a": a, "b": b}
    for key, w in (("a", a), ("b", b)):
        with registry.override(w.lms):
            issuer = _authorised_issuer(w)
            definition = _manual_badge(w, issuer)
            out[f"{key}_ids"] = {
                "definition_id": definition,
                "issuer_id": issuer,
                "course_id": str(w.course_id),
                "credential_id": _issue_to(w, definition, "s2"),
                "user_id": str(w.users["s2"]),
                "version_id": str(
                    w.get("lecturer", f"/api/v1/achievements/{definition}").json()[
                        "live_version_id"
                    ]
                ),
            }
            out[f"{key}_own"] = _issue_to(w, definition, "s1")
    with registry.override(a.lms):
        yield out


# ---- S-AUTHN-01 ------------------------------------------------------------------------------


def test_every_api_route_refuses_anonymous_callers(client: TestClient) -> None:
    allowed: list[str] = []
    for method, path in _api_routes(client):
        if (method, path) in PUBLIC_API:
            continue
        r = _call(client, method, _fill(path, {}), {})
        if r.status_code != 401:
            allowed.append(f"{method} {path} -> {r.status_code}")
    assert allowed == []


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0.",  # alg=none
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl",  # forged HMAC
    ],
)
def test_forged_or_malformed_tokens_are_refused(client: TestClient, token: str) -> None:
    r = client.get("/api/v1/learners/me", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "Traceback" not in r.text


def test_tampered_session_token_is_refused(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    token = a.h("s1")["authorization"].split()[1]
    head, body, sig = token.split(".")[:3] if token.count(".") >= 2 else (token, "", "")
    if body:
        tampered = ".".join([head, body[:-2] + ("AA" if body[-2:] != "AA" else "BB"), sig])
    else:
        tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    r = a.client.get("/api/v1/learners/me", headers={"authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


# ---- S-AUTHZ-STU -----------------------------------------------------------------------------


def test_student_cannot_change_anything_that_is_not_theirs(two_worlds: dict[str, Any]) -> None:
    """Every mutating route, called by student s1 with real ids from their own institution
    (another learner's credential, the course's badge, issuer, staff decisions…)."""
    a: World = two_worlds["a"]
    ids = two_worlds["a_ids"]
    leaks: list[str] = []
    for method, path in _api_routes(a.client):
        if method not in MUTATING or (method, path) == ("POST", "/api/v1/verify"):
            continue
        r = _call(a.client, method, _fill(path, ids), a.h("s1"))
        if (method, path) in STUDENT_OWN_COURSE:
            assert r.status_code in (202, 429), (path, r.status_code)
            continue
        if r.status_code < 400 or r.status_code >= 500:
            leaks.append(f"{method} {path} -> {r.status_code}")
        # 404 (or 422 when the body is checked first, which happens whether or not the
        # credential exists, so it discloses nothing)
        if (method, path) in STUDENT_MAY_CALL and r.status_code not in (404, 422):
            leaks.append(f"{method} {path} on another learner's credential -> {r.status_code}")
    assert leaks == []


def test_student_reads_only_their_own_records(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    ids = two_worlds["a_ids"]
    other = ids["credential_id"]
    for path in (
        f"/api/v1/credentials/{other}",
        f"/api/v1/credentials/{other}/export",
        f"/api/v1/credentials/{other}/share",
    ):
        assert a.get("s1", path).status_code == 404, path
    mine = {c["id"] for c in a.get("s1", "/api/v1/learners/me/credentials").json()}
    assert two_worlds["a_own"] in mine and other not in mine
    for path in (
        "/api/v1/admin/credentials",
        "/api/v1/admin/people",
        "/api/v1/admin/audit",
        f"/api/v1/courses/{ids['course_id']}/progress",
    ):
        assert a.get("s1", path).status_code in (403, 404), path
    # The awards queue answers a student with nothing at all (it lists what the caller may
    # decide on, which for a student is nothing).
    r = a.get("s1", "/api/v1/awards")
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert ids["user_id"] not in r.text and str(a.users["s3"]) not in r.text


# ---- S-TENANT-01 -----------------------------------------------------------------------------


def test_admin_of_one_institution_cannot_touch_another(two_worlds: dict[str, Any]) -> None:
    """Institution A's administrator calls every API route with Institution B's ids. Nothing
    may succeed, and list endpoints may not mention any of B's records."""
    a: World = two_worlds["a"]
    b: World = two_worlds["b"]
    b_ids = two_worlds["b_ids"]
    secrets = {str(b.iid), str(b.course_id), str(b.issuer_id), *b_ids.values(), two_worlds["b_own"]}
    secrets |= {str(u) for u in b.users.values()}
    problems: list[str] = []
    for method, path in _api_routes(a.client):
        if (method, path) == ("POST", "/api/v1/verify"):
            continue
        has_ids = bool(PARAM.search(path))
        r = _call(a.client, method, _fill(path, b_ids), a.h("admin"))
        if r.status_code >= 500:
            problems.append(f"{method} {path} -> {r.status_code}")
        elif has_ids and r.status_code < 400:
            problems.append(f"{method} {path} with B's ids -> {r.status_code}")
        elif not has_ids and method == "GET" and r.status_code == 200:
            leaked = [s for s in secrets if s in r.text]
            if leaked:
                problems.append(f"GET {path} mentions B's records: {leaked[:2]}")
    assert problems == []


# ---- S-FUZZ-01 -------------------------------------------------------------------------------

SQLI = ["' OR '1'='1", "1; DROP TABLE app.credentials;--", "%' UNION SELECT id FROM app.users--"]
XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def test_injection_strings_in_queries_are_inert(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    b: World = two_worlds["b"]
    for s in SQLI:
        for path in ("/api/v1/admin/people", "/api/v1/admin/audit"):
            r = a.client.get(path, params={"q": s, "category": s}, headers=a.h("admin"))
            assert r.status_code in (200, 422), (path, r.status_code)
            assert str(b.users["s1"]) not in r.text
    with a.db() as db:
        from sqlalchemy import func, select

        from opencredential.db import models as m

        assert db.scalar(select(func.count()).select_from(m.Credential)) >= 1


def test_script_in_badge_text_is_escaped_on_public_pages(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    body = a.publish(
        {"mode": "ALL", "rules": [{"type": "manual_approval"}]},
        title=f"Evil {XSS}"[:120],
        short_description=f"Desc {XSS}",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )
    version = body["live_version_id"]
    # The published achievement is JSON-LD: the text is data, served as JSON with nosniff, so a
    # browser never renders it as HTML.
    page = a.client.get(f"/achievements/{version}")
    assert page.status_code == 200
    assert "json" in page.headers["content-type"]
    assert page.headers["x-content-type-options"] == "nosniff"
    cred = _issue_to(a, body["id"], "s3")
    share = a.put("s3", f"/api/v1/credentials/{cred}/share", {})
    assert share.status_code == 200, share.text
    share_path = "/verify/" + share.json()["share"]["url"].rsplit("/", 1)[1]
    html = a.client.get(share_path).text
    assert "<script>alert(" not in html
    assert "<img src=x onerror" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/assets/..%2f..%2fetc%2fpasswd/content",
        "/assets/public/..%2f..%2fetc%2fpasswd.svg",
        "/assets/public/" + "a" * 64 + ".svg%00.png",
        "/verify/..%2f..%2fetc%2fpasswd",
        "/status/../../etc/passwd/1",
    ],
)
def test_path_traversal_is_refused(two_worlds: dict[str, Any], path: str) -> None:
    a: World = two_worlds["a"]
    r = a.client.get(path, headers=a.h("admin"))
    assert r.status_code in (400, 404, 422)
    assert "root:" not in r.text


def test_malformed_and_oversized_bodies_fail_cleanly(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    h = {**a.h("lecturer"), "content-type": "application/json"}
    for raw in (b"{", b"\xff\xfe\x00", b"[]" * 10, b'{"fields": {"title": "\\u0000"}}'):
        r = a.client.post("/api/v1/achievements", content=raw, headers=h)
        assert 400 <= r.status_code < 500, (raw[:10], r.status_code)
        assert "Traceback" not in r.text
    big = b'{"a": "' + b"x" * 400_000 + b'"}'
    r = a.client.post("/api/v1/verify", content=big, headers={"content-type": "application/json"})
    assert r.status_code in (413, 422)
    r = a.client.get("/api/v1/admin/audit", params={"limit": 10**12}, headers=a.h("admin"))
    assert r.status_code == 422


def test_svg_upload_cannot_carry_script(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)" width="10" height="10">'
        b'<script>alert(2)</script><a href="javascript:alert(3)"><rect width="10" height="10"/>'
        b"</a></svg>"
    )
    r = a.client.post(
        "/api/v1/assets",
        files={"file": ("x.svg", svg, "image/svg+xml")},
        data={"alt_text": "A small square used in a security test"},
        headers=a.h("lecturer"),
    )
    if r.status_code == 201:
        content = a.client.get(f"/api/v1/assets/{r.json()['id']}/content", headers=a.h("lecturer"))
        assert b"<script" not in content.content and b"onload" not in content.content
        assert b"javascript:" not in content.content
        assert "sandbox" in content.headers.get("content-security-policy", "")
    else:
        assert r.status_code in (400, 415, 422)


# ---- S-HDR-01, S-TOKEN-01 --------------------------------------------------------------------


def test_security_headers(two_worlds: dict[str, Any]) -> None:
    a: World = two_worlds["a"]
    api = a.get("s1", "/api/v1/learners/me")
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["cache-control"] == "no-store"
    assert "noindex" in api.headers["x-robots-tag"]
    https = a.client.get("/api/v1/learners/me", headers={**a.h("s1"), "x-forwarded-proto": "https"})
    assert https.headers["strict-transport-security"].startswith("max-age=")
    page = a.client.get("/verify")
    assert "default-src" in page.headers["content-security-policy"]


def test_no_canvas_token_or_secret_in_any_api_response(two_worlds: dict[str, Any]) -> None:
    """Spec §15.3: Canvas API tokens are never in browser-reachable state. Walk every GET an
    administrator can call and look for token-shaped fields."""
    a: World = two_worlds["a"]
    ids = two_worlds["a_ids"]
    bad = re.compile(r'"(access_token|refresh_token|client_secret|private_key|d)"\s*:', re.I)
    for method, path in _api_routes(a.client):
        if method != "GET":
            continue
        r = a.client.get(_fill(path, ids), headers=a.h("admin"))
        if r.status_code == 200 and r.headers.get("content-type", "").startswith(
            "application/json"
        ):
            assert not bad.search(r.text), path
