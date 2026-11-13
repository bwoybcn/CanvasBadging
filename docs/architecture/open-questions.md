# Open questions, ambiguities and chosen defaults

Gary's answers of 13 Nov 2026 are recorded as decided. Everything else has a working default that W2–W8 follow until Gary says otherwise.

## Decided by Gary

| # | Question | Answer | Where reflected |
|---|---|---|---|
| G1 | Where does the code live? | github.com/bwoybcn/CanvasBadging | all |
| G2 | Canvas sandbox | Local Canvas at http://localhost:3000 on Gary's machine | ADR-0004 (dev `did:key`), test strategy |
| G3 | Verification / issuer domain | Decide later | Configurable `verification_host`. Placeholder `credentials.example.ac.uk`. Production issuer activation is blocked while the placeholder is set (ADR-0004) |
| G4 | Vertical slice pause or straight through | Full MVP straight through | Workstream plan unchanged. The slice is still demonstrated as a milestone, not a stop |
| G5 | Released-grade awards: automatic or lecturer-confirmed? | Both, per badge | ADR-0017. Institution default `lecturer_confirmed` (change if UoL prefers) |
| G6 | Institution | University of Liverpool, trial on the local install first, multi-tenancy designed in | ADR-0016. Seed institution "University of Liverpool (Development)" |

## Open, with defaults

| # | Ambiguity | Default chosen | Who should confirm |
|---|---|---|---|
| Q1 | Spec §7.3 leaves the proof format open | `eddsa-rdfc-2022` only (ADR-0002) | — (driven by the cert guide) |
| Q2 | Recipient name inside the signed credential? | Off. Name is shown only on the share page if the student opts in (ADR-0007) | Gary / UoL data protection |
| Q3 | HTTPS for local dev against an http Canvas | Tool runs at `https://localhost:8443` with mkcert; Canvas stays http; `did:key` issuer | W3 confirms the local Canvas accepts it |
| Q4 | Who holds the Canvas REST token | Integration account authorised by an inst admin; per-instructor OAuth as an option (ADR-0009) | UoL Canvas admins (policy on service accounts) |
| Q5 | Canvas privacy level for the LTI key | `public` (needs email for the recipient hash, name for UI) | UoL |
| Q6 | Excused assignment under a score rule | Treated as `unknown` (code `EXCUSED`). The lecturer can resolve it with a manual award | Gary |
| Q7 | Score percentage base | `score / points_possible` (raw score, after late deductions as Canvas reports them) | Gary |
| Q8 | Module with no completion requirements | Not selectable for module rules (API-3) | — |
| Q9 | Badge expiry | Optional `validity_days` on the version, which sets `validUntil`. No renewal workflow (LATER) | — |
| Q10 | Snapshot staleness limit | 120 min, institution-configurable | — |
| Q11 | Polling interval | 30 min for courses with published badges, nightly for the rest | W3 tunes after load measurement |
| Q12 | Nesting depth of rules | One level (top-level ALL/ANY whose children may be one ALL/ANY group) | — |
| Q13 | Who can revoke | inst_admin always; dept_admin within scope if policy allows; lecturers request only | UoL |
| Q14 | Manual award second approval | Off by default, institution toggle | UoL |
| Q15 | Course activation | Required (placement `default: disabled` + app activation by lecturer) | UoL |
| Q16 | Session lifetime inside Canvas | 30 min idle, 8 h max, renewed by relaunch | — |
| Q17 | Public page indexing | `noindex` always in MVP, even when shared (sharing ≠ discoverable) | Gary |
| Q18 | Share link expiry | No expiry. The student can revoke at any time | — |
| Q19 | Retention defaults | Audit 7 y; LMS snapshots 1 y after course end; launch state 10 min; failed jobs 90 d; credentials kept for as long as verification is offered | UoL records management |
| Q20 | Credential `id` | `urn:uuid` (not dereferenceable). Verification URL is the separate share link | — |
| Q21 | Job queue | Postgres-backed, no Redis (ADR-0011). This deviates from the "recommended stack" in §3.2, which says "where required" | Gary |
| Q22 | LinkedIn organisation | `organizationId` from UoL's LinkedIn page if configured, else `organizationName` | UoL comms |
| Q23 | 1EdTech validator access | Use the public validator if reachable without membership. Otherwise the JSON Schema plus independent verifiers only, and the conformance report says so | Gary (UoL may be a 1EdTech member) |

## Unverified assumptions (owners must check before relying on them)

- Canvas support for LTI client-side postMessage storage (`lti_storage_target`) on the local install (W3).
- Canvas REST throttling headers and exact scope strings for the API key (W3).
- The `iss` value the local Canvas sends in launches (W3).
- Exact `IdentityObject.identityHash` format and `credentialSchema` type string, checked against the pinned JSON Schema and the validator (W4).
- Learner Credential Wallet import of our credentials and `did:web` resolution (W6).
