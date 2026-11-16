# SPDX-License-Identifier: AGPL-3.0-or-later
"""LTI 1.3 launch: one positive path per binding method and one negative test per check
(ADR-0008: iss, aud, azp, exp, iat, nonce replay, state, deployment, message type, version,
signature, unknown kid), plus role mapping and course mapping (spec §4.1-4.2, §20 Phase 2)."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from joserfc.jwk import OctKey, RSAKey
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.lti import claims as c
from opencredential.settings import get_settings
from tests.integration import lti_platform as lp
from tests.integration.lti_platform import DROP

pytestmark = pytest.mark.db


@pytest.fixture
def world(database: None) -> Iterator[dict[str, Any]]:
    """A non-demo institution with one registered Canvas integration and deployment."""
    suffix = uuid.uuid4().hex[:8]
    client_id = f"{lp.CLIENT_ID}{suffix}"
    with owner_session() as db:
        inst = m.Institution(slug=f"lti-{suffix}", name="LTI Test University", is_demo=False)
        db.add(inst)
        db.flush()
        integ = m.CanvasIntegration(
            institution_id=inst.id,
            name="Canvas",
            base_url=lp.BASE,
            lti_issuer=lp.ISS,
            lti_client_id=client_id,
            lti_auth_url=f"{lp.BASE}/api/lti/authorize_redirect",
            lti_token_url=f"{lp.BASE}/login/oauth2/token",
            lti_jwks_url=f"{lp.BASE}/api/lti/security/jwks",
            status="active",
        )
        db.add(integ)
        db.flush()
        db.add(
            m.LtiDeployment(
                institution_id=inst.id,
                canvas_integration_id=integ.id,
                deployment_id=lp.DEPLOYMENT_ID,
                scope="account",
            )
        )
        iid, integ_id = inst.id, integ.id
    platform = lp.Platform()
    platform.install()
    client = TestClient(create_app(get_settings()))
    yield {
        "iid": iid,
        "integration_id": integ_id,
        "client_id": client_id,
        "platform": platform,
        "client": client,
    }


def _login(w: dict[str, Any], **kw: Any) -> lp.Login:
    return lp.login(w["client"], client_id=w["client_id"], **kw)


def _claims(w: dict[str, Any], nonce: str, **over: Any) -> dict[str, Any]:
    base = {"aud": w["client_id"], "azp": w["client_id"]}
    base.update(over)
    return w["platform"].claims(nonce, **base)


def _launch(w: dict[str, Any], state: str, token: str) -> Any:
    return w["client"].post("/lti/launch", data={"state": state, "id_token": token})


def _code(resp: Any) -> str:
    match = re.search(r"Error code: ([A-Z_]+)", resp.text)
    return match.group(1) if match else f"<no error code: {resp.status_code}>"


def _session(resp: Any) -> tuple[str, str]:
    assert resp.status_code == 200, resp.text
    cfg = json.loads(re.search(r'id="oc-cfg">(.*?)</script>', resp.text).group(1))  # type: ignore[union-attr]
    frag = parse_qs(urlsplit(cfg["url"]).fragment)
    return frag["session"][0], frag["course"][0]


def _me(w: dict[str, Any], token: str) -> dict[str, Any]:
    r = w["client"].get("/api/v1/learners/me", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return dict(r.json())


# ---- happy paths -----------------------------------------------------------------------------


def test_instructor_launch_with_cookie_shows_user_and_course(world: dict[str, Any]) -> None:
    lg = _login(world)
    assert lg.cookie_name and lg.browser_secret
    redirect = parse_qs(urlsplit(lg.response.headers["location"]).query)
    assert redirect["redirect_uri"] == [lp.LAUNCH_URL]
    assert redirect["lti_message_hint"] == ["msg-hint"]
    assert redirect["prompt"] == ["none"] and redirect["response_mode"] == ["form_post"]

    resp = _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
    token, course_id = _session(resp)
    assert "frame-ancestors https://canvas.test.example" in resp.headers["content-security-policy"]
    me = _me(world, token)
    assert me["display_name"] == "Tess Teacher"
    assert me["email"] == "tess@example.ac.uk"
    assert me["session_method"] == "lti"
    lc = me["launch_course"]
    assert lc["id"] == course_id
    assert lc["title"] == "OpenCredential W3 Test Course"
    assert lc["canvas_course_id"] == "4"
    assert lc["course_code"] == "OCW3"
    assert lc["roles"] == ["lecturer"] and lc["view"] == "lecturer"
    assert lc["status"] == "inactive"  # activation is a separate, explicit step

    with owner_session() as db:
        course = db.get(m.Course, uuid.UUID(course_id))
        assert course is not None
        assert course.lti_context_id == lp.CONTEXT_ID
        assert course.lti_nrps_url and course.lti_nrps_url.endswith("/names_and_roles")
        ids = {
            (e.kind, e.value)
            for e in db.scalars(
                select(m.ExternalIdentity).where(m.ExternalIdentity.institution_id == world["iid"])
            )
        }
        assert ("lti_sub", "a1b2c3-user") in ids and ("canvas_user_id", "2") in ids
        actions = set(
            db.scalars(
                select(m.AuditEvent.action).where(m.AuditEvent.institution_id == world["iid"])
            )
        )
        assert "session.lti_launch" in actions


def test_relaunch_reuses_user_and_course(world: dict[str, Any]) -> None:
    ids = set()
    for _ in range(2):
        lg = _login(world)
        token, course_id = _session(
            _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
        )
        ids.add((_me(world, token)["id"], course_id))
    assert len(ids) == 1


def test_cookie_blocked_browser_uses_platform_storage(world: dict[str, Any]) -> None:
    lg = _login(world, storage_target="post_message_forwarding")
    page = lg.response.text
    assert "lti.put_data" in page and "post_message_forwarding" in page
    assert "script-src 'nonce-" in lg.response.headers["content-security-policy"]
    secret = lg.browser_secret
    world["client"].cookies.clear()  # third-party cookies blocked

    resp = _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
    assert resp.status_code == 200 and "lti.get_data" in resp.text
    ticket = re.search(r'name="ticket" value="([^"]+)"', resp.text).group(1)  # type: ignore[union-attr]

    bad = world["client"].post("/lti/verify", data={"ticket": ticket, "browser_secret": "nope"})
    assert _code(bad) == "BROWSER_BINDING_FAILED"
    # A failed attempt burns the ticket: no guessing loop.
    again = world["client"].post("/lti/verify", data={"ticket": ticket, "browser_secret": secret})
    assert _code(again) == "TICKET_INVALID"

    lg2 = _login(world, storage_target="post_message_forwarding")
    world["client"].cookies.clear()
    resp2 = _launch(world, lg2.state, world["platform"].sign(_claims(world, lg2.nonce)))
    ticket2 = re.search(r'name="ticket" value="([^"]+)"', resp2.text).group(1)  # type: ignore[union-attr]
    ok = world["client"].post(
        "/lti/verify", data={"ticket": ticket2, "browser_secret": lg2.browser_secret}
    )
    token, _ = _session(ok)
    assert _me(world, token)["launch_course"]["view"] == "lecturer"
    replay = world["client"].post(
        "/lti/verify", data={"ticket": ticket2, "browser_secret": lg2.browser_secret}
    )
    assert _code(replay) == "TICKET_INVALID"


def test_no_cookie_and_no_platform_storage_is_refused(world: dict[str, Any]) -> None:
    lg = _login(world)
    world["client"].cookies.clear()
    resp = _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
    assert resp.status_code == 401 and _code(resp) == "BROWSER_BINDING_FAILED"


# ---- role mapping ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "expected", "view"),
    [
        ([lp.LEARNER], ["student"], "student"),
        ([lp.TA], ["lecturer"], "lecturer"),
        ([lp.CONTEXT_ADMIN], ["course_admin", "lecturer"], "lecturer"),
        ([lp.INST_ADMIN, lp.LEARNER], ["student"], "student"),  # no institution-wide powers
        ([lp.INSTRUCTOR, lp.TEST_USER], [], "student"),  # Student View is never staff
        ([lp.INST_ADMIN], [], "student"),
    ],
)
def test_role_mapping(
    world: dict[str, Any], roles: list[str], expected: list[str], view: str
) -> None:
    lg = _login(world)
    token, _ = _session(
        _launch(
            world,
            lg.state,
            world["platform"].sign(
                _claims(
                    world, lg.nonce, **{c.CLAIM_ROLES: roles, "sub": f"user-{uuid.uuid4().hex[:6]}"}
                )
            ),
        )
    )
    lc = _me(world, token)["launch_course"]
    assert lc["roles"] == expected and lc["view"] == view


def test_roles_follow_canvas_and_ignore_client_input(world: dict[str, Any]) -> None:
    lg = _login(world)
    claims = _claims(world, lg.nonce, **{c.CLAIM_ROLES: [lp.INSTRUCTOR]})
    _session(_launch(world, lg.state, world["platform"].sign(claims)))

    # Demoted in Canvas: the next launch revokes the lecturer role. Extra form fields claiming a
    # role are ignored entirely.
    lg = _login(world)
    claims = _claims(world, lg.nonce, **{c.CLAIM_ROLES: [lp.LEARNER]})
    resp = world["client"].post(
        "/lti/launch",
        data={
            "state": lg.state,
            "id_token": world["platform"].sign(claims),
            "roles": "Instructor",
            "role": "inst_admin",
        },
    )
    token, _ = _session(resp)
    lc = _me(world, token)["launch_course"]
    assert lc["roles"] == ["student"]


def test_test_user_role_mapping_unit() -> None:
    assert c.map_roles([lp.INSTRUCTOR, lp.TEST_USER]) == set()
    assert c.map_roles(["Learner"]) == {"student"}
    assert c.map_roles(["http://purl.imsglobal.org/vocab/lis/v2/membership/Learner#Learner"]) == {
        "student"
    }


# ---- negative: one per check -----------------------------------------------------------------

OTHER_KEY = RSAKey.generate_key(2048, auto_kid=True)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"iss": "https://evil.example"}, "ISSUER_MISMATCH"),
        ({"aud": "someone-else", "azp": DROP}, "AUDIENCE_MISMATCH"),
        ({"aud": ["{client}", "other"], "azp": "other"}, "AZP_MISMATCH"),
        ({"exp": int(time.time()) - 600}, "TOKEN_EXPIRED"),
        ({"iat": int(time.time()) + 600}, "TOKEN_NOT_YET_VALID"),
        ({"iat": int(time.time()) - 7200}, "TOKEN_TOO_OLD"),
        ({"nonce": "not-the-login-nonce"}, "NONCE_MISMATCH"),
        ({c.CLAIM_MESSAGE_TYPE: "LtiDeepLinkingRequest"}, "MESSAGE_TYPE_UNSUPPORTED"),
        ({c.CLAIM_VERSION: "1.1"}, "LTI_VERSION_UNSUPPORTED"),
        ({c.CLAIM_DEPLOYMENT_ID: "99:unknown"}, "DEPLOYMENT_UNKNOWN"),
        ({c.CLAIM_DEPLOYMENT_ID: DROP}, "DEPLOYMENT_MISSING"),
        ({c.CLAIM_CONTEXT: DROP}, "COURSE_CONTEXT_MISSING"),
        (
            {
                c.CLAIM_CONTEXT: {
                    "id": "g1",
                    "type": ["http://purl.imsglobal.org/vocab/lis/v2/group#Group"],
                }
            },
            "COURSE_CONTEXT_UNSUPPORTED",
        ),
        ({c.CLAIM_TARGET_LINK_URI: "https://evil.example/lti/launch"}, "TARGET_LINK_URI_MISMATCH"),
        ({c.CLAIM_RESOURCE_LINK: DROP}, "RESOURCE_LINK_MISSING"),
        ({c.CLAIM_ROLES: DROP}, "ROLES_MISSING"),
        ({"sub": ""}, "SUBJECT_MISSING"),
    ],
)
def test_invalid_claims_rejected(world: dict[str, Any], over: dict[str, Any], code: str) -> None:
    lg = _login(world)
    over = {
        k: (
            [world["client_id"] if x == "{client}" else x for x in v]
            if isinstance(v, list) and k == "aud"
            else v
        )
        for k, v in over.items()
    }
    claims = _claims(world, lg.nonce)
    for k, v in over.items():
        if v is DROP:
            claims.pop(k, None)
        else:
            claims[k] = v
    resp = _launch(world, lg.state, world["platform"].sign(claims))
    assert _code(resp) == code
    assert resp.status_code in (400, 401, 403)
    assert "session=" not in resp.text


def test_bad_signature_rejected(world: dict[str, Any]) -> None:
    lg = _login(world)
    forged = world["platform"].sign(
        _claims(world, lg.nonce), key=OTHER_KEY, kid=world["platform"].key.kid
    )
    assert _code(_launch(world, lg.state, forged)) == "SIGNATURE_INVALID"


def test_unknown_kid_refetches_once_then_rejects(world: dict[str, Any]) -> None:
    lg = _login(world)
    before = world["platform"].jwks_hits
    forged = world["platform"].sign(_claims(world, lg.nonce), key=OTHER_KEY)
    assert _code(_launch(world, lg.state, forged)) == "SIGNATURE_INVALID"
    assert world["platform"].jwks_hits - before <= 1


def test_key_rotation_is_picked_up(world: dict[str, Any]) -> None:
    lg = _login(world)
    _session(_launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce))))
    world["platform"].key = RSAKey.generate_key(2048, auto_kid=True)  # Canvas rotates keys
    from opencredential.lti import platform_keys

    platform_keys.platform_jwks._entries[f"{lp.BASE}/api/lti/security/jwks"].fetched -= 60
    lg = _login(world)
    _session(_launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce))))


@pytest.mark.parametrize("alg", ["HS256", "none"])
def test_disallowed_algorithms(world: dict[str, Any], alg: str) -> None:
    lg = _login(world)
    claims = _claims(world, lg.nonce)
    if alg == "none":
        import base64

        def b64(d: dict[str, Any]) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        token = f"{b64({'alg': 'none'})}.{b64(claims)}."
    else:
        from joserfc import jwt

        token = jwt.encode({"alg": "HS256"}, claims, OctKey.generate_key(256))
    assert _code(_launch(world, lg.state, token)) == "ALG_NOT_ALLOWED"


def test_malformed_token(world: dict[str, Any]) -> None:
    lg = _login(world)
    assert _code(_launch(world, lg.state, "not-a-jwt")) == "ID_TOKEN_MALFORMED"


# ---- replay and state ------------------------------------------------------------------------


def test_replayed_launch_is_rejected(world: dict[str, Any]) -> None:
    lg = _login(world)
    token = world["platform"].sign(_claims(world, lg.nonce))
    _session(_launch(world, lg.state, token))
    again = _launch(world, lg.state, token)
    assert again.status_code == 401 and _code(again) == "STATE_REPLAYED"


def test_same_token_with_fresh_state_is_rejected(world: dict[str, Any]) -> None:
    lg = _login(world)
    token = world["platform"].sign(_claims(world, lg.nonce))
    _session(_launch(world, lg.state, token))
    lg2 = _login(world)
    assert _code(_launch(world, lg2.state, token)) == "NONCE_MISMATCH"


def test_nonce_reuse_is_rejected(world: dict[str, Any]) -> None:
    lg = _login(world)
    with owner_session() as db:
        db.add(
            m.LtiNonceUsed(
                nonce=lg.nonce, iss=lp.ISS, expires_at=datetime.now(UTC) + timedelta(hours=1)
            )
        )
    resp = _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
    assert _code(resp) == "NONCE_REPLAYED"


def test_rejected_launch_still_burns_state(world: dict[str, Any]) -> None:
    lg = _login(world)
    bad = world["platform"].sign(_claims(world, lg.nonce, iss="https://evil.example"))
    assert _code(_launch(world, lg.state, bad)) == "ISSUER_MISMATCH"
    good = world["platform"].sign(_claims(world, lg.nonce))
    assert _code(_launch(world, lg.state, good)) == "STATE_REPLAYED"


def test_unknown_state(world: dict[str, Any]) -> None:
    lg = _login(world)
    resp = _launch(world, "forged-state", world["platform"].sign(_claims(world, lg.nonce)))
    assert resp.status_code == 401 and _code(resp) == "STATE_UNKNOWN"


def test_expired_state(world: dict[str, Any]) -> None:
    lg = _login(world)
    with owner_session() as db:
        row = db.scalar(select(m.LtiLaunchState).where(m.LtiLaunchState.state == lg.state))
        assert row is not None
        row.created_at = row.created_at.replace(year=row.created_at.year - 1)
    resp = _launch(world, lg.state, world["platform"].sign(_claims(world, lg.nonce)))
    assert _code(resp) == "STATE_EXPIRED"


def test_missing_state_and_token(world: dict[str, Any]) -> None:
    assert _code(world["client"].post("/lti/launch", data={"id_token": "x"})) == "STATE_MISSING"
    assert _code(world["client"].post("/lti/launch", data={"state": "x"})) == "ID_TOKEN_MISSING"


# ---- login initiation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"iss": "https://unknown.example"}, "UNKNOWN_REGISTRATION"),
        ({"client_id": "999"}, "UNKNOWN_REGISTRATION"),
        ({"target_link_uri": "https://evil.example/x"}, "TARGET_LINK_URI_MISMATCH"),
        ({"login_hint": ""}, "LOGIN_PARAMS_MISSING"),
    ],
)
def test_login_rejections(world: dict[str, Any], params: dict[str, str], code: str) -> None:
    q = {
        "iss": lp.ISS,
        "login_hint": "h",
        "target_link_uri": lp.LAUNCH_URL,
        "client_id": world["client_id"],
    }
    q.update(params)
    resp = world["client"].get("/lti/login", params=q, follow_redirects=False)
    assert resp.status_code in (400, 403) and _code(resp) == code


def test_disabled_registration_cannot_log_in(world: dict[str, Any]) -> None:
    with owner_session() as db:
        integ = db.get(m.CanvasIntegration, world["integration_id"])
        assert integ is not None
        integ.status = "disabled"
    q = {
        "iss": lp.ISS,
        "login_hint": "h",
        "target_link_uri": lp.LAUNCH_URL,
        "client_id": world["client_id"],
    }
    resp = world["client"].get("/lti/login", params=q, follow_redirects=False)
    assert _code(resp) == "REGISTRATION_DISABLED"


def test_tool_jwks_and_canvas_config(world: dict[str, Any]) -> None:
    jwks = world["client"].get("/lti/jwks").json()
    assert jwks["keys"][0]["kty"] == "RSA" and "d" not in jwks["keys"][0]
    cfg = world["client"].get("/lti/config.json").json()
    placement = cfg["extensions"][0]["settings"]["placements"][0]
    assert placement["placement"] == "course_navigation"
    assert placement["text"] == "Badges" and placement["default"] == "disabled"
    assert cfg["custom_fields"]["canvas_course_id"] == "$Canvas.course.id"
    assert cfg["public_jwk"]["kid"] == jwks["keys"][0]["kid"]


def test_sign_in_clean_up_follows_the_configured_time_limit(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole-product review, 16 Nov 2026, finding 19: the clean-up job deleted sign-ins older
    than ten minutes whatever ``OC_LTI_STATE_TTL_SECONDS`` said, so with a longer limit a
    sign-in still in progress lost its record and failed."""
    from opencredential.jobs.tasks import purge_lti_state
    from opencredential.settings import get_settings

    lg = _login(world)
    with owner_session() as db:
        row = db.scalar(select(m.LtiLaunchState).where(m.LtiLaunchState.state == lg.state))
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(minutes=15)

    def still_there() -> bool:
        with owner_session() as db:
            return (
                db.scalar(select(m.LtiLaunchState.id).where(m.LtiLaunchState.state == lg.state))
                is not None
            )

    monkeypatch.setattr(get_settings(), "lti_state_ttl_seconds", 1800)
    purge_lti_state(0)
    assert still_there()  # fifteen minutes old, half an hour allowed
    monkeypatch.setattr(get_settings(), "lti_state_ttl_seconds", 600)
    purge_lti_state(0)
    assert not still_there()
