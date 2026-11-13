# OpenCredential architecture

Status: proposed (W1), 13 Nov 2026. Target first deployment: University of Liverpool, trialled on a local Canvas install before any production Canvas. Decisions are recorded in [`adr/`](adr/); this document is the overview that ties them together. Schema: [data-model.md](data-model.md). API: [api.md](api.md). Requirements: [rtm.md](rtm.md). Standards findings: [../standards/standards-check.md](../standards/standards-check.md).

## 1. Shape of the system

A **modular monolith** in Python (FastAPI) plus two small satellites: a **worker** (same codebase, different entrypoint) and a **signer** (Node/TypeScript, the only process that touches private keys). PostgreSQL is the single stateful store, including the job queue. Static SPA built with React/TypeScript and served by the API container. [ADR-0001](adr/0001-modular-monolith.md).

```text
                    Canvas LMS (LTI 1.3 platform + REST API + optional Live Events)
                       │ OIDC launch      │ NRPS (client-credentials)    │ REST (OAuth2 user token, read-only)
                       ▼                  ▼                              ▼
┌──────────────────────────────── api (FastAPI) ─────────────────────────────────┐
│ lti        authz/sessions   institutions/issuers   authoring   rules           │
│ issuance   credentials/share   reporting   audit   admin   public (verify/did) │
│ integrations/canvas (LmsAdapter impl)        storage (fs | S3)                  │
└──────┬────────────────────────────────────────────────────────────┬────────────┘
       │ SQL (app role, RLS)                                         │ HTTP on internal network (mTLS or shared secret)
       ▼                                                             ▼
┌──────────────┐   jobs (procrastinate, LISTEN/NOTIFY)   ┌────────────────────────┐
│ PostgreSQL   │◀──────────────────────────────────────▶│ worker (same image)     │
│ app schema   │                                         │ sync, evaluate, issue,  │
│ jobs schema  │                                         │ status publish, purge   │
│ keys schema  │◀──── keys role only ───────────────────│                         │
└──────────────┘                                         └──────────┬─────────────┘
       ▲  keys schema (encrypted private keys)                       │ sign / verify requests
       └─────────────────────────────────────────────────── ┌───────▼────────┐
                                                             │ signer (Node)  │
                                                             │ DB vc libs     │
                                                             └────────────────┘
```

## 2. Components

| Component | Responsibility | Key rules |
|---|---|---|
| `lti` | OIDC login initiation, launch validation, JWKS endpoint, dynamic config JSON for the Canvas developer key, deep-link-free course-nav launch | All claim checks server-side; nonce single-use; launch creates an app session, never trusts later client role hints. [ADR-0008](adr/0008-lti-library.md) |
| `authz` | Users, external identities, memberships, roles, session tokens, `can(actor, action, resource)` policy | Every route declares its permission; tenant id taken from the session, never from the request body. [ADR-0013](adr/0013-authorisation-model.md) |
| `institutions` / `issuers` | Tenant config, branding, policy, issuer records and delegation, LinkedIn org id, verification domain | Issuer cannot sign until an institutional admin records approval. |
| `keys` (API side) | Key lifecycle metadata, DID document generation | Never holds private material; asks signer to generate. [ADR-0005](adr/0005-key-storage-rotation.md) |
| `authoring` | Definitions, versions, assets (SVG sanitiser, PNG rendition), templates, categories, lifecycle state machine, preview | Published versions immutable (DB trigger). |
| `rules` | Rule schema, evaluation (three-valued: `met` / `not_met` / `unknown`), explanations, progress | Pure functions over a `LearnerSnapshot`; no I/O. |
| `integrations/canvas` | `LmsAdapter` implementation: REST client (pagination, throttling, retry), NRPS client, token refresh, Live Events receiver | Only GET calls; Canvas types never leak out of the package. [ADR-0009](adr/0009-canvas-data-access.md) |
| `sync` | Initial, scheduled and on-demand reconciliation into `lms_snapshot` tables; staleness tracking | Partial/failed fetch marks data `unknown`, never `not_met` or `met`. [ADR-0010](adr/0010-sync-strategy.md) |
| `issuance` | Award policy, idempotent award records, OB3 credential assembly, status index allocation, revocation, reissue | Idempotency key per (learner, version, policy). [ADR-0012](adr/0012-issuance-idempotency.md) |
| `signer` (Node) | Generate keys, sign credentials and status lists (`eddsa-rdfc-2022`), verify, JSON-LD safe-mode + schema checks | Pinned contexts, no network document loading. [ADR-0003](adr/0003-signer-service.md) |
| `status` | Bitstring Status List allocation, publish signed list credentials | 131,072 entries per list, random index. [ADR-0006](adr/0006-credential-status.md) |
| `public` | `/verify/{share_id}`, `/.well-known`-style DID documents, status lists, issuer profile, achievement pages, machine verification endpoint | Separate router, no session auth, cache headers, `noindex` unless shared. |
| `credentials` / `share` | Student collection, download, ShareGrant, LinkedIn builder | Share ids are 128-bit random, revocable. [ADR-0014](adr/0014-credential-delivery.md) |
| `reporting` | Counts, CSV exports | Scoped by authz; no free-text PII in CSV beyond what the role may see. |
| `audit` | Append-only audit events | Actor, action, resource, time, correlation id; PII minimised; DB role cannot UPDATE/DELETE. |
| `jobs` | Procrastinate tasks, retry policy, dead-letter view | Transactional enqueue with the business write. [ADR-0011](adr/0011-job-queue.md) |
| `frontend` | Student, lecturer, admin SPA (InstUI) | WCAG 2.2 AA; no Canvas token ever reaches it. [ADR-0015](adr/0015-frontend.md) |

## 3. LTI 1.3 launch flow

```text
Canvas                         OpenCredential api                          Browser
  │ 1. POST /lti/login (iss, login_hint, target_link_uri, lti_message_hint, client_id, lti_deployment_id, [lti_storage_target])
  │──────────────────────────────▶│ look up Platform by (iss, client_id); create state + nonce row (5 min TTL)
  │                                │ 2. redirect → Canvas /api/lti/authorize_redirect (scope=openid, response_type=id_token, response_mode=form_post, prompt=none, state, nonce)
  │◀───────────────────────────────│   (+ state also put in platform storage via postMessage if lti_storage_target present)
  │ 3. POST /lti/launch (id_token, state)
  │──────────────────────────────▶│ verify JWS against platform JWKS (cached, kid rotation), iss, aud ∋ client_id, azp, exp/iat (≤5 min skew),
  │                                │ nonce unused → mark used, state matches, deployment_id registered for this platform,
  │                                │ message_type = LtiResourceLinkRequest, version 1.3.0, context claim present for course nav,
  │                                │ roles → course role (Instructor/TA/ContentDeveloper → lecturer; Learner → student; Admin roles → staff),
  │                                │ custom canvas_user_id / canvas_course_id captured.
  │                                │ Upsert User / ExternalIdentity / Course / Membership (course scope) in the tenant of the Platform.
  │                                │ 4. Issue launch ticket (one-time, 60 s) → 302 to /app?ticket=…
  │                                │ 5. SPA exchanges ticket → session token (JWT, 30 min, held in memory, sent as Authorization: Bearer)
```

- Cookie independence: state verification uses the signed `state` value plus server-side row, so the flow works without third-party cookies; the session is a bearer token in memory (refreshable by a re-launch or a silent refresh endpoint bound to the session). CSRF does not apply to bearer-only APIs; the few form posts (launch) are protected by state/nonce.
- Course activation: if the institution requires it, a course is inert until a lecturer (or admin, per policy) activates it on first launch.
- Platform registration is per `CanvasIntegration` (issuer `iss`, `client_id`, JWKS URL, auth URL, token URL, deployments). The `iss` a self-hosted Canvas sends depends on its configuration; W3 records the local install's value.

## 4. Canvas data access and sync

- **Roster:** NRPS via client-credentials token (LTI key), `rlid` = the course-nav resource link id so Canvas user ids are included.
- **Modules, submissions, assignments, enrolments:** REST via an API developer key with scope enforcement, authorised by an institution-designated integration account (an account-level role with read-only "View course content", "View all grades", "View enrolments" style permissions). Tokens stored encrypted (`canvas_tokens`, envelope-encrypted with the app KEK), refreshed server-side. Per-instructor OAuth is the fallback option ([ADR-0009](adr/0009-canvas-data-access.md)).
- **Snapshot model:** sync writes normalised `lms_*` snapshot rows with `fetched_at` and `fetch_status`. Rules evaluate snapshots, not live API calls, so evaluations are reproducible and recorded.
- **Triggers:** initial sync on course activation; scheduled reconciliation (default every 30 min for courses with published badges, nightly for others); on-demand refresh from the lecturer or student UI (rate-limited); optional Live Events hint → targeted re-read.
- **Staleness:** snapshot older than policy (default 2 h) for any input a rule needs → that input is `unknown`.

## 5. Rules and award decisions

Rule set JSON (spec §6.3 shape, versioned schema `rules/v1`): `mode` ∈ {`ALL`,`ANY`}, `rules[]` of `module_completed`, `modules_completed`, `assignment_submitted`, `assignment_score`, `manual_approval`; one level of nesting only.

Evaluation per learner returns `{outcome, rules:[{rule_id, outcome, source:{kind, canvas_ids, fetched_at}, explanation_code, detail}]}` with Kleene logic (ALL: any `not_met` → `not_met`, else any `unknown` → `unknown`; ANY dual).

Score rule semantics (Gary: per badge choice of automatic or lecturer-confirmed):
- `met` only if `posted_at` set, `workflow_state = graded`, `grade_matches_current_submission`, not excused, `points_possible > 0`, `score / points_possible * 100 ≥ threshold`.
- Excused → `unknown` with code `EXCUSED` (lecturer can resolve by manual award). Unposted → `unknown` code `AWAITING_RELEASE`.
- Badge-level `award_policy`: `automatic` | `lecturer_confirmed` | `manual`. Institution policy can force `lecturer_confirmed` for any badge with a score rule.

A `met` evaluation creates an `AwardDecision` (status `ready` for automatic, `awaiting_confirmation` otherwise). Confirmation, manual award and justification are recorded on the decision.

## 6. Issuance and signing workflow

```text
AwardDecision(ready) ──(same tx)──▶ enqueue issue_credential(decision_id)
worker:
 1. SELECT … FOR UPDATE award row by idempotency_key = sha256(tenant|learner|achievement_version|policy|issuance_seq)
    - if credential exists with status issued → done (no-op)
 2. INSERT credential(status=pending_signature, id=urn:uuid, status_index allocated) — unique constraint guards duplicates
 3. build unsigned OB3 JSON (VCDM 2.0, context 3.0.3, issuer profile, achievement snapshot from version, identifier hash, evidence allowed by disclosure flags, credentialStatus, credentialSchema, validFrom, validUntil?)
 4. POST signer /sign {issuer_key_id, document}  → signer: safe-mode JSON-LD expand, JSON-Schema validate, sign eddsa-rdfc-2022, verify own output
 5. UPDATE credential SET signed_json, content_hash, status=issued, issued_at  (single tx with audit event)
 failures: step 4 transient → retry with backoff (decision kept); permanent → status=failed, visible in admin reconciliation.
 lost response: retry repeats from 1 and finds the row; signer is pure, so re-signing a pending row yields an equivalent credential and only one is stored.
```

- Reissue = new award row with `issuance_seq + 1`, requires `credential.reissue` permission and a reason; previous credential is revoked with reason `superseded`.
- Revocation = set bit in the issuer's status list, record `credential_status_events` (actor, reason), enqueue `publish_status_list`. Records are never deleted.
- Credential `id`: `urn:uuid:…` (not dereferenceable; avoids exposing a URL per credential). Public page URL is the separate share id.

## 7. Keys, issuer identity and verification

- Issuer DID: `did:web:<verification-host>:issuers:<issuer-slug>` → `https://<verification-host>/issuers/<issuer-slug>/did.json`. Verification host is per institution, configurable; placeholder `credentials.example.ac.uk` until UoL decides (Gary, Q3). Dev: `did:key`.
- Keys: Ed25519 generated in the signer; private key envelope-encrypted (AES-256-GCM, per-key DEK wrapped by a KEK from `SIGNER_KEK` secret or, optionally, Vault Transit / PKCS#11) and stored in the `keys` schema readable only by the signer's DB role. Key states: `pending` → `active` → `retired` (no new signatures, still published) → `revoked` (compromise; removed from `assertionMethod`). [ADR-0004](adr/0004-issuer-identity-did-web.md), [ADR-0005](adr/0005-key-storage-rotation.md)
- Rotation: new key becomes active; old key stays in the DID document so old credentials verify. Compromise: mark revoked, remove from DID doc, bulk-revoke affected credentials in status list (if the status list itself was signed by the compromised key, republish signed by the new key), and reissue on request. Procedure doc owned by W4, drilled in W8.
- Verification (`/verify/{share}` and `POST /api/v1/verify`): signer `/verify` checks proof (resolving our DID via local registry first, then network for foreign DIDs if enabled), schema, `validFrom`/`validUntil`, status list (fetch + verify list signature). Outcome mapping to spec §16.2: any proof/schema failure → `invalid`; status bit set → `revoked`; past `validUntil` → `expired`; status list or DID unreachable → `unable_to_verify`; else `verified`.

## 8. Authorisation and tenancy

- Tenancy: shared schema, `institution_id` on every tenant table, PostgreSQL Row-Level Security policies keyed on `current_setting('app.institution_id')` set per transaction, plus application scoping. Public routes run under a separate role with read access only to published public projections. [ADR-0016](adr/0016-tenancy.md)
- Roles: course-scoped (`student`, `lecturer`, `course_admin` from LTI roles, refreshed every launch and every NRPS sync) and org-scoped (`issuer_manager`, `dept_admin`, `inst_admin`, granted in-app, scoped to institution or an org unit/issuer). Policy is code (`authz/policy.py`) with a permission matrix test. Detail in [ADR-0013](adr/0013-authorisation-model.md).

## 9. Repository layout

```text
CanvasBadging/
  backend/                  FastAPI app (package: opencredential)
    opencredential/
      api/ lti/ authz/ institutions/ authoring/ rules/ issuance/ status/ public/
      credentials/ reporting/ audit/ jobs/ storage/ db/ settings.py
      integrations/canvas/  LmsAdapter implementation
    migrations/             Alembic
    tests/ (unit, integration)
  signer/                   Node/TS service (sign, verify, keygen, status lists), contexts pinned under signer/contexts/
  frontend/                 React + TS + Vite + InstUI
  tests/end_to_end/         Playwright
  tests/conformance/        1EdTech validator runs, independent verifier, fixtures
  docs/ architecture/ standards/ deployment/ administration/ development/ security/ reports/
  examples/                 seed data (Academic Skills Passport), sample configs
  docker/                   Dockerfiles, compose files (dev, single-tenant prod)
  scripts/  .github/  README.md CONTRIBUTING.md SECURITY.md LICENSE CHANGELOG.md
```

Deviation from spec §18.2: `credentials/` and `worker/` are packages inside `backend/` (same codebase), and the signer lives in its own top-level folder because it is a separate runtime.

## 10. Deployment

- Containers: `api` (uvicorn, also serves SPA), `worker` (procrastinate), `signer` (Node, internal network only), `postgres` 16+, reverse proxy (Caddy for dev/single host; any ingress in production). Optional: MinIO/S3 for assets, Vault for KEK.
- Dev (`docker compose up`): seeded UoL-like demo institution, demo issuer with `did:key`, dev keys (refused when `ENV=production`), Academic Skills Passport badges, synthetic learners, tool reachable at `https://localhost:8443` for the local Canvas at `http://localhost:3000`.
- Production: single-tenant compose profile or Kubernetes manifests (later); HTTPS everywhere; backups = `pg_dump` + asset bucket + KEK escrow (documented, restore tested in W8). Without the KEK backup, keys are unrecoverable by design.
- Observability: structured JSON logs (structlog) with correlation ids, `/healthz` and `/readyz`, Prometheus metrics endpoint (optional), failed-job dashboard in admin UI.

## 11. Test strategy

| Layer | Tooling | What | Gate |
|---|---|---|---|
| Unit | pytest + hypothesis; vitest | rules (property tests), lifecycle state machine, policy matrix, OB3 builder, LinkedIn builder, SVG sanitiser | every PR |
| Integration | pytest + testcontainers Postgres + real signer container; respx-recorded Canvas fixtures | DB constraints/RLS/immutability triggers, issuance idempotency incl. crash injection, status lists, LTI negative suite with a fake platform (our own key pair), Canvas adapter against recorded responses | every PR |
| Canvas live | pytest marked `canvas_live` against the local sandbox (`CANVAS_BASE_URL`) | launch, NRPS, modules, submissions, posted grades | manual/nightly on Gary's machine; fixtures re-recorded from here |
| End-to-end | Playwright (`--trace off` by default) | spec §19.3 scenarios E1–E12, third-party-cookie-blocked run | pre-merge for release branches |
| Conformance | 1EdTech validator (when accessible), pinned JSON Schema, independent verification with a **second implementation** (Python `pyld` + `cryptography` verifier written for tests, plus manual Learner Credential Wallet / VerifierPlus import) | C-OB3-*, C-INDEP-01, C-STATUS-01, C-WALLET-01 | release |
| Accessibility | axe via `@axe-core/playwright`, manual keyboard + NVDA/VoiceOver log | A-* | release |
| Security | pip-audit, npm audit, licence gate, cross-tenant suite, authz matrix, malicious SVG corpus, schemathesis fuzzing of OpenAPI | S-* | every PR (fast) / release (fuzz) |

## 12. Extension points for LATER items

`LmsAdapter` protocol (other LMSs); rule type registry (new rule kinds, pathways using earned badges as inputs); `alignment` on achievements (skills frameworks); `related`/pathway tables reserved; `CredentialTransport` interface (OB API, VC-API/CHAPI wallets); endorsement credentials reuse the signer; AI assistance would only produce draft text through the normal approval workflow.
