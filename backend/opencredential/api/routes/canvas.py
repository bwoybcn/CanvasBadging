# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas connection administration: REST OAuth for the integration account (ADR-0009).

Tokens are exchanged and stored server-side only. Responses describe the connection (who
authorised it, when it expires, which scopes) and never contain a token or client secret.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from starlette.responses import HTMLResponse

from opencredential import audit
from opencredential.api.deps import ActorDep, ClaimsDep, SettingsDep, TenantDb
from opencredential.api.errors import ApiError
from opencredential.db.models import CanvasIntegration, CanvasToken, LtiNonceUsed
from opencredential.db.session import tenant_session
from opencredential.integrations.base import LmsError
from opencredential.integrations.canvas import oauth
from opencredential.lti import pages

router = APIRouter(prefix="/api/v1/canvas", tags=["canvas"])


class IntegrationOut(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str
    lti_issuer: str
    lti_client_id: str
    api_client_id: str | None
    status: str
    api_connected: bool
    api_token_expires_at: datetime | None
    api_authorised_canvas_user_id: str | None
    api_scopes: list[str]


class OAuthStartOut(BaseModel):
    authorize_url: str


def _require_admin(actor: ActorDep) -> None:
    if not actor.is_inst_admin:
        raise ApiError(403, "FORBIDDEN", "Only institution administrators manage Canvas")


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(actor: ActorDep, db: TenantDb) -> list[IntegrationOut]:
    _require_admin(actor)
    out = []
    for i in db.scalars(select(CanvasIntegration).order_by(CanvasIntegration.name)):
        tok = db.scalar(
            select(CanvasToken).where(
                CanvasToken.canvas_integration_id == i.id,
                CanvasToken.purpose == "integration_account",
            )
        )
        out.append(
            IntegrationOut(
                id=i.id,
                name=i.name,
                base_url=i.base_url,
                lti_issuer=i.lti_issuer,
                lti_client_id=i.lti_client_id,
                api_client_id=i.api_client_id,
                status=i.status,
                api_connected=tok is not None,
                api_token_expires_at=tok.expires_at if tok else None,
                api_authorised_canvas_user_id=tok.canvas_user_id if tok else None,
                api_scopes=list(tok.scopes) if tok else [],
            )
        )
    return out


@router.post("/integrations/{integration_id}/oauth/start", response_model=OAuthStartOut)
def start_oauth(
    integration_id: uuid.UUID,
    claims: ClaimsDep,
    actor: ActorDep,
    db: TenantDb,
    settings: SettingsDep,
) -> OAuthStartOut:
    """Begin authorising the integration account. Open the URL in a new top-level window."""
    _require_admin(actor)
    integration = db.get(CanvasIntegration, integration_id)
    if integration is None:
        raise ApiError(404, "NOT_FOUND", "No such Canvas integration")
    state = oauth.make_state(
        settings,
        institution_id=claims.institution_id,
        integration_id=integration.id,
        user_id=claims.user_id,
    )
    try:
        return OAuthStartOut(authorize_url=oauth.authorize_url(settings, integration, state))
    except oauth.OAuthError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc


@router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(request: Request, settings: SettingsDep) -> HTMLResponse:
    params = request.query_params
    rid = getattr(request.state, "request_id", None)
    if params.get("error"):
        return pages.error(
            "CANVAS_AUTH_DENIED", "Canvas authorisation was cancelled or refused.", 400, rid
        )
    try:
        st = oauth.read_state(settings, params.get("state", ""))
        _use_once(st["jti"], int(st["exp"]))
        iid, int_id, user_id = uuid.UUID(st["inst"]), uuid.UUID(st["int"]), uuid.UUID(st["sub"])
        with tenant_session(iid) as db:
            integration = db.get(CanvasIntegration, int_id)
            if integration is None:
                raise oauth.OAuthError("NOT_FOUND", "The Canvas integration no longer exists.")
            body = oauth.exchange_code(settings, integration, params.get("code", ""))
            row = oauth.store_integration_token(settings, db, integration, body)
            if integration.status == "pending":
                integration.status = "active"
            audit.record(
                db,
                action="canvas.api_authorised",
                resource_type="canvas_integration",
                resource_id=integration.id,
                institution_id=iid,
                actor_user_id=user_id,
                request_id=rid,
                data={"canvas_user_id": row.canvas_user_id, "scopes": len(row.scopes)},
            )
    except oauth.OAuthError as exc:
        return pages.error(exc.code, str(exc), 400, rid)
    except LmsError as exc:
        return pages.error(exc.code, "Canvas did not accept the authorisation.", 502, rid)
    return HTMLResponse(
        "<!doctype html><html lang='en-GB'><meta charset='utf-8'><title>Canvas connected</title>"
        "<body><main><h1>Canvas is connected</h1><p>OpenCredential can now read course "
        "progress. You can close this window.</p></main></body></html>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _use_once(jti: str, exp: int) -> None:
    """Each authorisation link works once (reuses the pre-tenant nonce table)."""
    try:
        with tenant_session(None) as db:
            db.execute(
                insert(LtiNonceUsed).values(
                    id=uuid.uuid4(),
                    nonce=jti,
                    iss="opencredential:canvas-oauth",
                    expires_at=datetime.fromtimestamp(exp, UTC) + timedelta(minutes=1),
                )
            )
    except IntegrityError as exc:
        raise oauth.OAuthError("OAUTH_STATE_REUSED", "This authorisation link was used.") from exc
