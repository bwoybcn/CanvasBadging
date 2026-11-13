# Security guide

This guide is for people who run OpenCredential. It explains what the application protects on
its own, what the operator must set up, and the review to complete before going live. The
design reasoning is in the [threat model](threat-model.md). The reporting policy is in
[SECURITY.md](../../SECURITY.md).

## What the application does for you

| Control (spec §15.3) | How | Evidence |
|---|---|---|
| Authentication | LTI 1.3 launch only (development login is absent in production). The result is a 30-minute bearer token kept in the tab's `sessionStorage`, with no cookies, so it works with third-party cookies blocked. | `test_w3_lti_launch.py`, `unit/test_sessions.py`, `test_dev_login_routes_absent_in_production` |
| CSRF | There is no cookie-based API session, so a forged cross-site request carries no credentials. The LTI login and OAuth flows use single-use `state`. | `test_w3_lti_launch.py`, `test_forged_oauth_state_is_refused` |
| XSS | React escapes output. Server-rendered public pages escape all user text. The SPA has a strict CSP (`script-src 'self'`, `object-src 'none'`). | `test_script_in_badge_text_is_escaped_on_public_pages`, `test_security_headers` |
| SQL injection | Only SQLAlchemy bound parameters are used. | `test_injection_strings_in_queries_are_inert` |
| File uploads | SVGs pass an allow-list sanitiser; PNG metadata chunks are dropped; size limits apply; files are served with `nosniff`. | `unit/test_artwork.py`, `test_svg_upload_cannot_carry_script` |
| Role-based access | Every route has a server-side check. Roles come from Canvas and stored delegations, never from the request. | `test_w8_security.py` matrix |
| Tenant isolation | PostgreSQL row-level security, composite foreign keys, and an app role that does not own the tables. | `test_tenant_isolation.py`, `test_admin_of_one_institution_cannot_touch_another` |
| Secrets | Canvas tokens are encrypted at rest and never returned. Signing keys sit in the signer behind envelope encryption. Development secrets are refused in production. | `test_no_canvas_token_or_secret_in_any_api_response`, `unit/test_settings.py` |
| Key rotation | `did:web` verification methods can be rotated; old public keys stay published. | `test_did_web_rotation_keeps_old_credentials_verifiable` |
| Errors | RFC 9457 problem+json with a request id and no stack traces. | `test_unauthenticated_is_problem_json_with_request_id`, `test_malformed_and_oversized_bodies_fail_cleanly` |
| Security logging | Logins, role grants, issuer authorisation, issuance, revocation, sharing, exports and erasure go to the append-only audit log. | `test_audit_events_append_only`, `test_scenario_8_authorised_admin_revokes` |
| Response headers | `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin` on every response. A CSP on `/app`. `Cache-Control: no-store` on `/api`. HSTS when served over HTTPS. `X-Robots-Tag: noindex` except on shared pages. | `test_security_headers`, `test_public_check_page_and_robots` |
| Dependency scanning | `pip-audit` and `npm audit` (production dependencies) plus a licence allowlist on every pull request. Dependabot runs weekly. | CI job "Dependency audit and licences", [dependency report](../reports/dependency-scan.md) |

There is deliberately **no `X-Frame-Options` and no `frame-ancestors`**: Canvas shows the tool
in an iframe. If you want to limit framing, add `frame-ancestors https://<your-canvas-host>` at the
reverse proxy.

## What you must set up

### Secrets

Generate each of these with at least 32 random bytes, and keep them in a secrets store, not in
the repository or a shell history:

| Variable | Used by | Purpose |
|---|---|---|
| `OC_SECRET_KEY` | api, worker | Signs session tokens and OAuth state |
| `OC_SIGNER_SHARED_SECRET` | api, worker, signer | Authenticates calls to the signer |
| `OC_TOKEN_ENCRYPTION_KEY` | api, worker | Encrypts Canvas OAuth tokens at rest |
| `SIGNER_KEK` (32 bytes, base64) | signer only | Wraps the data keys that encrypt issuer private keys |
| Database passwords for `oc_owner`, `oc_app` and `oc_signer` | as below | |

With `OC_ENV=production`, the API and signer refuse to start if any of these is a committed
development value or too short.

### Keys

* Give `SIGNER_KEK` **only** to the signer container. Losing it means losing every signing key.
  Back it up separately from the database, under the same controls as a root CA key. Without it,
  the encrypted keys in a database backup are useless, which is the point.
* For a larger deployment, inject `SIGNER_KEK` from a secrets manager or a KMS rather than a
  plain environment file. The signer reads it once at start-up.
* Never use the development `did:key`. Create a `did:web` issuer on your verification domain
  (see the [production guide](../deployment/production.md#signing-keys-and-issuer-identity)).
* Rotate keys from Administration, Issuers. Never delete a historical key in routine rotation.
  If a key is exposed, follow [key-compromise.md](key-compromise.md).

### Network

* Only the reverse proxy should be reachable from the internet. The signer, PostgreSQL and the
  worker must not be.
* Terminate TLS at the proxy and pass `X-Forwarded-Proto: https` so the API sets HSTS.
* **Rate limiting:** the API has no general per-client limit (Canvas sync has its own limit per
  course). Add a limit at the proxy for `/lti/`, `/api/` and the public `/verify` routes. Here is
  an example for nginx:

  ```nginx
  limit_req_zone $binary_remote_addr zone=oc:10m rate=10r/s;
  location / { limit_req zone=oc burst=40 nodelay; proxy_pass http://api:8000; }
  ```

### Database

* `oc_owner` runs migrations only. The running services must not have its password.
* `oc_app` and `oc_signer` are `NOBYPASSRLS`, and neither owns tables.
* Use TLS between the services and PostgreSQL if they are on different hosts.

### Logging and monitoring

* Logs are JSON lines with a `request_id`. They contain no tokens, keys or learner names. Ship
  them to your central logging.
* Alert on: `/readyz` failing; failed issuance jobs (Administration, Failed issuance); repeated
  401s or 403s from one address; signer `5xx`.

## Pre-production security review

Complete this checklist (D-SECREVIEW) for each production installation, and again after a major
upgrade. Record who checked each item and when.

| # | Check | How to check |
|---|---|---|
| 1 | `OC_ENV=production` on api, worker and signer | `POST /dev/login` returns 404; the signer starts (it refuses the development KEK in production) |
| 2 | Every secret above is unique and was generated for this installation | The services start (they refuse committed values) |
| 3 | `SIGNER_KEK` is held only by the signer and is backed up offline | Inspect the deployment manifests |
| 4 | A `did:web` issuer on the institution's own verification domain is authorised, and the demo `did:key` is retired | Administration, Issuers; `https://<domain>/.well-known/did.json` resolves |
| 5 | TLS everywhere; HSTS present | `curl -sI https://<host>/api/v1/verify` shows `Strict-Transport-Security` |
| 6 | Signer and database not reachable from outside | A port scan from outside the network |
| 7 | Proxy rate limiting configured | Send a burst and get 429s |
| 8 | Only the migration job holds the owner password | Inspect the deployment manifests |
| 9 | The Canvas developer keys have only the scopes in [canvas.md](../integrations/canvas.md#3-create-the-api-developer-key) | Canvas Admin, Developer Keys |
| 10 | The backup and restore drill was run on this installation | [backup-restore.md](../operations/backup-restore.md) |
| 11 | Dependency audit is clean for the deployed commit | The CI "Dependency audit and licences" job for that commit |
| 12 | The threat model was reviewed for any local changes | [threat-model.md](threat-model.md) |
| 13 | The institution policy (approvers, revokers, retention) has been set by the institution admin | Administration, Policy |
| 14 | The DPIA has been completed by the data protection officer | [privacy/dpia-notes.md](../privacy/dpia-notes.md) |
| 15 | The incident contacts and key-compromise runbook are known to the on-call team | [key-compromise.md](key-compromise.md) |
