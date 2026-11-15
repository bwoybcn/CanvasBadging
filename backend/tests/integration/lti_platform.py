# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fake LTI 1.3 platform for launch tests: signs id_tokens like Canvas and serves its JWKS."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from opencredential.lti import claims as c
from opencredential.lti.platform_keys import platform_jwks

ISS = "https://canvas.test.example"
BASE = "https://canvas.test.example"
CLIENT_ID = "10000000000042"
DEPLOYMENT_ID = "17:abcdef0123456789"
CONTEXT_ID = "ctx-4c2b"
LAUNCH_URL = "http://localhost:8000/lti/launch"

INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
LEARNER = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
TA = "http://purl.imsglobal.org/vocab/lis/v2/membership/Instructor#TeachingAssistant"
CONTEXT_ADMIN = "http://purl.imsglobal.org/vocab/lis/v2/membership#Administrator"
INST_ADMIN = "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
TEST_USER = "http://purl.imsglobal.org/vocab/lti/system/person#TestUser"


@dataclass
class Platform:
    key: RSAKey = field(default_factory=lambda: RSAKey.generate_key(2048, auto_kid=True))
    jwks_hits: int = 0

    def jwks(self) -> dict[str, Any]:
        return {"keys": [self.key.as_dict(private=False) | {"alg": "RS256", "use": "sig"}]}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/lti/security/jwks":
                self.jwks_hits += 1
                return httpx.Response(200, json=self.jwks())
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    def install(self) -> None:
        platform_jwks.clear()
        platform_jwks._transport = self.transport()

    def claims(self, nonce: str, **over: Any) -> dict[str, Any]:
        now = int(time.time())
        base: dict[str, Any] = {
            "iss": ISS,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "sub": "a1b2c3-user",
            "iat": now,
            "exp": now + 3600,
            "nonce": nonce,
            "name": "Tess Teacher",
            "given_name": "Tess",
            "family_name": "Teacher",
            "email": "tess@example.ac.uk",
            c.CLAIM_MESSAGE_TYPE: "LtiResourceLinkRequest",
            c.CLAIM_VERSION: "1.3.0",
            c.CLAIM_DEPLOYMENT_ID: DEPLOYMENT_ID,
            c.CLAIM_TARGET_LINK_URI: LAUNCH_URL,
            c.CLAIM_RESOURCE_LINK: {"id": "rl-1", "title": "Badges"},
            c.CLAIM_ROLES: [INSTRUCTOR],
            c.CLAIM_CONTEXT: {
                "id": CONTEXT_ID,
                "label": "OCW3",
                "title": "OpenCredential W3 Test Course",
                "type": ["http://purl.imsglobal.org/vocab/lis/v2/course#CourseOffering"],
            },
            c.CLAIM_CUSTOM: {"canvas_course_id": "4", "canvas_user_id": "2"},
            c.CLAIM_NRPS: {
                "context_memberships_url": f"{BASE}/api/lti/courses/4/names_and_roles",
                "service_versions": ["2.0"],
            },
        }
        for k, v in over.items():
            if v is _DROP:
                base.pop(k, None)
            else:
                base[k] = v
        return base

    def sign(
        self,
        claims: dict[str, Any],
        *,
        key: RSAKey | None = None,
        alg: str = "RS256",
        kid: str | None = None,
    ) -> str:
        k = key or self.key
        return jwt.encode({"alg": alg, "kid": kid or k.kid, "typ": "JWT"}, claims, k)


class _Drop:
    pass


_DROP = _Drop()
DROP: Any = _DROP


@dataclass
class Login:
    state: str
    nonce: str
    cookie_name: str | None
    browser_secret: str | None
    response: httpx.Response


def login(client: TestClient, *, storage_target: str | None = None, **params: str) -> Login:
    q = {
        "iss": ISS,
        "login_hint": "hint-123",
        "target_link_uri": LAUNCH_URL,
        "client_id": CLIENT_ID,
        "lti_deployment_id": DEPLOYMENT_ID,
        "lti_message_hint": "msg-hint",
    }
    if storage_target:
        q["lti_storage_target"] = storage_target
    q.update(params)
    resp = client.post("/lti/login", data=q, follow_redirects=False)
    if storage_target:
        assert resp.status_code == 200, resp.text
        import json
        import re

        cfg = json.loads(re.search(r'id="oc-cfg">(.*?)</script>', resp.text).group(1))  # type: ignore[union-attr]
        redirect = cfg["redirect"]
    else:
        assert resp.status_code == 302, resp.text
        redirect = resp.headers["location"]
    qs = parse_qs(urlsplit(redirect).query)
    cookie = next(iter(resp.cookies.keys()), None)
    return Login(
        state=qs["state"][0],
        nonce=qs["nonce"][0],
        cookie_name=cookie,
        browser_secret=resp.cookies.get(cookie) if cookie else None,
        response=resp,
    )


def new_id() -> str:
    return uuid.uuid4().hex
