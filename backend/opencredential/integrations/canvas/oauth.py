# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas REST OAuth2 (authorization code) for the API developer key (ADR-0009).

* An institution admin starts the flow from OpenCredential; the browser goes to Canvas, signs in
  as the designated integration account and approves the scopes.
* The callback exchanges the code server-side. Access and refresh tokens are sealed with
  :mod:`opencredential.secretbox` and stored in ``canvas_tokens``. They never reach a browser,
  a log line or an API response.
* Access tokens last one hour; :class:`IntegrationTokens` refreshes them shortly before expiry
  (or after a 401) in its own short transaction.
"""

from __future__ import annotations

import secrets
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from sqlalchemy import select

from opencredential import secretbox
from opencredential.db.models import CanvasIntegration, CanvasToken
from opencredential.db.session import tenant_session
from opencredential.integrations.base import LmsPermissionError, LmsTransientError
from opencredential.integrations.canvas.http import CanvasAuthError, host_header, rewrite_url
from opencredential.settings import Settings

#: GET-only scopes the adapter needs (ADR-0009, checked against the local Canvas scope list).
API_SCOPES = (
    "url:GET|/api/v1/courses/:id",
    "url:GET|/api/v1/courses/:course_id/modules",
    "url:GET|/api/v1/courses/:course_id/modules/:module_id/items",
    "url:GET|/api/v1/courses/:course_id/assignments",
    "url:GET|/api/v1/courses/:course_id/students/submissions",
    "url:GET|/api/v1/courses/:course_id/enrollments",
    "url:GET|/api/v1/users/:user_id/profile",
)
STATE_AUDIENCE = "opencredential-canvas-oauth"
REFRESH_MARGIN = timedelta(minutes=5)


class OAuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ctx(token_id: uuid.UUID | str, field: str) -> str:
    return f"canvas_token:{token_id}:{field}"


def secret_context(integration_id: uuid.UUID) -> str:
    return f"canvas_integration:{integration_id}:api_client_secret"


def client_secret(settings: Settings, integration: CanvasIntegration) -> str:
    if not integration.api_client_secret_enc or not integration.api_client_id:
        raise OAuthError("API_KEY_MISSING", "The Canvas API developer key is not configured.")
    return secretbox.open_(
        settings, integration.api_client_secret_enc, secret_context(integration.id)
    )


def redirect_uri(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/") + "/api/v1/canvas/oauth/callback"


# ---- state ------------------------------------------------------------------------------------


def make_state(
    settings: Settings, *, institution_id: uuid.UUID, integration_id: uuid.UUID, user_id: uuid.UUID
) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "aud": STATE_AUDIENCE,
        "inst": str(institution_id),
        "int": str(integration_id),
        "sub": str(user_id),
        "iat": now,
        "exp": now + 600,
        "jti": secrets.token_urlsafe(16),
    }
    key = OctKey.import_key(settings.secret_key.get_secret_value().encode())
    return jwt.encode({"alg": "HS256"}, claims, key)


def read_state(settings: Settings, state: str) -> dict[str, Any]:
    key = OctKey.import_key(settings.secret_key.get_secret_value().encode())
    try:
        token = jwt.decode(state, key, algorithms=["HS256"])
        jwt.JWTClaimsRegistry(
            aud={"essential": True, "value": STATE_AUDIENCE},
            exp={"essential": True},
            jti={"essential": True},
        ).validate(token.claims)
    except (JoseError, ValueError) as exc:
        raise OAuthError("OAUTH_STATE_INVALID", "The Canvas authorisation link expired.") from exc
    return dict(token.claims)


def authorize_url(settings: Settings, integration: CanvasIntegration, state: str) -> str:
    if not integration.api_client_id:
        raise OAuthError("API_KEY_MISSING", "The Canvas API developer key is not configured.")
    params = {
        "client_id": integration.api_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(settings),
        "state": state,
        "scope": " ".join(API_SCOPES),
    }
    return integration.base_url.rstrip("/") + "/login/oauth2/auth?" + urlencode(params)


# ---- token endpoint ---------------------------------------------------------------------------


def _token_request(
    settings: Settings,
    integration: CanvasIntegration,
    form: dict[str, str],
    transport: httpx.BaseTransport | None,
) -> dict[str, Any]:
    public_url = integration.base_url.rstrip("/") + "/login/oauth2/token"
    url = rewrite_url(settings, public_url)
    form = {
        **form,
        "client_id": integration.api_client_id or "",
        "client_secret": client_secret(settings, integration),
    }
    try:
        with httpx.Client(timeout=settings.canvas_timeout_seconds, transport=transport) as client:
            resp = client.post(
                url,
                data=form,
                headers={"accept": "application/json", **host_header(settings, public_url)},
            )
    except httpx.HTTPError as exc:
        raise LmsTransientError(f"Canvas token endpoint unreachable: {exc}") from exc
    if resp.status_code >= 500:
        raise LmsTransientError(f"Canvas token endpoint error {resp.status_code}")
    if resp.status_code != 200:
        raise CanvasAuthError(f"Canvas refused the token request ({resp.status_code})")
    return dict(resp.json())


def exchange_code(
    settings: Settings,
    integration: CanvasIntegration,
    code: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    return _token_request(
        settings,
        integration,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(settings)},
        transport,
    )


def store_integration_token(
    settings: Settings, db: Any, integration: CanvasIntegration, body: dict[str, Any]
) -> CanvasToken:
    """Replace the integration-account token with ``body`` (a Canvas token response)."""
    for old in db.scalars(
        select(CanvasToken).where(
            CanvasToken.canvas_integration_id == integration.id,
            CanvasToken.purpose == "integration_account",
        )
    ):
        db.delete(old)
    db.flush()
    row = CanvasToken(
        id=uuid.uuid4(),
        institution_id=integration.institution_id,
        canvas_integration_id=integration.id,
        purpose="integration_account",
        canvas_user_id=str((body.get("user") or {}).get("id") or "") or None,
        access_token_enc=b"",
        scopes=list(API_SCOPES),
    )
    _apply(settings, row, body)
    db.add(row)
    return row


def _apply(settings: Settings, row: CanvasToken, body: dict[str, Any]) -> None:
    row.access_token_enc = secretbox.seal(settings, str(body["access_token"]), _ctx(row.id, "a"))
    if body.get("refresh_token"):
        row.refresh_token_enc = secretbox.seal(
            settings, str(body["refresh_token"]), _ctx(row.id, "r")
        )
    expires_in = body.get("expires_in")
    row.expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None


class IntegrationTokens:
    """Token provider for the adapter: reads, refreshes and re-seals the integration token."""

    def __init__(
        self,
        settings: Settings,
        institution_id: uuid.UUID,
        integration_id: uuid.UUID,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.institution_id = institution_id
        self.integration_id = integration_id
        self._transport = transport
        self._token: str | None = None
        self._expires: datetime | None = None
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._token and (
                self._expires is None or self._expires - REFRESH_MARGIN > datetime.now(UTC)
            ):
                return self._token
            self._load(force_refresh=False)
            assert self._token is not None
            return self._token

    def refresh(self) -> str:
        with self._lock:
            self._load(force_refresh=True)
            assert self._token is not None
            return self._token

    def _load(self, *, force_refresh: bool) -> None:
        with tenant_session(self.institution_id) as db:
            integration = db.get(CanvasIntegration, self.integration_id)
            row = db.scalar(
                select(CanvasToken)
                .where(
                    CanvasToken.canvas_integration_id == self.integration_id,
                    CanvasToken.purpose == "integration_account",
                )
                .with_for_update()
            )
            if integration is None or row is None:
                raise LmsPermissionError(
                    "No Canvas API authorisation yet. An administrator must connect the "
                    "integration account."
                )
            near_expiry = row.expires_at is not None and (
                row.expires_at - REFRESH_MARGIN <= datetime.now(UTC)
            )
            if force_refresh or near_expiry:
                if not row.refresh_token_enc:
                    raise CanvasAuthError("Canvas token expired and cannot be refreshed")
                refresh_token = secretbox.open_(
                    self.settings, row.refresh_token_enc, _ctx(row.id, "r")
                )
                body = _token_request(
                    self.settings,
                    integration,
                    {"grant_type": "refresh_token", "refresh_token": refresh_token},
                    self._transport,
                )
                _apply(self.settings, row, body)
            self._token = secretbox.open_(self.settings, row.access_token_enc, _ctx(row.id, "a"))
            self._expires = row.expires_at
