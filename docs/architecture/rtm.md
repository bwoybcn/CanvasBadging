# Requirements traceability matrix (MVP / MUST)

Source: OpenCredential specification v1.0 (13 Nov 2026). Every requirement the spec marks MVP / MUST, or states with "must" inside an MVP section, has one row. LATER items (§21, §9 "additional direct integrations") are excluded except where the spec asks for an extension point.

**How to read this.** *Component* names refer to [architecture.md §2](architecture.md#2-components). *Acceptance test* names the test that proves the row; IDs map to the test plan in [architecture.md §11](architecture.md#11-test-strategy):

- `U-*` unit (pytest / vitest), `I-*` integration (real Postgres, signer, recorded or live Canvas), `E1`–`E12` the end-to-end scenarios of spec §19.3 (Playwright against the Canvas sandbox), `C-*` standards conformance, `A-*` accessibility, `S-*` security, `D-*` documentation review (a named document exists and a reviewer has followed it).
- W5 status: see [w5-delivery.md](w5-delivery.md) for the tests that cover the W5 rows today and what still needs real Canvas.
- *WS* is the workstream that owns delivery (see `plan/workstreams.md`). A row is only "done" when its test passes in CI or, for `D-*`, the review is recorded (spec §22: "No feature may be marked complete solely because a UI element exists").

Component abbreviations: LTI = LTI launch; CAN = Canvas adapter; SYNC = sync/reconciliation; AUTHZ = authorisation and sessions; INST = institution and issuer admin; AUTH = badge authoring; RULES = rules engine; ISS = issuance service; SIGN = signer service; KEYS = key management; STAT = status lists; VER = verification service; SHARE = sharing/export/LinkedIn; AUD = audit; JOBS = worker; REP = reporting; UI-S / UI-L / UI-A = student / lecturer / admin UI; OPS = deployment and docs.

## §0–1 Process and principles

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-0.1 | No mocked or simulated issuance anywhere outside test doubles | ISS, SIGN | C-OB3-01 (credential from the running stack passes 1EdTech validator); code review rule in CONTRIBUTING | W4 |
| R-0.2 | Do not claim conformance/certification without evidence | OPS | D-CONF: conformance report links every claim to a test run | W8 |
| R-0.3 | RTM, standards check, architecture, ambiguities recorded before code | OPS | This document set merged | W1 |
| R-0.4 | Record decisions, dependencies, assumptions, unresolved issues | OPS | ADRs + `dependencies.md` + `open-questions.md` kept current (PR checklist) | all |
| R-1.1 | Product branding configurable (name, menu label) | INST, UI-* | U-BRAND-01 rendered name/menu label come from institution config | W7 |

## §2 Users and permissions

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-2.1-01 | Student views available credentials in enrolled courses | UI-S, AUTH, AUTHZ | E2 precondition; I-STU-01 lists only published badges for courses where caller holds Learner membership | W5 |
| R-2.1-02 | Student understands requirements | UI-S, RULES | I-STU-02 rule explanation text returned per rule | W5 |
| R-2.1-03 | Student sees progress | UI-S, RULES | E2, U-RULES-PROG | W5 |
| R-2.1-04 | Student views earned badges | UI-S | E2, E6 | W6 |
| R-2.1-05 | Student accesses evidence and achievement descriptions | UI-S, ISS | I-STU-03 evidence visible to owner per disclosure flags | W6 |
| R-2.1-06 | Student downloads standards-compliant credential | SHARE | E6, C-OB3-01 | W6 |
| R-2.1-07 | Student views/copies public verification URL | SHARE, UI-S | I-SHARE-01, E11 | W6 |
| R-2.1-08 | Student shares via external services | SHARE | I-SHARE-02 share links render OG metadata | W6 |
| R-2.1-09 | Collection across Canvas courses | UI-S | I-STU-04 credentials from two courses in one list | W6 |
| R-2.1-10 | Student chooses whether badge is publicly shareable | SHARE | I-SHARE-03 default private; toggle creates/revokes ShareGrant | W6 |
| R-2.1-11 | Student understands consequences of sharing | UI-S | A-COPY-01 disclosure panel lists every field that becomes public (reviewed) | W6 |
| R-2.1-12 | Students cannot modify criteria, self-issue, edit credentials, see others' data, edit issuer | AUTHZ | S-AUTHZ-STU matrix test (every mutating route ×Learner → 403/404) | W5/W7 |
| R-2.2-01 | Lecturer creates definitions | AUTH, UI-L | E1 | W5 |
| R-2.2-02 | Edits unpublished definitions only | AUTH | U-AUTH-LIFECYCLE edits rejected after APPROVED/PUBLISHED | W5 |
| R-2.2-03 | Configures award criteria | AUTH, RULES | E1, U-RULES-SCHEMA | W5 |
| R-2.2-04 | Links badges to Canvas activities (module/assignment pickers) | AUTH, CAN | I-CAN-PICK lists modules/assignments of the launched course | W5 |
| R-2.2-05 | Uploads or selects artwork | AUTH | I-ASSET-01 | W5 |
| R-2.2-06 | Previews before publishing | AUTH, UI-L | E1, I-PREVIEW-01 | W5 |
| R-2.2-07 | Submits for approval where required | AUTH | U-AUTH-LIFECYCLE | W5 |
| R-2.2-08 | Publishes approved credentials where authorised | AUTH, AUTHZ | U-AUTH-LIFECYCLE, S-AUTHZ-LEC | W5 |
| R-2.2-09 | Views student progress | UI-L, RULES | I-LEC-PROG | W5 |
| R-2.2-10 | Issues manual awards where authorised | ISS, AUTHZ | E5 | W5 |
| R-2.2-11 | Reviews automated decisions | UI-L, RULES | I-LEC-DECISIONS | W5 |
| R-2.2-12 | Reviews award history and exceptions | UI-L, REP | I-LEC-HISTORY | W7 |
| R-2.2-13 | Requests revocation | ISS, AUD | I-REVREQ-01 request recorded, credential unchanged until approved | W7 |
| R-2.2-14 | Exports course-level issuance records (CSV) | REP | I-REP-CSV-COURSE | W7 |
| R-2.2-15 | Cannot impersonate institutional issuer or award outside scope | AUTHZ, INST | S-AUTHZ-LEC (issue for issuer not delegated to course → 403) | W7 |
| R-2.3-01 | Dept admin reviews definitions across authorised courses | UI-A, AUTHZ | I-DEPT-01 scoped listing | W7 |
| R-2.3-02 | Approves/rejects definitions | AUTH | U-AUTH-LIFECYCLE, I-APPROVE-01 | W7 |
| R-2.3-03 | Applies programme templates/policies | INST, AUTH | I-TEMPLATE-01 | W7 |
| R-2.3-04 | Manages issuers within delegated scope | INST | S-AUTHZ-DEPT | W7 |
| R-2.3-05 | Reviews awards, exceptions, revocation requests | UI-A, REP | I-DEPT-02 | W7 |
| R-2.3-06 | Manages delegated permissions | AUTHZ | I-DELEGATE-01 cannot grant above own scope | W7 |
| R-2.4-01 | Inst admin configures integration and Canvas connections | INST, LTI, CAN | I-INST-CANVAS-01 (register platform, deployment, API token) | W3/W7 |
| R-2.4-02 | Configures organisational identity | INST | I-INST-01 | W7 |
| R-2.4-03 | Manages issuer identities and signing keys | KEYS, INST | I-KEYS-01 generate, rotate, retire; DID doc updated | W4/W7 |
| R-2.4-04 | Establishes policies and approval workflows | INST | I-POLICY-01 | W7 |
| R-2.4-05 | Defines institutional templates | INST | I-TEMPLATE-01 | W7 |
| R-2.4-06 | Delegates admin permissions | AUTHZ | I-DELEGATE-01 | W7 |
| R-2.4-07 | Reviews institution-wide records | REP | I-REP-INST | W7 |
| R-2.4-08 | Revokes credentials when authorised | ISS, STAT | E8 | W7 |
| R-2.4-09 | Configures retention and privacy policies | INST, JOBS | I-RETENTION-01 purge job honours settings | W7 |
| R-2.4-10 | Manages exports, backups, recovery | OPS, REP | I-EXPORT-INST; D-BACKUP + backup/restore drill (W8) | W7/W8 |
| R-2.4-11 | Inspects audit logs | AUD, UI-A | I-AUDIT-UI | W7 |
| R-2.4-12 | Configures public verification services (domain) | INST, VER | I-INST-DOMAIN DID doc and pages served on configured host | W7 |
| R-2.5-01 | Verifier opens shared page without Canvas account | VER | E7, E9 | W6 |
| R-2.5-02 | Confirms signature validity | VER | E7 | W6 |
| R-2.5-03 | Identifies issuing organisation | VER | E7 | W6 |
| R-2.5-04 | Reviews description and criteria | VER | E7 | W6 |
| R-2.5-05 | Sees valid / expired / revoked | VER, STAT | E7, E8, I-VER-EXP | W6 |
| R-2.5-06 | Evidence only where explicitly permitted | VER, SHARE | I-VER-EVIDENCE hidden unless disclosure flag + ShareGrant | W6 |
| R-2.5-07 | Signature validity not presented as proof of the educational claim | VER | A-COPY-02 wording review of verification page | W6 |

## §3 Architecture

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-3.1-01 | Independent web app integrated via LTI 1.3 + supported APIs | all | E1–E12 run against a real Canvas | W3 |
| R-3.1-02 | Backend independent of Canvas logic; adapters isolate LMS | CAN | U-ARCH-01 import-linter: no `integrations.canvas` import outside adapter registry | W2 |
| R-3.2 | Recommended stack, libraries vetted for maintenance + licence | OPS | `dependencies.md`; CI licence gate S-LIC-01 | W2 |
| R-3.2-02 | No bespoke cryptographic primitives | SIGN | Code review; SIGN uses Digital Bazaar suites + Node crypto only | W4 |
| R-3.4-01 | Multi-institution with strict tenant isolation | AUTHZ, DB | S-TENANT-01 (RLS + API cross-tenant suite), E10 | W2/W8 |
| R-3.4-02 | Single-institution self-hosted deployment | OPS | D-DEPLOY single-tenant compose profile boots | W2 |
| R-3.4-03 | Independent institution-specific issuer identities | INST, KEYS | I-KEYS-02 two tenants, two DIDs, cross-signing impossible | W4 |
| R-3.4-04 | Credentials separate from gradebook; no grade/submission modification | CAN | U-CAN-RO: adapter exposes only GET methods; API token scopes are read-only | W3 |
| R-3.4-05 | Signing keys stored separately from app data | KEYS, SIGN | S-KEYS-01 backend DB role cannot read key material table; keys only in signer | W4 |
| R-3.4-06 | Stable institution-controlled HTTPS URLs for issuer metadata & verification | VER, INST | I-INST-DOMAIN | W4 |
| R-3.4-07 | Export without commercial service | SHARE | E6 | W6 |
| R-3.4-08 | Dev/test do not rely on production Canvas | OPS | D-DEV: local Canvas sandbox + recorded fixtures | W2 |

## §4 Canvas integration

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-4.1-01 | LTI 1.3 with relevant Advantage services (NRPS) | LTI, CAN | I-LTI-01, I-NRPS-01 | W3 |
| R-4.1-02 | Admin-managed registration and installation | LTI, OPS | D-CANVAS-INSTALL followed on sandbox; I-INST-CANVAS-01 | W3 |
| R-4.1-03 | Course Navigation entry, configurable label (the specification's "Micro-Credentials"; default "Badges" since 15 Nov 2026) | LTI | I-LTI-CONFIG generated JSON has `course_navigation`, label from config | W3 |
| R-4.1-04 | Opens lecturer or student UI per validated permissions | LTI, AUTHZ | I-LTI-ROLE-01 instructor→lecturer view, learner→student view | W3 |
| R-4.1-05 | Account-level deployment supported | LTI | I-LTI-02 multiple courses under one deployment | W3 |
| R-4.1-06 | Course-level enabling subject to institution settings | LTI, INST | I-LTI-COURSE-ENABLE (placement default disabled + app course activation flag) | W3 |
| R-4.2-01 | OIDC launch; validate iss, aud/azp, deployment_id, nonce, state, signature, exp/iat, context, roles | LTI | I-LTI-NEG suite: one negative test per claim | W3 |
| R-4.2-02 | Replay and forged-launch protection | LTI | I-LTI-REPLAY nonce reuse rejected; S-LTI-FORGE wrong key rejected | W3 |
| R-4.2-03 | Client-side role indicators never sufficient | AUTHZ | S-AUTHZ-ROLE: server ignores any role field in request bodies | W3 |
| R-4.2-04 | Works with third-party cookies blocked | LTI | E-COOKIE Playwright run with 3P cookies blocked (iframe) | W3 |
| R-4.3-01 | Adapters: course, user, enrolment/role | CAN | I-CAN-01 | W3 |
| R-4.3-02 | Modules, module items, per-student completion | CAN | I-CAN-02 (Canvas sandbox) | W3 |
| R-4.3-03 | Assignments and submission status | CAN | I-CAN-03 | W3 |
| R-4.3-04 | Released (posted) grades where authorised | CAN | I-CAN-04 unposted score reported as `unreleased` | W3 |
| R-4.3-05 | Minimum Canvas permissions; documented extra OAuth | CAN, OPS | D-CANVAS-SCOPES lists every scope; I-CAN-SCOPE token with only those scopes passes I-CAN-01..04 | W3 |
| R-4.3-06 | NRPS for roster | CAN | I-NRPS-01 | W3 |
| R-4.3-07 | Do not assume AGS reads existing grades | CAN | Design rule (ADR-0009); no AGS read path | W3 |
| R-4.4-01 | Initial sync, scheduled reconciliation, on-demand refresh | SYNC, JOBS | I-SYNC-01..03 | W5 |
| R-4.4-02 | Retry, pagination, rate limits | CAN | U-CAN-PAGE (Link header), U-CAN-429 (backoff on 403 rate-limit / `X-Rate-Limit-Remaining`) | W3 |
| R-4.4-03 | Detect changed/deleted activities | SYNC | I-SYNC-DELETED rule marked `source_missing`, badge flagged | W5 |
| R-4.4-04 | Report inaccessible/incomplete data explicitly | SYNC, UI-L | I-SYNC-PARTIAL | W5 |
| R-4.4-05 | Event-driven where dependable, polling otherwise | SYNC | ADR-0010; I-LIVE-01 optional Live Events hint triggers re-read | W5 |
| R-4.4-06 | Canvas outage never causes incorrect issuance | RULES, SYNC | I-OUTAGE-01 (5xx/timeout → `unknown`, no issuance), E-scenario 15 of threat model | W5 |
| R-4.5 | Internal LMS adapter interface; Canvas specifics only in adapter | CAN | U-ARCH-01; protocol class `LmsAdapter` with fake implementation used by unit tests | W3 |

## §5 Authoring

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-5.1-01 | Guided create workflow | UI-L | E1 | W5 |
| R-5.1-02 | Field set & required-ness per table (title, short description, outcomes, criteria, issuer derived, artwork, category, evidence description, validity, skills, course, awarding method, approval) | AUTH | U-AUTH-VALID one case per required field | W5 |
| R-5.2-01 | Standard categories + local categories | AUTH, INST | U-AUTH-CAT | W5 |
| R-5.2-02 | Distinguish completion from competency (achievement type) | AUTH | U-AUTH-TYPE maps to OB3 `achievementType`; UI copy review | W5 |
| R-5.3-01 | SVG and PNG upload with preview, alt text, validation, size limits | AUTH | I-ASSET-01..04 | W5 |
| R-5.3-02 | SVG sanitised (no script, no external refs) | AUTH | S-SVG-01 corpus of malicious SVGs all neutralised | W5 |
| R-5.3-03 | Branding options + openly licensed templates | AUTH, INST | I-ASSET-TEMPLATES seed artwork with licence file | W5 |
| R-5.4-01 | DRAFT→IN_REVIEW→APPROVED→PUBLISHED→ARCHIVED; reject to draft | AUTH | U-AUTH-LIFECYCLE (state machine, all illegal transitions rejected) | W5 |
| R-5.4-02 | Institution configures self-approval | INST, AUTH | U-AUTH-SELFAPPROVE | W7 |
| R-5.4-03 | Exact version used for issuance preserved; substantive change → new version | AUTH | U-AUTH-VERSION; DB trigger test I-DB-IMMUT-01 | W5 |
| R-5.5-01 | Preview all listed elements | AUTH, UI-L | I-PREVIEW-01 | W5 |
| R-5.5-02 | Preview marked non-issued and non-verifiable | AUTH | I-PREVIEW-02 preview JSON has no proof, watermark present | W5 |

## §6 Rules engine

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-6.1 | Deterministic, explainable, auditable evaluation | RULES | U-RULES-DET (property test: same inputs → same output + explanation) | W5 |
| R-6.2-A | Module completion | RULES, CAN | U-RULES-A, E2 | W5 |
| R-6.2-B | Multiple module completion | RULES | U-RULES-B | W5 |
| R-6.2-C | Assignment submission | RULES | U-RULES-C, I-CAN-03 | W5 |
| R-6.2-D | Minimum score (%) | RULES | U-RULES-D, E4 | W5 |
| R-6.2-E | Manual approval | RULES | E5 | W5 |
| R-6.2-F | ALL / ANY, depth limited | RULES | U-RULES-F (depth >1 rejected) | W5 |
| R-6.4-01 | Per-student evaluation recording source of each result | RULES | U-RULES-SRC | W5 |
| R-6.4-02 | Incomplete vs unknown distinguished | RULES | U-RULES-TRI (three-valued logic) | W5 |
| R-6.4-03 | Prevent duplicate awards | ISS | E3 | W4 |
| R-6.4-04 | Missing grades, excused, unposted results | RULES | U-RULES-D cases; E4 | W5 |
| R-6.4-05 | Detect grade/module requirement changes | SYNC | I-SYNC-CHANGE | W5 |
| R-6.4-06 | Manual re-evaluation | RULES, UI-L | I-REEVAL-01 | W5 |
| R-6.4-07 | Actionable errors | RULES | U-RULES-ERR messages have code + remedy | W5 |
| R-6.4-08 | Audit history of evaluations | RULES, AUD | I-EVAL-AUDIT | W5 |
| R-6.4-09 | Grades only after release under institution policy; else pending/confirmation | RULES | E4, U-RULES-POLICY | W5 |
| R-6.5-01 | Automatic, lecturer-confirmed, manual policies | ISS | U-ISS-POLICY ×3, E2, E5 | W5 |
| R-6.5-02 | Award traceable to version, learner, issuer, decision/justification, timestamp | ISS, DB | I-DB-TRACE NOT NULL/FK constraints + query | W4 |
| R-6.6 | Idempotent issuance; reissue is separate authorised operation | ISS | E3, E12, U-ISS-IDEM | W4 |

## §7 Open Badges 3.0

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-7.1 | Real OB 3.0 VC built from normative spec + errata, no invented properties | ISS | C-OB3-01 (1EdTech validator), C-OB3-02 JSON Schema `ob_v3p0_achievementcredential_schema.json` | W4 |
| R-7.2 | All mandatory fields + listed metadata (id, type, issuer, subject, achievement name/description/criteria, dates, image, proof, status) | ISS | C-OB3-02 + U-ISS-FIELDS | W4 |
| R-7.2-02 | Evidence and skills alignment where permitted | ISS | U-ISS-EVIDENCE (only disclosed evidence emitted) | W4 |
| R-7.3-01 | Asymmetric signature in a conformance-accepted proof format | SIGN | C-OB3-01; ADR-0002 (`eddsa-rdfc-2022`) | W4 |
| R-7.3-02 | Independent verification | VER | C-INDEP-01 (verify with a second implementation, see test strategy) | W4 |
| R-7.3-03 | Issuer key discovery and key id | KEYS, VER | I-DID-01 `did.json` resolves, `verificationMethod` dereferences | W4 |
| R-7.3-04 | Key rotation with historical verification | KEYS | I-KEYS-ROTATE old credential still verifies after rotation | W4 |
| R-7.3-05 | Secure private-key storage; never in source, browser, logs | KEYS, SIGN | S-KEYS-01..03 (grep CI for key patterns, log scrubber test) | W4 |
| R-7.3-06 | Configurable issuer identity | INST, KEYS | I-INST-01 | W4 |
| R-7.4 | Distinct per-institution verifiable identity; institution approves it; no vendor-as-issuer | INST, KEYS | I-KEYS-02; U-INST-APPROVE issuer cannot sign until approved_by set | W4/W7 |
| R-7.5-01 | Privacy-preserving subject identification; no raw email public by default | ISS | U-ISS-SUBJ (salted hash only); S-PRIV-01 grep public pages | W4 |
| R-7.5-02 | Stable internal learner record | DB | I-DB-USER | W2 |
| R-7.5-03 | Document holder binding vs issuer signature | OPS | D-HOLDER (student and verifier guides) | W6 |
| R-7.6-01 | Bitstring Status List revocation | STAT | E8, C-STATUS-01 list credential validates | W4 |
| R-7.6-02 | Active / revoked / expired / failure / indeterminate | VER | I-VER-STATES ×5 | W4 |
| R-7.6-03 | Revocation needs authorisation + reason; no deletion | ISS, AUTHZ | I-REVOKE-01, S-AUTHZ-REVOKE | W7 |
| R-7.6-04 | Downloaded copy recognised as revoked | STAT, VER | E8 | W4 |
| R-7.7-01 | Export without hidden proprietary dependencies | SHARE | C-INDEP-01 using only public contexts/DID | W4 |
| R-7.7-02 | Verifiable after rotation/upgrades | KEYS | I-KEYS-ROTATE, I-UPGRADE (old fixture credentials verify after migration) | W8 |
| R-7.7-03 | Document preservation after migration/shutdown | OPS | D-PRESERVE | W8 |

## §8–9 Student interface, export, LinkedIn

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-8.1 | Dashboard: available, earned, collection | UI-S | E2, I-STU-04 | W6 |
| R-8.2 | Evidence-based progress; never claim earned when data unavailable | UI-S, RULES | U-RULES-TRI; Playwright check of "Awaiting published result" | W5 |
| R-8.3 | Credential detail fields | UI-S | I-STU-DETAIL | W6 |
| R-8.4-01 | Download, copy link, toggle public, see visible fields, portable copy | SHARE, UI-S | E6, I-SHARE-03 | W6 |
| R-8.4-02 | No indexing of private pages; nothing public by default | VER | S-PRIV-02 (`X-Robots-Tag: noindex` on all non-shared routes; unshared id → 404) | W6 |
| R-9.1 | Signed download, student-controlled URL, human page, copyable details, wallet docs, independent verifier + wallet demonstrated | SHARE, VER, OPS | E6, E7, C-WALLET-01 (import into Learner Credential Wallet, recorded) | W6 |
| R-9.2 | Standard data model; test against independent implementations; document wallet limits | SHARE, OPS | C-INDEP-01, D-WALLETS | W6 |
| R-9.3 | Add to LinkedIn: values + prefilled `profile/add` link; no scraping | SHARE | E11, U-SHARE-LI URL builder (orgId XOR orgName) | W6 |
| R-9.4 | OG metadata without unnecessary learner data; opaque share ids; no access to Canvas submissions | SHARE, VER | I-SHARE-02, U-SHARE-ID (≥128-bit random), S-PRIV-01 | W6 |
| R-9.5 | Explain retention after leaving; export without Canvas auth | OPS, SHARE | D-LEAVING; E9 | W6 |

## §10–11 Administration and academic credibility

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-10.1 | Institution configuration fields | INST | I-INST-01 | W7 |
| R-10.2 | Issuer records with explicit delegation; creation ≠ authority | INST | I-ISSUER-01 issuer inactive until approved | W7 |
| R-10.3 | Approval workflow configuration + decision audit | INST, AUTH, AUD | I-POLICY-01 | W7 |
| R-10.4 | Institutional templates | INST | I-TEMPLATE-01 | W7 |
| R-10.5 | Operational reporting + CSV | REP | I-REP-01..07 one per metric; I-REP-CSV | W7 |
| R-10.6 | Audit of listed actions with actor/action/resource/time; minimal PII | AUD | I-AUDIT-01 (one test per action type); S-PRIV-03 | W7 |
| R-11.1 | Required educational metadata; distinguish attending…assessed proficiency | AUTH | U-AUTH-VALID, U-AUTH-TYPE | W5 |
| R-11.2 | Non-credit first class; no implied credit unless approved | AUTH, INST | U-AUTH-CREDIT (credit wording/`creditsAvailable` blocked unless institution flag) | W5 |
| R-11.3 | Academic Skills Passport seed data (9 badges, 3 themes), not hard-coded | OPS | I-SEED-01 seeds load and can be deleted | W2 |
| R-11.4 | Evidence references; private evidence never public by default | ISS, SHARE | I-VER-EVIDENCE, U-ISS-EVIDENCE | W6 |
| R-11.5 | Human QA review supported | AUTH | I-APPROVE-01 with review checklist fields | W7 |

## §12–13 Data model and API

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-12.1 | Normalised, migration-controlled schema with the 20 entities | DB | I-DB-MIGRATE (upgrade/downgrade on empty + seeded DB) | W2 |
| R-12.2 | UUIDs; external ids scoped to platform+institution; no email PK | DB | I-DB-USER, schema lint | W2 |
| R-12.3 | Published versions and issued credentials immutable; corrections via reissue | DB, ISS | I-DB-IMMUT-01/02 (UPDATE raises) | W4 |
| R-12.4 | Relationships per list | DB | I-DB-TRACE | W2 |
| R-12.5 | Retention rules; export/delete personal data; separate delete/revoke/unshare; erasure doc | INST, JOBS, OPS | I-RETENTION-01, I-DSAR-01, D-ERASURE | W7 |
| R-13-01 | Versioned REST API route groups + separate `/verify/{share}` | API | I-API-ROUTES (OpenAPI snapshot) | W2+ |
| R-13-02 | Standards-defined transport endpoints only per normative standard | API | ADR-0014 (OB API deferred; nothing invented) | W6 |
| R-13.1 | OpenAPI, validation, authz, tenant isolation, pagination, structured errors, rate limits, idempotency, audit, correlation ids | API | I-API-CONTRACT (schemathesis against OpenAPI), S-RATE-01, U-API-ERR | W2+ |
| R-13.1-02 | Public verification exposes no private API | VER | S-PUBLIC-01 public router mounted separately, no auth cookies accepted | W6 |

## §14–17 UI, security, verification, jobs

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-14.2 | Responsive, keyboard, screen reader, contrast, not colour-only | UI-* | A-AXE-01 (axe on every route), A-KBD-01, A-SR-01 manual NVDA/VoiceOver log | W8 |
| R-14.2-02 | WCAG 2.2 AA target | UI-* | A-REPORT | W8 |
| R-14.3/4 | Lecturer and student workflow targets | UI-L, UI-S | E1, E2 step counts | W5/W6 |
| R-14.5 | Designed error states (9 listed) | UI-* | Playwright E-ERR suite, one per state | W5–W7 |
| R-15.1 | DPIA support docs | OPS | D-DPIA | W8 |
| R-15.2 | Privacy principles | all | S-PRIV-* | W8 |
| R-15.3 | Security controls list (HTTPS, sessions, CSRF, XSS, SQLi, uploads, RBAC, tenant, secrets, rotation, errors, dep scanning, security logs); no Canvas tokens in browser | all | S-* suite; S-TOKEN-01 (no token in any API response or SPA bundle) | W8 |
| R-15.4 | Threat model covering 15 threats | OPS | D-THREAT (each threat → mitigation → test ID) | W8 |
| R-15.5 | Key-compromise procedure documented and tested; never delete historical keys in routine rotation | KEYS, OPS | I-KEYS-COMPROMISE drill; D-KEY-COMPROMISE | W4/W8 |
| R-16.1 | Verification checks (structure, signature, issuer, method, validity, status, integrity) | VER | I-VER-STATES, C-INDEP-01 | W4 |
| R-16.2 | Five outcomes; infra failure ≠ fraud | VER | I-VER-STATES (status list 503 → "Unable to verify") | W4 |
| R-16.3 | Public page content; machine-readable verification; sharing ≠ revocation | VER, SHARE | I-VER-PAGE, I-VER-API, I-SHARE-03 | W6 |
| R-17 | Background jobs for sync, eval, issuance, notifications, status, retries | JOBS | I-JOBS-01 | W2/W5 |
| R-17.1 | Idempotent jobs, bounded retries, backoff, dead letter, visibility, structured logs, status, stale-data detection | JOBS | I-JOBS-02..05; U-SYNC-STALE | W5 |
| R-17.2 | Signing failure keeps decision; lost response retry no duplicate; reconciliation tools | ISS, JOBS | E12, I-RECON-01 | W4 |

## §18–20 Open source, testing, phases

| ID | Requirement | Component | Acceptance test | WS |
|---|---|---|---|---|
| R-18.1 | AGPL-3.0-or-later; dependency licences compatible; no paid deps | OPS | S-LIC-01 CI gate against allowlist in `dependencies.md` | W2 |
| R-18.2 | Repository structure | OPS | Repo layout per [architecture.md §9](architecture.md#9-repository-layout) | W2 |
| R-18.3 | Local install: compose, migrations, sample config, dev keys, demo issuer/badges/students | OPS | D-DEV followed from clean clone in CI (`make demo` smoke) | W2 |
| R-18.3-02 | Dev keys never usable in production | KEYS | U-KEYS-DEVGUARD (startup refuses dev key when `ENV=production`) | W2 |
| R-18.4 | Production docs (13 topics) | OPS | D-PROD checklist | W8 |
| R-18.5 | No mandatory cloud/vendor deps | OPS | Compose stack runs offline except Canvas | W2 |
| R-19.1–19.3 | Unit, integration, E1–E12 | QA | CI jobs green | all |
| R-19.4 | 1EdTech tooling + conformance report; no false certification claim | QA | C-OB3-01, D-CONF | W8 |
| R-19.5 | Accessibility testing (keyboard, SR, automated, mobile, reduced motion, zoom) | QA | A-* | W8 |
| R-19.6 | Dependency checks, authz, cross-tenant, malicious input; pre-prod review | QA | S-DEP-01 (pip-audit, npm audit), S-TENANT-01, S-FUZZ-01, D-SECREVIEW | W8 |
| R-20 | Each phase ships code, tests, docs and a phase report | OPS | Phase report in `docs/reports/phase-N.md` | all |
| R-22.1–22.15 | Definition of Done | — | Each DoD item maps to rows above; W8 produces `docs/reports/dod.md` | W8 |
| R-21 | LATER items get extension points only (LmsAdapter, rule type registry, skills `alignment`, pathways via achievement `related`, wallet transport interface) | all | Design review of ADR-0001 | W1 |
