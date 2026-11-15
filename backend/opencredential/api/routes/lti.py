# SPDX-License-Identifier: AGPL-3.0-or-later
"""LTI 1.3 endpoints: OIDC login initiation, launch, browser verification and JWKS (spec §4)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from opencredential.api.deps import SettingsDep
from opencredential.authz import sessions
from opencredential.db.session import tenant_session
from opencredential.logging import get_logger
from opencredential.lti import pages
from opencredential.lti.config import canvas_tool_config, endpoints
from opencredential.lti.keys import jwks
from opencredential.lti.launch import (
    LaunchRejected,
    Registration,
    begin_login,
    cookie_matches,
    cookie_name,
    load_integration,
    mark_completed,
    origin_of,
    park_launch,
    redeem_ticket,
    storage_key,
    validate_launch,
)
from opencredential.lti.provision import provision_launch
from opencredential.settings import Settings

router = APIRouter(prefix="/lti", tags=["lti"])
log = get_logger("lti")
#: An id_token with a large roster of custom fields is still well under this.
MAX_FORM_BYTES = 256 * 1024


async def _params(request: Request) -> dict[str, str]:
    """Query and ``application/x-www-form-urlencoded`` body parameters (LTI uses only these;
    parsed here so no multipart dependency is needed). Body values win."""
    data: dict[str, Any] = dict(request.query_params)
    if request.method == "POST":
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            return {k: str(v) for k, v in data.items()}
        body = await request.body()
        if len(body) > MAX_FORM_BYTES:
            return {}
        data.update(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
    return {k: str(v) for k, v in data.items()}


def _rejected(request: Request, exc: LaunchRejected) -> Response:
    request_id = getattr(request.state, "request_id", None)
    log.warning("lti.rejected", code=exc.code, status=exc.status)
    return pages.error(exc.code, exc.message, exc.status, request_id)


@router.api_route("/login", methods=["GET", "POST"], include_in_schema=False)
async def login(request: Request, settings: SettingsDep) -> Response:
    """Third-party initiated login (OIDC step 1)."""
    params = await _params(request)
    ep = endpoints(settings)
    try:
        with tenant_session(None) as db:
            start = begin_login(db, settings, params, ep["launch"])
    except LaunchRejected as exc:
        return _rejected(request, exc)

    if start.storage_target:
        response: Response = pages.put_storage_then_redirect(
            redirect=start.redirect_url,
            target=start.storage_target,
            origin=start.platform_origin,
            key=storage_key(start.state),
            secret=start.browser_secret,
        )
    else:
        response = RedirectResponse(start.redirect_url, status_code=302)
    _set_binding_cookie(response, settings, start.state, start.browser_secret)
    return response


@router.post("/launch", include_in_schema=False)
async def launch(request: Request, settings: SettingsDep) -> Response:
    """Authentication response (OIDC step 3): validate, bind to the browser, sign in."""
    params = await _params(request)
    if params.get("error"):
        exc = LaunchRejected(
            "PLATFORM_ERROR", f"Canvas refused the sign-in ({params['error'][:80]}).", 400
        )
        return _rejected(request, exc)
    state = params.get("state", "")
    rejected: LaunchRejected | None = None
    with tenant_session(None) as db:
        # Rejections are captured, not raised, so consuming the state and nonce still commits.
        try:
            validated = validate_launch(
                db,
                settings,
                state=state,
                id_token=params.get("id_token", ""),
                launch_url=endpoints(settings)["launch"],
            )
            if cookie_matches(validated, request.cookies.get(cookie_name(state))):
                mark_completed(db, validated.state_row_id)
                bound = True
            elif validated.storage_target:
                ticket = park_launch(db, validated)
                bound = False
            else:
                raise LaunchRejected(
                    "BROWSER_BINDING_FAILED",
                    "Your browser blocked the cookie this sign-in needs and Canvas did not offer "
                    "another way to confirm it. Allow cookies for this site, or open the tool in "
                    "a new tab.",
                    401,
                )
        except LaunchRejected as exc:
            rejected = exc
    if rejected is not None:
        return _rejected(request, rejected)

    if not bound:
        return pages.get_storage_and_verify(
            verify_url=endpoints(settings)["verify"],
            ticket=ticket,
            target=validated.storage_target or "_parent",
            origin=validated.platform_origin,
            key=storage_key(state),
        )
    response = _complete(
        request, settings, validated.launch, validated.registration, validated.platform_origin
    )
    response.delete_cookie(cookie_name(state), path="/lti/")
    return response


@router.post("/verify", include_in_schema=False)
async def verify(request: Request, settings: SettingsDep) -> Response:
    """Finish a launch whose browser was confirmed through Canvas platform storage."""
    params = await _params(request)
    rejected: LaunchRejected | None = None
    with tenant_session(None) as db:
        try:
            launch_data, registration = redeem_ticket(
                db, settings, params.get("ticket", ""), params.get("browser_secret", "")
            )
        except LaunchRejected as exc:
            rejected = exc
    if rejected is not None:
        return _rejected(request, rejected)
    integration = load_integration(registration)
    return _complete(request, settings, launch_data, registration, origin_of(integration.base_url))


def _complete(
    request: Request,
    settings: Settings,
    launch_data: Any,
    registration: Registration,
    frame_origin: str,
) -> Response:
    try:
        with tenant_session(registration.institution_id) as db:
            result = provision_launch(
                db,
                registration.institution_id,
                registration.integration_id,
                launch_data,
                request_id=getattr(request.state, "request_id", None),
            )
    except PermissionError as exc:
        return _rejected(
            request,
            LaunchRejected(str(exc), "Your account cannot use Badges here.", 403),
        )
    token, _ = sessions.issue(
        settings,
        user_id=result.user_id,
        institution_id=registration.institution_id,
        course_id=result.course_id,
        method="lti",
    )
    log.info(
        "lti.launch_ok",
        course_id=str(result.course_id),
        roles=sorted(result.course_roles),
        new_user=result.created_user,
    )
    fragment = urlencode({"session": token, "course": str(result.course_id)})
    url = f"{settings.public_base_url.rstrip('/')}/app/launch#{fragment}"
    return pages.redirect_to_app(url, frame_origin if frame_origin else "*")


def _set_binding_cookie(response: Response, settings: Settings, state: str, secret: str) -> None:
    secure = settings.public_base_url.startswith("https://")
    response.set_cookie(
        cookie_name(state),
        secret,
        max_age=settings.lti_state_ttl_seconds,
        path="/lti/",
        httponly=True,
        secure=secure,
        # In an iframe on another site only SameSite=None cookies are sent; that needs HTTPS.
        samesite="none" if secure else "lax",
    )


@router.get("/jwks", include_in_schema=False)
def tool_jwks(settings: SettingsDep) -> JSONResponse:
    return JSONResponse(jwks(settings), headers={"Cache-Control": "public, max-age=300"})


@router.get("/config.json", include_in_schema=False)
def tool_config(settings: SettingsDep) -> JSONResponse:
    """Canvas developer key JSON for this deployment (no secrets: public key only)."""
    return JSONResponse(canvas_tool_config(settings))
