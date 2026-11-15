# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tiny server-rendered pages for the LTI handshake (no framework, no external assets).

Each page carries its configuration as JSON in a ``<script type="application/json">`` block and
one inline script allowed by a per-response CSP nonce. All interpolated text is HTML-escaped.
"""

from __future__ import annotations

import html
import json
import secrets
from typing import Any

from starlette.responses import HTMLResponse

_STYLE = (
    "body{font-family:Lato,'Helvetica Neue',Arial,sans-serif;color:#273540;margin:2rem;"
    "line-height:1.5}main{max-width:40rem}h1{font-size:1.4rem}"
    ".code{color:#576773;font-size:.9rem}a,button{color:#0770a3}"
)

# lti.put_data / lti.get_data (1EdTech "LTI Client Side postMessages" + platform storage).
_STORAGE_JS = """
(function () {
  var cfg = JSON.parse(document.getElementById('oc-cfg').textContent);
  var done = false;
  function finish(value) {
    if (done) return; done = true;
    if (cfg.mode === 'put') { window.location.replace(cfg.redirect); return; }
    if (!value) {
      document.getElementById('oc-status').textContent =
        'Your browser blocked the sign-in check. Choose Badges in your Canvas course menu again, ' +
        'or allow cookies for this site.';
      return;
    }
    var form = document.getElementById('oc-form');
    form.elements.browser_secret.value = value;
    form.submit();
  }
  var target = null;
  try {
    if (window.parent !== window) {
      target = cfg.target === '_parent' ? window.parent : window.parent.frames[cfg.target];
    }
  } catch (e) { target = null; }
  if (!target) { finish(null); return; }
  var id = 'oc-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  window.addEventListener('message', function (ev) {
    if (ev.origin !== cfg.origin) return;
    var d = ev.data || {};
    if (d.message_id !== id) return;
    if (d.subject === 'lti.put_data.response') finish(true);
    if (d.subject === 'lti.get_data.response') finish(d.error ? null : d.value);
  });
  setTimeout(function () { finish(null); }, 3000);
  var msg = cfg.mode === 'put'
    ? { subject: 'lti.put_data', message_id: id, key: cfg.key, value: cfg.secret }
    : { subject: 'lti.get_data', message_id: id, key: cfg.key };
  target.postMessage(msg, cfg.origin);
})();
"""

_REDIRECT_JS = """
(function () {
  var cfg = JSON.parse(document.getElementById('oc-cfg').textContent);
  window.location.replace(cfg.url);
})();
"""


def _page(
    title: str,
    body: str,
    *,
    script: str | None = None,
    config: dict[str, Any] | None = None,
    frame_ancestors: str = "*",
    form_action: str = "'self'",
    status: int = 200,
) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    cfg = ""
    if config is not None:
        payload = json.dumps(config).replace("<", "\\u003c")
        cfg = f'<script type="application/json" id="oc-cfg">{payload}</script>'
    js = f'<script nonce="{nonce}">{script}</script>' if script else ""
    doc = (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{html.escape(title)}</title>'
        f'<style nonce="{nonce}">{_STYLE}</style></head>'
        f"<body><main>{body}</main>{cfg}{js}</body></html>"
    )
    csp = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        f"form-action {form_action}; frame-ancestors {frame_ancestors}; base-uri 'none'"
    )
    return HTMLResponse(
        doc,
        status_code=status,
        headers={
            "Content-Security-Policy": csp,
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def put_storage_then_redirect(
    *, redirect: str, target: str, origin: str, key: str, secret: str
) -> HTMLResponse:
    return _page(
        "Signing in to Badges",
        '<h1>Signing you in…</h1><p id="oc-status" role="status">Connecting to Canvas.</p>',
        script=_STORAGE_JS,
        config={
            "mode": "put",
            "redirect": redirect,
            "target": target,
            "origin": origin,
            "key": key,
            "secret": secret,
        },
        frame_ancestors=origin,
    )


def get_storage_and_verify(
    *, verify_url: str, ticket: str, target: str, origin: str, key: str
) -> HTMLResponse:
    body = (
        '<h1>Signing you in…</h1><p id="oc-status" role="status">Checking this browser.</p>'
        f'<form id="oc-form" method="post" action="{html.escape(verify_url)}">'
        f'<input type="hidden" name="ticket" value="{html.escape(ticket)}">'
        '<input type="hidden" name="browser_secret" value=""></form>'
    )
    return _page(
        "Signing in to Badges",
        body,
        script=_STORAGE_JS,
        config={"mode": "get", "target": target, "origin": origin, "key": key},
        frame_ancestors=origin,
    )


def redirect_to_app(url: str, frame_ancestors: str) -> HTMLResponse:
    return _page(
        "Opening Badges",
        f'<p role="status">Opening Badges… <a href="{html.escape(url)}">Continue</a></p>',
        script=_REDIRECT_JS,
        config={"url": url},
        frame_ancestors=frame_ancestors,
    )


def error(code: str, message: str, status: int, request_id: str | None) -> HTMLResponse:
    ref = f" Reference: {html.escape(request_id)}." if request_id else ""
    body = (
        "<h1>Badges could not open</h1>"
        f"<p>{html.escape(message)}</p>"
        "<p>Close this and choose <strong>Badges</strong> in the course menu again. "
        "If it keeps happening, contact your Canvas administrator.</p>"
        f'<p class="code">Error code: {html.escape(code)}.{ref}</p>'
    )
    return _page("Badges could not open", body, status=status)
