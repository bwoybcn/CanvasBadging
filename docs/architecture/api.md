# API contracts (v1)

Spec §13. FastAPI generates the OpenAPI document; this file fixes the contract the implementation must match. W2 commits the generated `openapi.json` snapshot, and CI fails on unreviewed changes.

## Conventions

- Base `/api/v1`. JSON only. Auth: `Authorization: Bearer <session token>` from the LTI launch ticket exchange (dev: `/dev/login`, disabled when `ENV=production`).
- Tenant comes from the session. A resource from another tenant returns **404** (no disclosure). Missing permission inside the tenant returns **403**.
- Pagination: `?limit=` (default 50, max 200) and `?cursor=` (opaque). Responses look like `{ "items": [...], "next_cursor": "…" | null }`.
- Errors use RFC 9457 problem+json: `{type, title, status, code, detail, request_id, errors?: [{field, code, message}]}`. `code` is stable and machine-readable (for example `RULE_SOURCE_MISSING` or `AWAITING_RELEASE`).
- Every response carries `X-Request-ID`. A request may send its own `X-Request-ID`, which is accepted if it is a valid UUID.
- Mutations that issue, revoke, reissue, award or approve accept `Idempotency-Key` (UUID). The server stores key → response for 24 h per actor.
- Rate limits are per session and per IP on public routes. A limited request gets `429` with `Retry-After`.
- Every privileged mutation writes an `audit_events` row in the same transaction.
- The permission names below refer to [ADR-0013](adr/0013-authorisation-model.md).

## LTI and session (not under `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/lti/login` | OIDC login initiation |
| POST | `/lti/launch` | id_token launch, which redirects to `/app?ticket=` |
| GET | `/lti/jwks` | Tool public keys (client-credentials assertions) |
| GET | `/lti/config/{integration_id}.json` | Canvas developer key JSON (course_navigation, custom fields, scopes) |
| POST | `/api/v1/session/exchange` | `{ticket}` → `{token, expires_at, user, context:{course, roles}}` |
| POST | `/api/v1/session/refresh` | Extends the session. Returns 401 once the session is past its maximum life, so the user must relaunch |

## Resource groups

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET/PATCH | `/institutions/current` | `institution.read` / `institution.manage` | name, branding, verification_host, linkedin org, policy, retention, categories |
| GET/POST | `/admin/canvas-integrations` | `integration.manage` | register platform + API key; `POST …/{id}/authorize` starts the OAuth for the integration account |
| GET/POST/PATCH | `/admin/org-units`, `/admin/memberships` | `membership.grant` (scoped) | grants cannot exceed the granter's scope |
| GET/POST/PATCH | `/issuers`, `/issuers/{id}` | `issuer.manage` | `POST /issuers/{id}/approve` (`inst_admin`) |
| GET/POST | `/issuers/{id}/keys` | `keys.manage` | `POST` generates a key in the signer. `POST /issuers/{id}/keys/{kid}/activate`, `/retire`, `/revoke {reason}` |
| GET/POST/PATCH | `/issuers/{id}/delegations` | `issuer.delegate` | |
| GET/POST/PATCH/DELETE | `/achievements` | `achievement.create` / `.edit` (draft only) | filters: `course_id`, `state`, `issuer_id`. The body carries the draft version fields and `award_policy` |
| POST | `/achievements/{id}/submit` · `/approve` · `/reject` · `/publish` · `/archive` · `/restore` | lifecycle permissions | state-machine guarded. `approve` and `reject` take a review checklist and comment |
| POST | `/achievements/{id}/new-version` | `achievement.edit` | copies the published version into a new draft |
| GET | `/achievements/{id}/preview` | `achievement.read` | unsigned sample credential and page data, `"preview": true`, no proof |
| GET | `/achievement-versions/{id}` | `achievement.read` | immutable snapshot |
| GET/PUT | `/achievement-versions/{id}/rules` | `rules.edit` (draft only) | validates against Canvas snapshot (module has requirements, assignment exists) |
| GET/POST | `/assets` | `asset.upload` | multipart; SVG sanitised, PNG rendition; returns `{id, url, alt_text, warnings[]}` |
| GET/POST | `/templates` | `template.manage` | |
| GET | `/courses/{id}` · `/courses/{id}/canvas/modules` · `/courses/{id}/canvas/assignments` | `course.read` (staff) | pickers, read from snapshots |
| POST | `/courses/{id}/activate` · `/courses/{id}/sync` | `course.manage` · `course.sync` | sync is rate-limited (1 per 5 min per course) |
| GET | `/courses/{id}/progress` | `progress.read_course` | learner × badge matrix with outcome codes |
| GET | `/learners/me` | any | profile, courses |
| GET | `/learners/me/achievements` | any | available badges with per-rule progress |
| GET | `/learners/me/credentials` | any | collection across courses |
| POST | `/evaluations` | `evaluation.run` | `{version_id, user_ids[] or course}` re-evaluates and returns job id |
| GET | `/evaluations?version_id=&user_id=` | `evaluation.read` | history with per-rule sources |
| GET | `/awards?status=awaiting_confirmation` | `award.confirm` | lecturer queue; `limit` 1 to 500, default 100 |
| POST | `/awards/{id}/confirm` · `/awards/{id}/reject` | `award.confirm` | Idempotency-Key |
| POST | `/awards/confirm-all` | `award.confirm` | `{decision_ids[]}` (1 to 500). Each award gets the checks of a single confirm and stands on its own; returns `{confirmed, left, rows[]}` with a `code` and `message` for each one left waiting. Manual awards are always left (`CONFIRM_ONE_AT_A_TIME`); ids the caller cannot confirm are skipped silently |
| POST | `/awards/manual` | `award.manual` | `{version_id, user_id, justification, evidence[]}`; may require second approval per policy |
| GET | `/credentials/{id}` | owner (staff views are W7) | detail + live verification result + share state + LinkedIn values |
| GET | `/credentials/{id}/export` | owner or `credential.export` | `application/ld+json` download of the exact `signed_json` bytes, filename `<slug>-<date>.json` |
| GET/PUT/DELETE | `/credentials/{id}/share` | owner | `PUT {show_name, show_evidence}` turns sharing on or updates it (same link while active) → `{share:{shared, url, …}, linkedin:{fields, add_to_profile_url}, preview}`; DELETE withdraws the grant (credential not revoked). Anyone else gets 404 |
| POST | `/credentials/{id}/share/preview` | owner | `{show_name, show_evidence}` → exactly what the public page would show, plus what is never shown. Changes nothing |
| POST | `/credentials/{id}/revoke` | `credential.revoke` | `{reason_code, reason_text}` |
| POST | `/credentials/{id}/revocation-requests` | `credential.request_revoke` | lecturer path |
| POST | `/credentials/{id}/reissue` | `credential.reissue` | `{reason}`; old credential revoked as `superseded` |
| GET | `/audit` | `audit.read` | filters: action, resource, actor, from/to |
| GET | `/reports/summary` · `/reports/issuance.csv` · `/reports/failed-jobs` | `report.read` (scoped) | |
| POST | `/admin/jobs/{id}/retry` · `/admin/reconcile` | `jobs.manage` | |
| POST | `/admin/data-export` · `/admin/users/{id}/erase` | `privacy.manage` | async; returns job id |

## Public (no auth, separate router and DB role)

| Method | Path | Notes |
|---|---|---|
| GET | `/verify/{share_id}` | HTML page (server-rendered, OG tags, `noindex` unless the student opted in to indexing, which is a LATER option). Shows result, explanation of what verification means, permitted identity and evidence |
| GET | `/verify/{share_id}/credential.json` | the signed credential, so wallets can "add from URL" (CORS `*`) |
| GET | `/verify/{share_id}/verification.json` | machine-readable verification result for a share |
| GET | `/verify` | "Check a credential file" page: upload a file, posts to `/api/v1/verify` |
| GET | `/robots.txt` | `Disallow: /` (every response also carries `X-Robots-Tag: noindex`) |
| POST | `/api/v1/verify` | body: credential JSON (≤256 KB) → `{result: verified|revoked|expired|invalid|unable_to_verify, checks:[{name, ok, detail}], issuer:{id,name}, achievement:{name}}`. Rate-limited |
| GET | `/issuers/{slug}/did.json` | DID document (did:web resolution path) |
| GET | `/issuers/{slug}/profile` | OB3 Profile JSON-LD (content-negotiated HTML) |
| GET | `/status/{issuer_slug}/{list_id}` | signed BitstringStatusListCredential, `Cache-Control: max-age=300` |
| GET | `/achievements/{version_id}` | public achievement description page / JSON for `criteria.id` and `achievement.id` dereferencing |
| GET | `/assets/public/{sha256}.{png,svg}` | badge images referenced from credentials (content-addressed, immutable) |

## Internal: signer (cluster-internal only)

| Method | Path | Body → Response |
|---|---|---|
| POST | `/keys` | `{issuer_key_id, did}` → `{verification_method_id, public_key_multibase}` (private key written to `keys` schema) |
| POST | `/sign` | `{issuer_key_id, document}` → `{signed}`; rejects documents failing safe-mode expansion or schema |
| POST | `/sign-status-list` | `{issuer_key_id, list_meta, bits_gzip_b64}` → `{signed}` |
| POST | `/verify` | `{credential, options:{allow_network_dids}}` → check list |
| GET | `/healthz` | |

Auth between api/worker and signer is a shared bearer secret plus network isolation in compose. mTLS is optional in production.

## Credential shape (what `/sign` receives)

```json
{
  "@context": ["https://www.w3.org/ns/credentials/v2",
               "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json"],
  "id": "urn:uuid:…",
  "type": ["VerifiableCredential", "OpenBadgeCredential"],
  "issuer": {"id": "did:web:<host>:issuers:<slug>", "type": ["Profile"], "name": "University of Liverpool", "url": "https://www.liverpool.ac.uk/"},
  "validFrom": "2026-…Z",
  "name": "<achievement title>",
  "credentialSubject": {
    "type": ["AchievementSubject"],
    "identifier": [{"type": "IdentityObject", "identityType": "emailAddress", "hashed": true,
                    "identityHash": "sha256$…", "salt": "<random>"}],
    "achievement": {"id": "https://<host>/achievements/<version_id>", "type": ["Achievement"],
                    "achievementType": "…", "name": "…", "description": "…",
                    "criteria": {"id": "https://<host>/achievements/<version_id>#criteria", "narrative": "…"},
                    "image": {"id": "https://<host>/assets/public/<sha>.png", "type": "Image", "caption": "<alt text>"},
                    "alignment": []}
  },
  "evidence": [],
  "credentialStatus": {"type": "BitstringStatusListEntry", "statusPurpose": "revocation",
                       "statusListIndex": "94567", "statusListCredential": "https://<host>/status/<slug>/<list>"},
  "credentialSchema": [{"id": "https://purl.imsglobal.org/spec/ob/v3p0/schema/json/ob_v3p0_achievementcredential_schema.json",
                        "type": "1EdTechJsonSchemaValidator2019"}]
}
```

W4 must check the exact `identityHash` format, the `credentialSchema` type string and the `image` shape against the pinned schema and the 1EdTech validator before freezing this shape. Treat the example above as illustrative until then.
