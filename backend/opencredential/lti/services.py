# SPDX-License-Identifier: AGPL-3.0-or-later
"""LTI Advantage service access: client-credentials tokens and Names and Roles (NRPS).

The access token comes from the platform token endpoint using a JWT client assertion signed
with the tool key (1EdTech Security Framework §4.1). Tokens are cached in memory until shortly
before expiry; they are never stored or sent to a browser.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from joserfc import jwt

from opencredential.db.models import CanvasIntegration
from opencredential.integrations.base import LmsPermissionError, LmsTransientError
from opencredential.integrations.canvas.http import host_header, next_link, rewrite_url
from opencredential.lti.keys import tool_key
from opencredential.settings import Settings

NRPS_SCOPE = "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
NRPS_MEDIA_TYPE = "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

_cache: dict[tuple[str, str], tuple[str, float]] = {}
_lock = threading.Lock()


def clear_token_cache() -> None:
    with _lock:
        _cache.clear()


def client_assertion(settings: Settings, client_id: str, token_url: str) -> str:
    key = tool_key(settings)
    now = int(time.time())
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "iat": now,
        "exp": now + 300,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode({"alg": "RS256", "kid": key.kid, "typ": "JWT"}, claims, key)


def service_token(
    settings: Settings,
    integration: CanvasIntegration,
    scopes: list[str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    if not integration.lti_token_url:
        raise LmsPermissionError("the Canvas connection has no LTI token URL")
    scope = " ".join(sorted(scopes))
    cache_key = (str(integration.id), scope)
    with _lock:
        hit = _cache.get(cache_key)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    form = {
        "grant_type": "client_credentials",
        "client_assertion_type": ASSERTION_TYPE,
        "client_assertion": client_assertion(
            settings, integration.lti_client_id, integration.lti_token_url
        ),
        "scope": scope,
    }
    try:
        with httpx.Client(timeout=settings.canvas_timeout_seconds, transport=transport) as client:
            resp = client.post(
                rewrite_url(settings, integration.lti_token_url),
                data=form,
                headers=host_header(settings, integration.lti_token_url),
            )
    except httpx.HTTPError as exc:
        raise LmsTransientError(f"LTI token endpoint unreachable: {exc}") from exc
    if resp.status_code >= 500:
        raise LmsTransientError(f"LTI token endpoint error {resp.status_code}")
    if resp.status_code != 200:
        raise LmsPermissionError(
            f"Canvas refused the LTI service token ({resp.status_code}): {resp.text[:200]}"
        )
    body = resp.json()
    token = str(body["access_token"])
    with _lock:
        _cache[cache_key] = (token, time.time() + float(body.get("expires_in", 3600)))
    return token


@dataclass(frozen=True)
class NrpsMember:
    sub: str
    roles: tuple[str, ...]
    status: str
    name: str | None
    given_name: str | None
    family_name: str | None
    email: str | None
    canvas_user_id: str | None
    lti11_user_id: str | None


def _member(raw: dict[str, Any]) -> NrpsMember:
    custom: dict[str, Any] = {}
    for message in raw.get("message") or []:
        custom.update(message.get("https://purl.imsglobal.org/spec/lti/claim/custom") or {})
    cid = custom.get("canvas_user_id")
    cid = None if cid is None or str(cid).startswith("$") else str(cid)
    return NrpsMember(
        sub=str(raw["user_id"]),
        roles=tuple(str(r) for r in raw.get("roles") or []),
        status=str(raw.get("status") or "Active"),
        name=raw.get("name"),
        given_name=raw.get("given_name"),
        family_name=raw.get("family_name"),
        email=raw.get("email"),
        canvas_user_id=cid,
        lti11_user_id=raw.get("lti11_legacy_user_id"),
    )


def nrps_members(
    settings: Settings,
    integration: CanvasIntegration,
    memberships_url: str,
    *,
    resource_link_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[NrpsMember]:
    """All members of a context. Raises on any failed page (no partial rosters)."""
    token = service_token(settings, integration, [NRPS_SCOPE], transport=transport)
    params: dict[str, Any] = {"limit": 100}
    if resource_link_id:
        params["rlid"] = resource_link_id
    url: str | None = memberships_url
    pages = 0
    with httpx.Client(timeout=settings.canvas_timeout_seconds, transport=transport) as client:
        while url:
            pages += 1
            if pages > 500:
                raise LmsTransientError("NRPS pagination did not terminate")
            try:
                resp = client.get(
                    rewrite_url(settings, url),
                    params=params if pages == 1 else None,
                    headers={
                        "authorization": f"Bearer {token}",
                        "accept": NRPS_MEDIA_TYPE,
                        **host_header(settings, url),
                    },
                )
            except httpx.HTTPError as exc:
                raise LmsTransientError(f"NRPS unreachable: {exc}") from exc
            if resp.status_code >= 500 or resp.status_code == 429:
                raise LmsTransientError(f"NRPS error {resp.status_code}")
            if resp.status_code != 200:
                raise LmsPermissionError(f"NRPS refused ({resp.status_code})")
            for raw in resp.json().get("members") or []:
                yield _member(raw)
            url = next_link(resp.headers.get("link"))
