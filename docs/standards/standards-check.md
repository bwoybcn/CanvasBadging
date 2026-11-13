# Standards and integration check

Checked 13 November 2026 against the live official documentation listed in spec §23. Each finding says what the spec assumes, what the source says, and what we will do. Items marked **Correction** change or sharpen the spec; items marked **Confirmed** match it; items marked **Unverified** could not be checked from source today and must be checked by the named workstream before code depends on them.

## 1. Open Badges 3.0

Sources: [OB 3.0 specification](https://standards.1edtech.org/open-badges/specifications/standards/v3p0) (Final, document version 1.4.5, 29 Jun 2026), [errata](https://standards.1edtech.org/open-badges/specifications/standards/v3p0/errata), [Conformance and Certification Guide](https://standards.1edtech.org/open-badges/specifications/standards/v3p0/cert) (latest revision 15 Jun 2026), [Implementation Guide](https://standards.1edtech.org/open-badges/guides/standards/v3p0/impl).

| # | Finding | Status | Decision |
|---|---|---|---|
| OB-1 | **Proof formats.** The errata moved the list of allowed proof formats out of the spec and into the Conformance Guide. For Issuers the guide accepts only Data Integrity proofs, using `eddsa-rdfc-2022` (EdDSA Cryptosuites v1.0) or `ecdsa-sd-2023` (ECDSA Cryptosuites v1.0). VC-JWT (RS256) still appears as an example in spec §8.2 but is **not** listed as a certifiable issuer proof. Displayers/verifiers must support **both** `eddsa-rdfc-2022` and `ecdsa-sd-2023`. | **Correction** to §7.3 (it leaves the choice open) | Sign with `DataIntegrityProof` / `eddsa-rdfc-2022`, Ed25519 keys as Multikey. No VC-JWT in MVP. Our verification page only has to verify our own credentials, but the machine-readable verifier should accept `ecdsa-sd-2023` too if we later verify uploaded third-party badges. [ADR-0002](../architecture/adr/0002-proof-format.md) |
| OB-2 | **Data model version.** Examples and schemas use VCDM 2.0: context `https://www.w3.org/ns/credentials/v2`, then `https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json`; dates are `validFrom` / `validUntil` (not `issuanceDate`). VCDM 1.1-compatible schemas exist for legacy issuers. | Confirmed / sharpened | Issue VCDM 2.0 only, context **3.0.3** (latest; added `endorsementJwt`, `@protected` from 3.0.2). Pin context files locally in the document loader; never fetch contexts at runtime. |
| OB-3 | **Schema validation.** Official JSON Schema `ob_v3p0_achievementcredential_schema.json`; credentials SHOULD carry `credentialSchema` pointing to it. | Confirmed | Validate every credential against the pinned schema before signing (C-OB3-02). |
| OB-4 | **Validity rule in certification.** A badge is valid if it "passes JSON-LD validation in safe mode" and meets verification requirements. | New detail | Run `jsonld` expansion in safe mode in the signer before signing; any undefined term fails issuance. Do not add custom properties without an extension context. |
| OB-5 | **Revocation.** The guide's Displayer section defines revoked as `credentialStatus.type = "BitstringStatusListEntry"` with `statusPurpose = "revocation"`; expired means now > `validUntil`. The Implementation Guide recommends Bitstring Status List v1.0. No `1EdTechRevocationList` in the current text. | Confirmed (§7.6) | Use Bitstring Status List with `statusPurpose: revocation`. [ADR-0006](../architecture/adr/0006-credential-status.md) |
| OB-6 | **Recipient identification.** The Implementation Guide says: use a DID in `credentialSubject.id` only when the learner proves control of it; for download/URL delivery, **omit `credentialSubject.id`** and use `credentialSubject.identifier` (an `IdentityObject`, e.g. `identityType: emailAddress`, `hashed: true`, `identityHash` = SHA-256 of value+salt, `salt`). | **Correction / clarification** to §7.5 | Follow the guide: no subject `id` in MVP; one salted hashed identifier. Spec §7.5's warning about hashing is respected by using a random per-credential salt and documenting the limit (anyone holding the credential can test a guessed email). [ADR-0007](../architecture/adr/0007-recipient-identity.md) |
| OB-7 | **Issuer identity and keys.** Guide suggests an HTTPS-hosted issuer profile associated with `did:web`; `verificationMethod` is a fragment of the issuer id; public key published as Multikey (`publicKeyMultibase`) or JWK. Guide notes common DID methods lack rotation semantics and suggests HSMs. | Confirmed (§7.4) | `did:web` per issuer on the institution's verification domain. [ADR-0004](../architecture/adr/0004-issuer-identity-did-web.md), [ADR-0005](../architecture/adr/0005-key-storage-rotation.md) |
| OB-8 | **OB API** (`/ims/ob/v3p0/credentials`, `/profile`, `/discovery`, OAuth 2.0 with dynamic client registration) is required for Host and Service Consumer/Provider roles, **not** for Issuer certification. | **Correction** to §13 ("implement standards-defined transport endpoints") | Not in MVP. Delivery = signed JSON download + public URL. OB API Provider (Read) is the first candidate for §21 2F. [ADR-0014](../architecture/adr/0014-credential-delivery.md) |
| OB-9 | **Certification** requires 1EdTech membership, issuing a badge to `conformance@imsglobal.org`, and a video of recipient retrieval. | Confirmed (§19.4) | W8 runs the public validator and records results. We never say "certified" unless granted. |
| OB-10 | The guide says it is "not necessary to sign the credential except when delivering it". | Design note | Sign at issuance (needed for the status-list binding and immutability), not lazily on download. |
| OB-11 | Open Graph tags (name, description, image) recommended on the HTML view. | Confirmed (§9.4) | Verification page emits OG tags with achievement data only, never learner name unless the student shares it. |

## 2. Bitstring Status List

Source: [Bitstring Status List v1.0](https://www.w3.org/TR/vc-status-list/), W3C Recommendation, 15 May 2025.

| # | Finding | Status | Decision |
|---|---|---|---|
| BSL-1 | Entry: `type: BitstringStatusListEntry`, `statusPurpose`, `statusListIndex` (base-10 string), `statusListCredential` (URL). Optional `id` must not equal the list URL. | Confirmed | Implement exactly. |
| BSL-2 | List credential: type `BitstringStatusListCredential`, subject type `BitstringStatusList`, `encodedList` = GZIP then multibase base64url (no padding); index 0 is left-most bit. | Confirmed | Use `@digitalbazaar/vc-bitstring-status-list` for encode/decode; sign the list with the issuer key. |
| BSL-3 | Minimum uncompressed size 16 KB = **131,072 entries**; smaller lists raise `STATUS_LIST_LENGTH_ERROR`. | New detail | One list per issuer per 131,072 credentials; allocate a new list when full. |
| BSL-4 | Indexes SHOULD be assigned randomly (herd privacy). | New detail | Random unused index per credential (DB unique constraint). |
| BSL-5 | Optional `ttl` (ms) aligned with HTTP `Cache-Control`. | New detail | `ttl` 300000 (5 min) and `Cache-Control: max-age=300`; revocation is visible to verifiers within 5 minutes. |

## 3. Canvas LTI 1.3 and placements

Sources: [Navigation placements](https://developerdocs.instructure.com/services/canvas/external-tools/lti/placements/file.navigation_tools), [LTI tools intro](https://developerdocs.instructure.com/services/canvas/external-tools/lti/file.tools_intro), [Names and Role Provisioning](https://developerdocs.instructure.com/services/canvas/resources/names_and_role.md).

| # | Finding | Status | Decision |
|---|---|---|---|
| LTI-1 | `course_navigation` placement: `placement`, `message_type: LtiResourceLinkRequest`, `target_link_uri`, `text`, `icon_url`, `enabled: true`; settings `default` (`enabled`/`disabled`), `visibility` (`public`/`members`/`admins`), `windowTarget: "_blank"` to open in a new tab (omit = iframe), `display_type`. | Confirmed (§4.1) | Generate the developer-key JSON from config; label "Micro-Credentials". |
| LTI-2 | An account-level install shows the link in every course of that account and sub-accounts by default; with `default: disabled`, instructors must enable it in course Settings → Navigation. | **Clarification** of §4.1 "course-level enabling" | Ship `default: disabled` + an app-side per-course activation flag that institution policy can require. |
| LTI-3 | Canvas LTI Advantage services: NRPS (read), AGS (LineItems, Result read-only, Score), Platform Notification Service, plus Canvas-specific scopes (`lti-ags/progress`, `public_jwk/update`, `account_lookup/show`, `page_content/show`). Client-credentials tokens are scoped to where the tool is deployed and to the tool's own line items. | Confirmed (§4.3) | NRPS for roster. AGS not used (we never write grades; it cannot read arbitrary existing grades). |
| LTI-4 | NRPS: `GET /api/lti/courses/:course_id/names_and_roles`, scope `.../lti-nrps/scope/contextmembership.readonly`. `user_id` is the LTI user id. **Canvas numeric user id is only present** inside `message` as `https://www.instructure.com/canvas_user_id`, and `message` is only returned when `rlid` is passed. `name`/`email` depend on the tool's privacy level. | **Correction**: NRPS alone does not map users to REST ids | Pass `rlid` (the course-nav resource link id) on NRPS calls, and add custom launch variables `canvas_user_id=$Canvas.user.id`, `canvas_course_id=$Canvas.course.id`. Privacy level `public` (needs email for recipient hash, name for UI); institution can choose `email_only` + REST lookup. |
| LTI-5 | Canvas Users API does not document lookup by LTI 1.3 id. | New detail | Persist the (LTI sub ↔ Canvas user id) mapping from launches and NRPS; never derive one from the other. |
| LTI-6 | Third-party-cookie-restricted browsers. | **Unverified** | W3 to confirm Canvas support for the LTI Client Side postMessage / platform storage spec (`lti_storage_target`) on the sandbox. Fallbacks either way: state+nonce held server-side keyed by a signed state value, SPA session by in-memory bearer token (no cookie), and an institution option for `windowTarget: _blank`. |
| LTI-7 | The local sandbox is `http://localhost:3000`. LTI 1.3 and `did:web` normally need HTTPS. | New constraint | Dev profile: tool on `https://localhost:8443` (mkcert), Canvas dev install allowed over http; issuer uses `did:key` in dev (self-resolving, independently verifiable). See [open-questions.md](../architecture/open-questions.md) Q3. |

## 4. Canvas REST API

Sources: [OAuth2 overview](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth.md), [Modules](https://developerdocs.instructure.com/services/canvas/resources/modules), [Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions), Live Events [Module](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/canvas/file.data_service_canvas_module.md), [Grade](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/canvas/file.data_service_canvas_grade.md), [Submission](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/canvas/file.data_service_canvas_submission), [setup](https://developerdocs.instructure.com/services/canvas/data-services/live-events/overview/file.data_service_setup.md).

| # | Finding | Status | Decision |
|---|---|---|---|
| API-1 | REST access needs an **API developer key** and the OAuth2 authorization-code flow; tokens expire after 1 hour and are refreshed with the (reused) refresh token; tokens act as the authorising user. `client_credentials` is documented only for LTI Advantage (NRPS/AGS), not for REST. | Confirmed (§4.3 note) — now concrete | Two Canvas keys per installation: an LTI key (launch, NRPS) and an API key (REST, scopes enforced). REST token comes from an institution-designated integration account. [ADR-0009](../architecture/adr/0009-canvas-data-access.md) |
| API-2 | Module progress: `GET /api/v1/courses/:course_id/modules?student_id=…` (and `/modules/:id/items?student_id=…`) returns `state` (`locked`/`unlocked`/`started`/`completed`), `completed_at`, and per-item `completion_requirement.completed`, **only** when the caller is the student or passes `student_id` (needs a role that can view that student's progress). | Confirmed | One call per learner per course (`include[]=items`) for module rules. |
| API-3 | A module with no completion requirements reports `requirement_type: "all"` and its completion state is not a meaningful signal. | **New risk** for Rule A/B | Authoring rejects a module rule whose module has no completion requirements; sync flags it if requirements are later removed. |
| API-4 | Submissions: `GET /api/v1/courses/:course_id/students/submissions?student_ids[]=…&assignment_ids[]=…` with fields `score`, `grade`, `excused`, `workflow_state`, `submitted_at`, `missing`, `late`, `grade_matches_current_submission`, and **`posted_at`** ("date this submission was posted to the student, or nil"). | Confirmed; sharpens §6.4 | "Released" = `posted_at` not null. Score rule needs: posted, `workflow_state = graded`, `grade_matches_current_submission = true`, not excused, `points_possible > 0` (from the assignment). Otherwise `unknown/pending`. |
| API-5 | **No Live Event for module completion** (only module/module item create/update). `grade_change` carries `muted` and `grading_complete` but no posted flag; `submission_created/updated` have no `posted_at`. | **Correction** to §4.4 "prefer event-driven" | Polling reconciliation is the source of truth. Live Events (HTTPS, signed JWT, 3 retries then drop) are optional *hints* that schedule a re-read; never trusted for issuance. [ADR-0010](../architecture/adr/0010-sync-strategy.md) |
| API-6 | Live Events subscriptions are created by an admin in the Data Services UI; HTTPS delivery can be signed (JWT, Canvas JWKS rotated monthly); failing endpoints are retried 3 times then the subscription may be deactivated. | New detail | Optional, admin-configured; verify JWT signature; treat as lossy. |
| API-7 | Pagination (`Link` header) and throttling. | **Unverified** today (well known, not re-read) | W3 to confirm header names (`X-Rate-Limit-Remaining`, 403 "Rate Limit Exceeded") against the docs before coding the client. |

## 5. LinkedIn

Source: [addtoprofile.linkedin.com](https://addtoprofile.linkedin.com). The help pages cited in spec §23 block automated fetching (robots), so they were not re-read.

| # | Finding | Status | Decision |
|---|---|---|---|
| LI-1 | `https://www.linkedin.com/profile/add?startTask=CERTIFICATION_NAME` with optional `name`, `organizationId` **or** `organizationName` (never both), `issueYear`, `issueMonth`, `expirationYear`, `expirationMonth`, `certUrl` (URL-encoded), `certId`. | Confirmed (§9.3) | Builder enforces orgId XOR orgName; institution config holds LinkedIn organization id. Values also shown as copyable fields. |

## 6. Libraries

| # | Finding | Status | Decision |
|---|---|---|---|
| LIB-1 | `PyLTI1p3` last release is 2.0.0 (Nov 2022). | **Maintenance risk** vs §3.2 "maintained LTI library" | Thin in-house LTI 1.3 launch module on `joserfc` (JWT/JWKS) following the 1EdTech Security Framework, with a negative test per claim. [ADR-0008](../architecture/adr/0008-lti-library.md) |
| LIB-2 | Digital Bazaar Data Integrity stack (`@digitalbazaar/vc` 7.3.0, `eddsa-rdfc-2022-cryptosuite` 1.3.0, `ed25519-multikey`, `vc-bitstring-status-list`, `jsonld` 9) is BSD-3-Clause and actively released (Feb 2026). No equally mature Python implementation of `eddsa-rdfc-2022`. | Decision driver | Signer is a small Node/TypeScript service. [ADR-0003](../architecture/adr/0003-signer-service.md) |
| LIB-3 | All candidate dependencies are AGPL-compatible (MIT, BSD, Apache-2.0, MPL-2.0, LGPL-3.0, PSF). | Confirmed | See [dependencies.md](../architecture/dependencies.md). |

## 7. Spec corrections summary

1. §7.3: proof format is not open: use Data Integrity `eddsa-rdfc-2022` (or `ecdsa-sd-2023`); VC-JWT is not certifiable for issuers.
2. §7.5: omit `credentialSubject.id` without DID authentication; use a salted `IdentityObject`.
3. §7.2/§7.1: VCDM 2.0 + OB context 3.0.3; `validFrom`/`validUntil`; JSON-LD safe-mode validity.
4. §13: OB API is a Host/Service role and not required for an issuer; defer.
5. §4.4: Canvas has no module-completion event and no posted flag in grade events; polling is primary.
6. §4.3: NRPS gives Canvas user ids only with `rlid`; Users API has no LTI-id lookup; capture ids via custom variables.
7. §4.1: course-level enabling means `default: disabled` placement plus app activation.
8. §3.2: PyLTI1p3 is unmaintained; Redis is unnecessary if the job queue is Postgres-backed ([ADR-0011](../architecture/adr/0011-job-queue.md)).
