# API guide

OpenCredential's user interface is built entirely on its REST API, so anything the UI does, a
script or another system can do too. This guide explains how to call it. The complete reference
is the OpenAPI document [openapi.json](openapi.json): 98 paths, generated from the code. CI
fails if the committed copy differs from the code (`test_openapi_snapshot_is_current`).

To browse it, open `https://<host>/docs` (interactive), or load `openapi.json`
into any OpenAPI viewer. The original design contract, with the permission model behind each
route, is [../architecture/api.md](../architecture/api.md). Where the two differ, this guide and
`openapi.json` describe what is built.

## Authentication

| Caller | How it authenticates |
|---|---|
| A person, in Canvas | The LTI 1.3 launch ends at `/app/launch#session=<token>`. The SPA keeps that token in `sessionStorage` and sends `Authorization: Bearer <token>`. Tokens last 30 minutes (`OC_SESSION_TTL_MINUTES`). |
| A script, in development | `POST /dev/login {"institution": "<slug>", "user_id": "<id>"}` returns a token for a demo user. It is absent when `OC_ENV=production`. |
| Anyone, for public verification | Nothing. See [Public endpoints](#public-endpoints). |

There are no long-lived API keys and no cookies. A token carries the user and the institution.
Roles are looked up on the server for every request; nothing in the request can raise them.

## Conventions

* Base path `/api/v1`, JSON in and out.
* **Tenancy:** the institution comes from the token. Another institution's resource gives
  **404**, the same as one that does not exist. A resource you may see but not change gives
  **403**.
* **Errors** are RFC 9457 `application/problem+json`:

  ```json
  {"type": "about:blank", "title": "Not found", "status": 404, "code": "NOT_FOUND",
   "detail": "No such course.", "request_id": "01a1d5b3-…"}
  ```

  `code` is stable; use it, not `detail`, in programs. Validation errors (422) add `errors`.
* **Request ids:** every response has `X-Request-ID`. Send your own (a UUID) to correlate logs.
* **Lists** take `limit` (capped per endpoint, for example 200 for achievements). The
  achievements list also returns `next_cursor` for paging.
* **Idempotency:** award decisions are idempotent per learner and badge version, and issuance is
  idempotent per decision. Repeating a confirm, a manual award or an issue never creates a second
  credential (scenario E3).
* **Rate limits:** `POST /courses/{id}/sync` answers 429 if the course was refreshed within
  `OC_SYNC_MIN_INTERVAL_SECONDS`. Other limits belong at the reverse proxy (see the
  [security guide](../security/security-guide.md#network)).
* **Caching:** `/api/` responses carry `Cache-Control: no-store`.

## Endpoint groups

| Tag in `openapi.json` | Paths start with | Who |
|---|---|---|
| learners, student collection | `/learners/me…`, `/credentials/{id}…` | the signed-in learner (their own data only) |
| achievements, artwork | `/achievements…`, `/achievement-versions…`, `/assets…`, `/artwork-templates` | course staff (authoring), reviewers (approve, reject) |
| courses | `/courses…` | course staff; students may read their own course's sync state and request a refresh |
| eligibility and awards | `/evaluations`, `/awards…` | course staff |
| credentials | `/credentials/{id}/revoke`, `/revocation-requests`, `/reissue` | revokers by policy; course staff may request |
| administration, institutional administration | `/institutions/current…`, `/admin/…`, `/issuers…` | department and institution administrators, scoped |
| canvas | `/canvas/oauth…` | institution administrators |
| public verification | `/verify`, `/issuers/{slug}/did.json`, `/status/…` | anyone |
| health | `/healthz`, `/readyz` | monitoring |

## Common tasks

```bash
H="Authorization: Bearer $TOKEN"

# The signed-in user, their roles and the course they launched from
curl -s -H "$H" https://$HOST/api/v1/learners/me

# Switch a course on (it then reads Canvas every 30 minutes)
curl -s -X POST -H "$H" https://$HOST/api/v1/courses/$COURSE/activate

# Learner-by-badge progress for a course
curl -s -H "$H" https://$HOST/api/v1/courses/$COURSE/progress

# A learner downloads their signed credential
curl -s -H "$H" -o credential.json https://$HOST/api/v1/credentials/$CRED/export

# Issuance records as CSV (administrators)
curl -s -H "$H" -o issued.csv "https://$HOST/api/v1/admin/reports/issuance.csv"

# Revoke (a revoker under the institution policy); a reason is required
curl -s -X POST -H "$H" -H 'content-type: application/json' \
  -d '{"reason_code":"issued_in_error","reason_text":"Wrong learner"}' \
  https://$HOST/api/v1/credentials/$CRED/revoke
```

Check exact paths and bodies against `openapi.json`. These examples show the shape.

## Public endpoints

No authentication, and nothing private is returned. Use them from wallets, verifiers and
employers' systems.

| Method and path | Returns |
|---|---|
| `POST /api/v1/verify` with a credential as the body | `{"result": "verified" \| "revoked" \| "expired" \| "invalid" \| "unable_to_verify", "checks": [...]}`. `unable_to_verify` means something could not be reached; it is never a judgement of fraud. |
| `GET /verify` | A page where a person can check a file |
| `GET /verify/{share_id}` | A learner's shared credential page (only while they share it) |
| `GET /verify/{share_id}/credential.json` | The signed credential, for wallets |
| `GET /verify/{share_id}/verification.json` | The verification result as JSON |
| `GET /issuers/{slug}/did.json` | The issuer's `did:web` document, with every key ever used |
| `GET /status/{slug}/{list_id}` | A signed Bitstring Status List (revocation) |

Credentials are standard Open Badges 3.0 Verifiable Credentials, so any conformant verifier can
check them without these endpoints. See the [conformance report](../reports/conformance.md).

## Standards-defined APIs

The Open Badges 3.0 API (`/ims/ob/v3p0/…`) is **not** implemented. It is needed only for Host
and Service Provider certification, not for issuers ([ADR-0014](../architecture/adr/0014-credential-delivery.md)).
Credentials are delivered by signed download and public URL.
