# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public, unauthenticated endpoints that make credentials independently verifiable.

* ``GET /issuers/{slug}/did.json`` — did:web DID document (key discovery, spec §7.3).
* ``GET /status/{slug}/{list_id}`` — signed BitstringStatusListCredential (spec §7.6).
* ``GET /achievements/{version_id}`` — the published achievement (``achievement.id`` target).
* ``GET /assets/default-badge.svg`` — fallback badge image.
* ``POST /api/v1/verify`` — machine-readable verification (spec §16.3).

None of these needs a session. Each maps its public identifier to an institution through a
narrow SECURITY DEFINER lookup and then reads with an ordinary tenant-scoped session.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from opencredential.api.deps import SettingsDep, SignerDep
from opencredential.api.errors import ApiError
from opencredential.db.models import AchievementVersion, Institution
from opencredential.db.session import tenant_session
from opencredential.institutions.identity import base_url, did_web_for
from opencredential.issuance import ob3
from opencredential.issuance.service import alignments as issuance_alignments
from opencredential.verification.service import Verifier
from opencredential.verification.sources import (
    DefaultSources,
    Unavailable,
    local_did_document,
    local_status_list,
    own_origins,
)

router = APIRouter(tags=["public verification"])

LD_JSON = "application/ld+json"
MAX_VERIFY_BYTES = 256 * 1024
NO_STORE = {"Cache-Control": "no-store"}

DEFAULT_BADGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img" \
aria-label="Digital badge">
<title>Digital badge</title>
<circle cx="100" cy="100" r="92" fill="#1f4e79"/>
<circle cx="100" cy="100" r="72" fill="none" stroke="#ffffff" stroke-width="6"/>
<path d="M70 102l20 20 42-46" fill="none" stroke="#ffffff" stroke-width="12" \
stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


@router.get("/issuers/{slug}/did.json", summary="did:web DID document for an issuer")
def did_json(slug: str, request: Request) -> JSONResponse:
    host = request.headers.get("host", "")
    doc = local_did_document(did_web_for(host, slug))
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "No issuer with that identifier on this host")
    return JSONResponse(
        doc, media_type="application/did+ld+json", headers={"Cache-Control": "max-age=300"}
    )


@router.get(
    "/status/{slug}/{list_id}",
    summary="Signed BitstringStatusListCredential",
    responses={503: {"description": "No valid list is published right now"}},
)
def status_list(slug: str, list_id: uuid.UUID, request: Request) -> Response:
    try:
        doc = local_status_list(list_id, slug)
    except Unavailable as exc:
        # Verifiers must report "unable to verify", never "revoked" (ADR-0006).
        raise ApiError(
            503, "STATUS_UNAVAILABLE", "Status list temporarily unavailable", str(exc)
        ) from exc
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "No such status list")
    # Plain JSON: every verifier we test with parses it, while some (the 1EdTech inspector)
    # refuse a status list credential served as application/ld+json.
    return Response(
        json.dumps(doc), media_type="application/json", headers={"Cache-Control": "max-age=300"}
    )


@router.get("/achievements/{version_id}", summary="Published achievement definition")
def achievement(version_id: uuid.UUID, settings: SettingsDep) -> Response:
    with tenant_session(None) as db:
        iid = db.execute(
            text("select app.institution_for_version(:v)"), {"v": str(version_id)}
        ).scalar()
    if iid is None:
        raise ApiError(404, "NOT_FOUND", "No published achievement with that id")
    with tenant_session(uuid.UUID(str(iid))) as db:
        version = db.get(AchievementVersion, version_id)
        institution = db.get(Institution, iid)
        assert version is not None and institution is not None
        base = base_url(institution, settings)
        url = f"{base}/achievements/{version.id}"
        body = ob3.build_achievement(
            ob3.AchievementInfo(
                id=url,
                name=version.title,
                description=version.description,
                criteria_narrative=version.criteria_narrative,
                criteria_id=f"{url}#criteria",
                achievement_type=version.achievement_type,
                tags=(version.category,) if version.category else (),
                # The same skills as every credential of this version carries; credentials
                # point here for a skill the author gave no link of its own.
                alignments=issuance_alignments(version, url),
            )
        )
    body = {"@context": [ob3.VC_V2_CONTEXT, ob3.OB_CONTEXT], **body}
    return Response(json.dumps(body), media_type=LD_JSON, headers={"Cache-Control": "max-age=3600"})


@router.get("/assets/default-badge.svg", summary="Default badge image", include_in_schema=False)
def default_badge() -> Response:
    return Response(
        DEFAULT_BADGE_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "max-age=86400", "Content-Security-Policy": "default-src 'none'"},
    )


class CheckOut(BaseModel):
    name: str
    status: str
    ok: bool
    detail: str


class VerifyOut(BaseModel):
    result: str
    label: str
    checks: list[CheckOut]
    issuer: dict[str, Any] | None
    achievement: dict[str, Any] | None
    credential_id: str | None
    valid_from: str | None
    valid_until: str | None
    issuer_trust: dict[str, Any]
    explanation: str
    checked_at: str


@router.post(
    "/api/v1/verify",
    response_model=VerifyOut,
    summary="Verify an Open Badges 3.0 credential",
    description=(
        "Body: the credential JSON (at most 256 KB). Result is one of verified, revoked, "
        "expired, invalid, unable_to_verify, with the individual checks."
    ),
)
async def verify(request: Request, settings: SettingsDep, signer: SignerDep) -> JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_VERIFY_BYTES:
        raise ApiError(413, "TOO_LARGE", "Credential is larger than 256 KB")
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise ApiError(422, "NOT_JSON", "The request body must be the credential JSON") from exc

    def run() -> dict[str, Any]:
        verifier = Verifier(signer, DefaultSources(own_origins(settings.public_base_url)))
        return verifier.verify(doc, now=datetime.now(UTC)).to_dict()

    result = await run_in_threadpool(run)
    return JSONResponse(result, headers=NO_STORE)
