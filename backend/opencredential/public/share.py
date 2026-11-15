# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public share pages and the "check a credential file" page (spec §9.4, §16.3; W6).

* ``GET /verify`` — anyone can check a downloaded credential file, no account needed.
* ``GET /verify/{share_id}`` — the human-readable page a student shares. Server-rendered so
  link previews (Open Graph) work without JavaScript.
* ``GET /verify/{share_id}/credential.json`` — the exact signed credential, for wallets that
  can "add from URL" and for anyone who wants to verify it with another tool.
* ``GET /verify/{share_id}/verification.json`` — machine-readable verification result.
* ``GET /assets/public/{sha256}.{ext}`` — badge artwork referenced from issued credentials.
* ``GET /robots.txt`` — disallow everything (sharing is not discovery, open question Q17).

Unknown and withdrawn share ids get the same 404, so a withdrawn link reveals nothing.
Open Graph tags carry the badge and issuer only, never the learner's name, even when the
learner chose to show their name on the page itself.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from opencredential.api.deps import SettingsDep, SignerDep
from opencredential.credentials import sharing as svc
from opencredential.db.models import (
    BadgeAsset,
    Credential,
    CredentialStatus,
    Institution,
    ShareGrant,
)
from opencredential.db.session import tenant_session
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient
from opencredential.storage import get_store
from opencredential.verification.service import Verifier
from opencredential.verification.sources import DefaultSources, own_origins

router = APIRouter(tags=["public verification"])

SHARE_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
    "img-src 'self' https: data:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
PAGE_HEADERS = {
    "Content-Security-Policy": CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}

NO_STORE = {"Cache-Control": "no-store"}

RESULT_STYLE = {
    "verified": ("#0b6b2b", "✓"),
    "revoked": ("#a4161a", "✕"),
    "expired": ("#7a4b00", "!"),
    "invalid": ("#a4161a", "✕"),
    "unable_to_verify": ("#3d4a5c", "?"),
}

RESULT_TEXT = {
    "verified": "This badge is genuine. It was issued by the organisation named below, has not "
    "been changed since, and has not been withdrawn.",
    "revoked": "The issuer has withdrawn (revoked) this badge. It is no longer valid.",
    "expired": "This badge has passed its expiry date, so it is no longer current.",
    "invalid": "This badge failed its checks. It may have been changed since it was issued, or it "
    "may not be a genuine badge. Do not rely on it.",
    "unable_to_verify": "We could not complete the checks right now, for example because the "
    "issuer's status information was temporarily unreachable. This is not evidence that "
    "anything is wrong. Please try again later.",
}

WHAT_IT_MEANS = (
    "Verification confirms that this credential was digitally signed by the named issuer, has not "
    "been changed since, and has not been revoked or expired. It does not independently prove "
    "every claim behind the award, and whether you trust the issuing organisation is your "
    "decision."
)

STYLE = """
:root{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
line-height:1.5;color:#1b1f24;background:#f5f6f8}
body{margin:0}main{max-width:46rem;margin:0 auto;padding:1.5rem 1rem 3rem}
.card{background:#fff;border:1px solid #d6dae0;border-radius:.5rem;padding:1.25rem;margin:0 0 1rem}
.head{display:flex;gap:1.25rem;align-items:flex-start;flex-wrap:wrap}
.head img{width:7.5rem;height:7.5rem;object-fit:contain}
h1{font-size:1.6rem;margin:0 0 .25rem}h2{font-size:1.15rem;margin:0 0 .5rem}
.result{border-left:.4rem solid;padding:.75rem 1rem;margin:0 0 1rem;background:#fff;
border-radius:.25rem}.result strong{font-size:1.2rem}
dl{display:grid;grid-template-columns:minmax(8rem,max-content) 1fr;gap:.35rem 1rem;margin:0}
dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}li{overflow-wrap:anywhere}
.muted{color:#4a5563;font-size:.95rem}a{color:#0b4f8a}
details summary{cursor:pointer;font-weight:600}
code{font-size:.9em;overflow-wrap:anywhere}
button,input[type=file]{font:inherit}input[type=file]{max-width:100%}
button{background:#0b4f8a;color:#fff;border:0;border-radius:.3rem;padding:.5rem 1rem;cursor:pointer}
:focus-visible{outline:3px solid #f2a900;outline-offset:2px}
"""


def _page(
    title: str, body: str, *, head_extra: str = "", status: int = 200, script: str | None = None
) -> HTMLResponse:
    script_tag = f'<script src="{escape(script)}" defer></script>' if script else ""
    html = (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow, noarchive">'
        f"<title>{escape(title)}</title>{head_extra}<style>{STYLE}</style>{script_tag}</head>"
        f"<body><main>{body}</main></body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=PAGE_HEADERS)


def _not_shared() -> HTMLResponse:
    return _page(
        "Badge link not active",
        '<div class="card"><h1>This link is not active</h1>'
        "<p>The holder has not shared a badge at this address, or has stopped "
        "sharing it. Stopping sharing does not affect whether the badge itself is valid.</p>"
        '<p>If you have the credential file, you can <a href="/verify">check it here</a>.</p>'
        "</div>",
        status=404,
    )


def _load(share_id: str, settings: Settings) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """(public view, signed credential, share url) for an active share, else ``None``."""
    if not SHARE_ID.match(share_id):
        return None
    with tenant_session(None) as db:
        iid = db.execute(text("select app.institution_for_share(:s)"), {"s": share_id}).scalar()
    if iid is None:
        return None
    with tenant_session(uuid.UUID(str(iid))) as db:
        grant = db.scalar(
            select(ShareGrant).where(
                ShareGrant.share_id == share_id, ShareGrant.revoked_at.is_(None)
            )
        )
        if grant is None:
            return None
        cred = db.get(Credential, grant.credential_id)
        institution = db.get(Institution, grant.institution_id)
        if cred is None or cred.signed_json is None or institution is None:
            return None
        view = svc.public_view(
            db, cred, svc.ShareOptions(grant.show_name, grant.show_evidence), settings
        )
        status = db.scalar(
            select(CredentialStatus).where(CredentialStatus.credential_id == cred.id)
        )
        view["holder_state"] = svc.credential_state(cred, status)
        return view, dict(cred.signed_json), svc.share_url(institution, settings, share_id)


def _json_not_found() -> JSONResponse:
    return JSONResponse(
        {"title": "Not found"}, status_code=404, headers={"Cache-Control": "no-store"}
    )


def _verify(signer: SignerClient, settings: Settings, vc: dict[str, Any]) -> dict[str, Any]:
    verifier = Verifier(signer, DefaultSources(own_origins(settings.public_base_url)))
    return verifier.verify(vc, now=datetime.now(UTC)).to_dict()


def _date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%-d %B %Y")
    except ValueError:
        return value


def _og(view: dict[str, Any], url: str) -> str:
    """Link-preview tags: badge and issuer only. No learner information, ever."""
    title = f"{view['credential_name']} · {view['issuer']['institution']}"
    desc = (
        f"A digital badge issued by {view['issuer']['name']}. "
        "Open the link to check that it is genuine."
    )
    tags = {
        "og:type": "website",
        "og:site_name": "OpenCredential verification",
        "og:title": title,
        "og:description": desc,
        "og:url": url,
    }
    image = view["image"]["url"]
    # Most link-preview crawlers ignore SVG, and only an absolute https image is useful.
    if image and image.startswith("https://") and not image.endswith(".svg"):
        tags["og:image"] = image
        tags["og:image:alt"] = view["image"]["alt"]
    out = "".join(
        f'<meta property="{k}" content="{escape(v, quote=True)}">' for k, v in tags.items()
    )
    out += '<meta name="twitter:card" content="summary">'
    out += f'<meta name="description" content="{escape(desc, quote=True)}">'
    return out


def _result_block(result: dict[str, Any]) -> str:
    code = result["result"]
    colour, mark = RESULT_STYLE.get(code, ("#3d4a5c", "?"))
    checks = "".join(
        f"<li><strong>{escape(c['name'].replace('_', ' ').capitalize())}</strong>: "
        f"{escape(c['status'])}. {escape(c['detail'])}</li>"
        for c in result.get("checks", [])
    )
    trust = result.get("issuer_trust") or {}
    trust_note = ""
    if trust.get("detail"):
        trust_note = f'<p class="muted">{escape(str(trust["detail"]))}</p>'
    return (
        f'<section class="result" style="border-color:{colour}" aria-labelledby="result-h">'
        f'<h2 id="result-h"><span aria-hidden="true" style="color:{colour}">{mark}</span> '
        f"<strong>{escape(result['label'])}</strong></h2>"
        f"<p>{escape(RESULT_TEXT.get(code, ''))}</p>"
        f'<p class="muted">Checked {escape(_date(result.get("checked_at")))}.</p>{trust_note}'
        f"<details><summary>Show the individual checks</summary><ul>{checks}</ul></details>"
        "</section>"
    )


def render_share_page(view: dict[str, Any], result: dict[str, Any], url: str, share_id: str) -> str:
    rows = [
        ("Issued by", f"{view['issuer']['name']}, {view['issuer']['institution']}"),
        ("Issued on", _date(view["issued_on"])),
    ]
    if view["valid_until"]:
        rows.append(("Expires on", _date(view["valid_until"])))
    if view["recipient_name"]:
        rows.append(("Awarded to", view["recipient_name"]))
    if view["achievement_type"]:
        rows.append(("Type", view["achievement_type"]))
    rows.append(("Credential ID", view["credential_id"] or ""))
    dl = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows)
    skills = ""
    if view["skills"]:
        items = "".join(
            f'<li><a href="{escape(s["url"], quote=True)}" rel="nofollow noopener">'
            f"{escape(s['name'] or s['url'])}</a></li>"
            if s.get("url", "").startswith("https://")
            else f"<li>{escape(s['name'] or '')}</li>"
            for s in view["skills"]
        )
        skills = f'<section class="card"><h2>Skills</h2><ul>{items}</ul></section>'
    evidence = ""
    if view["evidence"]:
        items = "".join(
            "<li>"
            + escape(e["narrative"])
            + (
                f' (<a href="{escape(e["url"], quote=True)}" rel="nofollow noopener">link</a>)'
                if e.get("url")
                else ""
            )
            + "</li>"
            for e in view["evidence"]
        )
        evidence = f'<section class="card"><h2>Evidence</h2><ul>{items}</ul></section>'
    image = view["image"]
    img = (
        f'<img src="{escape(image["url"], quote=True)}" alt="{escape(image["alt"], quote=True)}">'
        if image["url"]
        else ""
    )
    who = (
        f"<p>Awarded to <strong>{escape(view['recipient_name'])}</strong>.</p>"
        if view["recipient_name"]
        else '<p class="muted">The holder chose not to show their name on this page.</p>'
    )
    return (
        _result_block(result) + f'<article class="card"><div class="head">{img}<div>'
        f"<h1>{escape(view['credential_name'])}</h1>{who}</div></div>"
        f"<p>{escape(view['description'])}</p><dl>{dl}</dl></article>"
        f'<section class="card"><h2>Criteria</h2><p>{escape(view["criteria"])}</p></section>'
        + skills
        + evidence
        + '<section class="card"><h2>What verification means</h2>'
        f"<p>{escape(WHAT_IT_MEANS)}</p>"
        "<p>You can check this badge with any Open Badges 3.0 verifier: download "
        f'<a href="/verify/{share_id}/credential.json">the signed credential file</a> or use '
        f'<a href="/verify/{share_id}/verification.json">the machine-readable result</a>.</p>'
        f'<p class="muted">Page address: <code>{escape(url)}</code></p></section>'
    )


@router.get(
    "/verify/{share_id}",
    response_class=HTMLResponse,
    summary="Public verification page for a credential the holder chose to share",
)
async def share_page(share_id: str, settings: SettingsDep, signer: SignerDep) -> HTMLResponse:
    loaded = await run_in_threadpool(_load, share_id, settings)
    if loaded is None:
        return _not_shared()
    view, vc, url = loaded
    result = await run_in_threadpool(_verify, signer, settings, vc)
    head = _og(view, url) + (
        f'<link rel="alternate" type="application/ld+json" '
        f'href="/verify/{share_id}/credential.json">'
    )
    return _page(
        f"{view['credential_name']} · verification",
        render_share_page(view, result, url, share_id),
        head_extra=head,
    )


@router.get(
    "/verify/{share_id}/credential.json",
    summary="The signed Open Badges 3.0 credential behind a share link",
    responses={200: {"content": {"application/ld+json": {}}}, 404: {}},
)
async def share_credential(share_id: str, settings: SettingsDep) -> Response:
    loaded = await run_in_threadpool(_load, share_id, settings)
    if loaded is None:
        return _json_not_found()
    return Response(
        json.dumps(loaded[1], indent=2, ensure_ascii=False),
        media_type="application/ld+json",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@router.get(
    "/verify/{share_id}/verification.json",
    summary="Machine-readable verification result for a share link",
)
async def share_verification(share_id: str, settings: SettingsDep, signer: SignerDep) -> Response:
    loaded = await run_in_threadpool(_load, share_id, settings)
    if loaded is None:
        return _json_not_found()
    result = await run_in_threadpool(_verify, signer, settings, loaded[1])
    return JSONResponse(
        result, headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}
    )


CHECK_PAGE = """
<div class="card"><h1>Check a credential file</h1>
<p>Choose an Open Badges 3.0 credential file (<code>.json</code>) to check its signature, issuer
and status. You do not need an account. The file is sent to this service only to run the checks
and is not stored.</p>
<form id="check-form" novalidate>
<p><label for="file">Credential file</label><br>
<input id="file" name="file" type="file" accept=".json,application/json,application/ld+json"></p>
<p><button type="submit">Check the file</button></p></form>
<div id="out" role="status" aria-live="polite"></div></div>
<section class="card"><h2>What verification means</h2><p>__MEANS__</p></section>
<script type="application/json" id="result-words">__WORDS__</script>
"""


def _result_words() -> str:
    """The verdict wording and colours, shared with check.js so both pages say the same."""
    words = {"text": RESULT_TEXT, "style": {k: list(v) for k, v in RESULT_STYLE.items()}}
    # Inside <script>, "</" could end the element early; JSON allows "<\/" for it.
    return json.dumps(words).replace("</", "<\\/")


CHECK_JS = (Path(__file__).parent / "static" / "check.js").read_text(encoding="utf-8")


@router.get("/verify", response_class=HTMLResponse, summary="Check a credential file")
def check_page() -> HTMLResponse:
    return _page(
        "Check a credential file",
        CHECK_PAGE.replace("__MEANS__", escape(WHAT_IT_MEANS)).replace(
            "__WORDS__", _result_words()
        ),
        script="/verify-assets/check.js",
    )


@router.get("/verify-assets/check.js", include_in_schema=False)
def check_js() -> Response:
    return Response(
        CHECK_JS,
        media_type="text/javascript",
        headers={"Cache-Control": "max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/assets/public/{name}", include_in_schema=False)
def public_asset(name: str) -> Response:
    """Artwork of published badges, content-addressed and immutable."""
    sha, _, ext = name.partition(".")
    if not SHA256.match(sha) or ext not in ("svg", "png"):
        return Response(status_code=404)
    with tenant_session(None) as db:
        iid = db.execute(text("select app.institution_for_public_asset(:s)"), {"s": sha}).scalar()
    if iid is None:
        return Response(status_code=404)
    with tenant_session(uuid.UUID(str(iid))) as db:
        asset = db.scalar(select(BadgeAsset).where(BadgeAsset.sha256 == sha).limit(1))
        if asset is None:
            return Response(status_code=404)
        media = asset.media_type
        key = asset.storage_key
        if ext == "png" and media == "image/svg+xml":
            if not asset.png_rendition_key:
                return Response(status_code=404)
            media, key = "image/png", asset.png_rendition_key
        elif ext == "svg" and media != "image/svg+xml":
            return Response(status_code=404)
    try:
        data = get_store().get(key)
    except (FileNotFoundError, KeyError):
        return Response(status_code=404)
    return Response(
        data,
        media_type=media,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/robots.txt", include_in_schema=False)
def robots() -> Response:
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")
