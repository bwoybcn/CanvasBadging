# SPDX-License-Identifier: AGPL-3.0-or-later
"""LTI 1.3 OIDC login initiation and resource-link launch validation (spec §4.2, ADR-0008).

Flow::

    Canvas ──(1) login initiation──▶ /lti/login        creates state, nonce, browser secret
    browser ◀─(2) redirect to Canvas authorize (and, if offered, lti.put_data to platform storage)
    Canvas ──(3) form_post id_token + state──▶ /lti/launch
           validate signature and claims, consume state and nonce exactly once
           bind to the browser: cookie, or lti.get_data from platform storage (/lti/verify)
    browser ◀─(4) app session (bearer token, never a cookie) + course context

Every check raises :class:`LaunchRejected` with a stable code; integration tests cover one
negative case per check.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from joserfc import jws, jwt
from joserfc.errors import JoseError
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opencredential.db.models import CanvasIntegration, LtiDeployment, LtiLaunchState, LtiNonceUsed
from opencredential.db.session import tenant_session
from opencredential.logging import get_logger
from opencredential.lti import claims as c
from opencredential.lti.platform_keys import JwksUnavailable, platform_jwks
from opencredential.settings import Settings

ALLOWED_ALGS = ["RS256", "RS384", "RS512"]
log = get_logger("lti.launch")


class LaunchRejected(Exception):
    """A login or launch that must not proceed. ``code`` is stable and safe to show."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Registration:
    institution_id: uuid.UUID
    integration_id: uuid.UUID
    status: str


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def storage_key(state: str) -> str:
    """Platform-storage key for one login (short, not the state itself)."""
    return "oc_bind_" + sha256(state)[:24]


def cookie_name(state: str) -> str:
    return "oc_lti_" + sha256(state)[:16]


def resolve_registration(db: Session, iss: str, client_id: str) -> Registration:
    row = db.execute(
        text("SELECT institution_id, integration_id, status FROM app.lti_registration(:i, :c)"),
        {"i": iss, "c": client_id},
    ).first()
    if row is None:
        raise LaunchRejected("UNKNOWN_REGISTRATION", "This tool is not registered for that LMS.")
    if row.status == "disabled":
        raise LaunchRejected("REGISTRATION_DISABLED", "This Canvas connection is disabled.", 403)
    return Registration(row.institution_id, row.integration_id, row.status)


def load_integration(registration: Registration) -> CanvasIntegration:
    with tenant_session(registration.institution_id) as db:
        integration = db.get(CanvasIntegration, registration.integration_id)
        if integration is None:  # pragma: no cover - the definer function just returned it
            raise LaunchRejected("UNKNOWN_REGISTRATION", "This tool is not registered.")
        db.expunge(integration)
        return integration


# ---- (1) login initiation -------------------------------------------------------------------


@dataclass(frozen=True)
class LoginStart:
    redirect_url: str
    state: str
    browser_secret: str
    storage_target: str | None
    platform_origin: str


def begin_login(
    db: Session, settings: Settings, params: dict[str, str], launch_url: str
) -> LoginStart:
    """Validate a third-party login initiation and prepare the authentication request.

    ``db`` is a pre-tenant session (``tenant_session(None)``).
    """
    iss = params.get("iss", "")
    login_hint = params.get("login_hint", "")
    target_link_uri = params.get("target_link_uri", "")
    client_id = params.get("client_id", "")
    if not iss or not login_hint or not target_link_uri:
        raise LaunchRejected("LOGIN_PARAMS_MISSING", "The LMS sent an incomplete login request.")
    if not client_id:
        raise LaunchRejected("CLIENT_ID_MISSING", "The LMS did not say which tool to launch.")
    if not _same_origin(target_link_uri, launch_url):
        raise LaunchRejected("TARGET_LINK_URI_MISMATCH", "The launch target is not this tool.")

    registration = resolve_registration(db, iss, client_id)
    integration = load_integration(registration)
    if not integration.lti_auth_url:
        raise LaunchRejected("REGISTRATION_INCOMPLETE", "The Canvas connection has no login URL.")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    browser_secret = secrets.token_urlsafe(32)
    storage_target = params.get("lti_storage_target") or None
    db.add(
        LtiLaunchState(
            state=state,
            nonce=nonce,
            canvas_integration_id=integration.id,
            client_id=client_id,
            browser_secret_hash=sha256(browser_secret),
            storage_target=storage_target,
        )
    )
    auth_params = {
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": client_id,
        "redirect_uri": launch_url,
        "login_hint": login_hint,
        "state": state,
        "nonce": nonce,
    }
    if params.get("lti_message_hint"):
        auth_params["lti_message_hint"] = params["lti_message_hint"]
    sep = "&" if "?" in integration.lti_auth_url else "?"
    return LoginStart(
        redirect_url=integration.lti_auth_url + sep + urlencode(auth_params),
        state=state,
        browser_secret=browser_secret,
        storage_target=storage_target,
        platform_origin=origin_of(integration.base_url),
    )


# ---- (3) launch validation --------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatedLaunch:
    launch: c.LaunchData
    registration: Registration
    state_row_id: uuid.UUID
    browser_secret_hash: str
    storage_target: str | None
    platform_origin: str


def validate_launch(
    db: Session,
    settings: Settings,
    *,
    state: str,
    id_token: str,
    launch_url: str,
    now: datetime | None = None,
) -> ValidatedLaunch:
    """Validate and *consume* a launch. ``db`` is a pre-tenant session whose transaction must be
    committed by the caller even when this raises after consuming (so a replay stays dead)."""
    now = now or datetime.now(UTC)
    if not state:
        raise LaunchRejected("STATE_MISSING", "The launch did not include a state value.")
    if not id_token:
        raise LaunchRejected("ID_TOKEN_MISSING", "The launch did not include an id_token.")

    # State: must be ours, fresh and unused. Consumed atomically so two racing POSTs of the same
    # launch cannot both succeed.
    ttl = timedelta(seconds=settings.lti_state_ttl_seconds)
    row = db.execute(
        update(LtiLaunchState)
        .where(
            LtiLaunchState.state == state,
            LtiLaunchState.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(
            LtiLaunchState.id,
            LtiLaunchState.nonce,
            LtiLaunchState.canvas_integration_id,
            LtiLaunchState.client_id,
            LtiLaunchState.browser_secret_hash,
            LtiLaunchState.storage_target,
            LtiLaunchState.created_at,
        )
    ).first()
    if row is None:
        exists = db.scalar(select(LtiLaunchState.id).where(LtiLaunchState.state == state))
        if exists:
            raise LaunchRejected("STATE_REPLAYED", "This launch has already been used.", 401)
        raise LaunchRejected("STATE_UNKNOWN", "This launch was not started by this tool.", 401)
    if row.created_at < now - ttl:
        raise LaunchRejected("STATE_EXPIRED", "The launch took too long. Try again.", 401)

    claims = _verify_token(db, settings, id_token, row.client_id, row.canvas_integration_id, now)
    integration, registration = claims.pop("__integration"), claims.pop("__registration")

    if claims.get("nonce") != row.nonce:
        raise LaunchRejected("NONCE_MISMATCH", "The launch does not match its login.", 401)
    _check_message(claims, launch_url)
    deployment_id = str(claims[c.CLAIM_DEPLOYMENT_ID])
    _check_deployment(registration, integration.id, deployment_id)

    # Nonce replay: a second use of the same signed token (even with a fresh state) fails.
    exp = datetime.fromtimestamp(int(claims["exp"]), UTC)
    try:
        with db.begin_nested():
            db.execute(
                insert(LtiNonceUsed).values(
                    id=uuid.uuid4(), nonce=str(claims["nonce"]), iss=claims["iss"], expires_at=exp
                )
            )
    except IntegrityError as exc:
        raise LaunchRejected("NONCE_REPLAYED", "This launch has already been used.", 401) from exc

    launch = c.launch_from_claims(claims, row.client_id)
    return ValidatedLaunch(
        launch=launch,
        registration=registration,
        state_row_id=row.id,
        browser_secret_hash=row.browser_secret_hash or "",
        storage_target=row.storage_target,
        platform_origin=origin_of(integration.base_url),
    )


def _verify_token(
    db: Session,
    settings: Settings,
    id_token: str,
    client_id: str | None,
    integration_id: uuid.UUID,
    now: datetime,
) -> dict[str, Any]:
    try:
        header = jws.extract_compact(id_token.encode()).headers()
    except (JoseError, ValueError) as exc:
        raise LaunchRejected("ID_TOKEN_MALFORMED", "The launch token is not a JWT.", 401) from exc
    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise LaunchRejected(
            "ALG_NOT_ALLOWED", f"Signature algorithm {alg!r} is not accepted.", 401
        )

    # The (unverified) issuer only selects the registration; it must be the very integration the
    # login was started for, and its keys then verify the signature and the issuer claim.
    unverified = _unverified_claims(id_token)
    iss = str(unverified.get("iss", ""))
    try:
        registration = resolve_registration(db, iss, client_id or "")
    except LaunchRejected as exc:
        if exc.code != "UNKNOWN_REGISTRATION":
            raise
        raise LaunchRejected(
            "ISSUER_MISMATCH", "The launch came from another platform.", 401
        ) from exc
    if registration.integration_id != integration_id:
        raise LaunchRejected("ISSUER_MISMATCH", "The launch came from a different platform.", 401)
    integration = load_integration(registration)
    if not integration.lti_jwks_url:
        raise LaunchRejected("REGISTRATION_INCOMPLETE", "The Canvas connection has no key URL.")

    try:
        keys = platform_jwks.get(settings, integration.lti_jwks_url, header.get("kid"))
    except JwksUnavailable as exc:
        log.warning("lti.jwks_unavailable", error=str(exc)[:300])
        raise LaunchRejected(
            "PLATFORM_KEYS_UNAVAILABLE",
            "Canvas's signing keys could not be fetched, so the launch cannot be checked.",
            503,
        ) from exc
    try:
        token = jwt.decode(id_token, keys, algorithms=ALLOWED_ALGS)
    except JoseError as exc:
        raise LaunchRejected(
            "SIGNATURE_INVALID", "The launch signature is not valid.", 401
        ) from exc
    claims = dict(token.claims)

    if claims.get("iss") != integration.lti_issuer:
        raise LaunchRejected("ISSUER_MISMATCH", "The launch came from a different platform.", 401)
    aud = claims.get("aud")
    auds = [aud] if isinstance(aud, str) else list(aud or [])
    if integration.lti_client_id not in auds:
        raise LaunchRejected("AUDIENCE_MISMATCH", "The launch was meant for another tool.", 401)
    if (len(auds) > 1 or "azp" in claims) and claims.get("azp") != integration.lti_client_id:
        raise LaunchRejected("AZP_MISMATCH", "The launch was authorised for another tool.", 401)
    skew = settings.lti_clock_skew_seconds
    ts = now.timestamp()
    try:
        exp, iat = int(claims["exp"]), int(claims["iat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LaunchRejected("TIMESTAMPS_MISSING", "The launch has no lifetime.", 401) from exc
    if exp + skew < ts:
        raise LaunchRejected("TOKEN_EXPIRED", "The launch has expired. Open it again.", 401)
    if iat - skew > ts:
        raise LaunchRejected("TOKEN_NOT_YET_VALID", "The launch is dated in the future.", 401)
    if iat + settings.lti_state_ttl_seconds + skew < ts:
        raise LaunchRejected("TOKEN_TOO_OLD", "The launch was issued too long ago.", 401)
    if not claims.get("sub"):
        raise LaunchRejected("SUBJECT_MISSING", "The launch did not identify the user.", 401)
    claims["__integration"], claims["__registration"] = integration, registration
    return claims


def _unverified_claims(id_token: str) -> dict[str, Any]:
    """Payload of a compact JWT *without* verification, used only to choose the key set."""
    try:
        payload = json.loads(jws.extract_compact(id_token.encode()).payload)
        return payload if isinstance(payload, dict) else {}
    except (JoseError, ValueError) as exc:
        raise LaunchRejected("ID_TOKEN_MALFORMED", "The launch token is not a JWT.", 401) from exc


def _check_message(claims: dict[str, Any], launch_url: str) -> None:
    if claims.get(c.CLAIM_MESSAGE_TYPE) != c.MESSAGE_TYPE:
        raise LaunchRejected(
            "MESSAGE_TYPE_UNSUPPORTED", "This kind of LTI message is not supported."
        )
    if claims.get(c.CLAIM_VERSION) != c.VERSION:
        raise LaunchRejected("LTI_VERSION_UNSUPPORTED", "Only LTI 1.3.0 launches are supported.")
    if not claims.get(c.CLAIM_DEPLOYMENT_ID):
        raise LaunchRejected("DEPLOYMENT_MISSING", "The launch has no deployment id.")
    target = claims.get(c.CLAIM_TARGET_LINK_URI)
    if not target or not _same_origin(str(target), launch_url):
        raise LaunchRejected("TARGET_LINK_URI_MISMATCH", "The launch target is not this tool.")
    link = claims.get(c.CLAIM_RESOURCE_LINK) or {}
    if not isinstance(link, dict) or not link.get("id"):
        raise LaunchRejected("RESOURCE_LINK_MISSING", "The launch has no resource link.")
    roles = claims.get(c.CLAIM_ROLES)
    if not isinstance(roles, list):
        raise LaunchRejected("ROLES_MISSING", "The launch has no roles claim.")
    context = claims.get(c.CLAIM_CONTEXT)
    if not isinstance(context, dict) or not context.get("id"):
        raise LaunchRejected(
            "COURSE_CONTEXT_MISSING", "Open Micro-Credentials from inside a Canvas course.", 403
        )
    types = context.get("type") or []
    if types and not (set(map(str, types)) & c.COURSE_CONTEXT_TYPES):
        raise LaunchRejected(
            "COURSE_CONTEXT_UNSUPPORTED", "Micro-Credentials only opens inside a course.", 403
        )


def _check_deployment(registration: Registration, integration_id: uuid.UUID, dep: str) -> None:
    with tenant_session(registration.institution_id) as tdb:
        known = tdb.scalar(
            select(LtiDeployment.id).where(
                LtiDeployment.canvas_integration_id == integration_id,
                LtiDeployment.deployment_id == dep,
            )
        )
    if known is None:
        raise LaunchRejected(
            "DEPLOYMENT_UNKNOWN",
            "This Canvas installation of the tool has not been approved by an administrator.",
            403,
        )


# ---- browser binding --------------------------------------------------------------------------


def park_launch(db: Session, validated: ValidatedLaunch) -> str:
    """Keep a validated launch for up to the state TTL until the browser proves it started the
    login (platform storage). Returns the one-time ticket."""
    ticket = secrets.token_urlsafe(32)
    db.execute(
        update(LtiLaunchState)
        .where(LtiLaunchState.id == validated.state_row_id)
        .values(launch_ticket_hash=sha256(ticket), launch_claims=validated.launch.to_json())
    )
    return ticket


def redeem_ticket(
    db: Session, settings: Settings, ticket: str, browser_secret: str, now: datetime | None = None
) -> tuple[c.LaunchData, Registration]:
    now = now or datetime.now(UTC)
    row = db.execute(
        update(LtiLaunchState)
        .where(
            LtiLaunchState.launch_ticket_hash == sha256(ticket),
            LtiLaunchState.completed_at.is_(None),
        )
        .values(completed_at=now)
        .returning(
            LtiLaunchState.browser_secret_hash,
            LtiLaunchState.launch_claims,
            LtiLaunchState.created_at,
        )
    ).first()
    if row is None or not row.launch_claims:
        raise LaunchRejected("TICKET_INVALID", "This sign-in link has already been used.", 401)
    if row.created_at < now - timedelta(seconds=settings.lti_state_ttl_seconds):
        raise LaunchRejected("STATE_EXPIRED", "The launch took too long. Try again.", 401)
    if not browser_secret or not secrets.compare_digest(
        sha256(browser_secret), row.browser_secret_hash or ""
    ):
        raise LaunchRejected(
            "BROWSER_BINDING_FAILED",
            "We could not confirm this browser started the launch. Open the tool again.",
            401,
        )
    data = row.launch_claims
    launch = c.launch_from_claims(data["raw"], data["client_id"])
    registration = resolve_registration(db, launch.issuer, launch.client_id)
    return launch, registration


def mark_completed(db: Session, state_row_id: uuid.UUID, now: datetime | None = None) -> None:
    db.execute(
        update(LtiLaunchState)
        .where(LtiLaunchState.id == state_row_id)
        .values(completed_at=now or datetime.now(UTC))
    )


def cookie_matches(validated: ValidatedLaunch, cookie_value: str | None) -> bool:
    return bool(cookie_value) and secrets.compare_digest(
        sha256(cookie_value or ""), validated.browser_secret_hash
    )


# ---- helpers ----------------------------------------------------------------------------------


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _same_origin(a: str, b: str) -> bool:
    try:
        return origin_of(a).lower() == origin_of(b).lower()
    except ValueError:
        return False
