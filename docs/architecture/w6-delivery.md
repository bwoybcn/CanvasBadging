# W6 delivery: student collection and portability (spec Phase 6)

## Exit condition

> A student can earn, download and share a credential, and an external party can verify it
> without Canvas access.

`backend/tests/integration/test_w6_sharing.py::test_phase6_exit_earn_download_share_and_outsider_verifies`
runs it end to end on PostgreSQL and the real signer: a fake Canvas reports a module complete,
sync and the rules engine award the badge, the issuance service signs it, the student sees it in
the collection, downloads it (valid against the official schema and verified by the independent
Python verifier), previews and turns on a public link; a client with no session opens the page
(Verified, `noindex`, no name), fetches `credential.json` and verifies it; withdrawing the link
gives 404 while the credential still verifies.

## Scenarios (spec §19.3)

| Scenario | Test | Also in CI |
|---|---|---|
| 6 Student export | `test_scenario_6_student_export_is_valid_ob3_with_verifiable_proof` | `student_share.py` → DCC verifier-core + 1EdTech inspector on student-downloaded files |
| 7 External verification | `test_scenario_7_external_verifier_reports_valid_then_revoked` (valid, revoked, tampered → invalid; share page shows Revoked) | same |
| 9 Canvas account closure | `test_scenario_9_export_survives_account_closure` (memberships revoked, user deleted, session refused, file still verifies) | |
| 11 LinkedIn | `test_scenario_11_linkedin_gets_certification_fields_and_a_working_url` | |

Privacy rules: `test_sharing_is_off_by_default_opaque_and_owner_only`,
`test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`,
`test_public_check_page_and_robots`. Frontend: `frontend/src/pages/__tests__/credentials.test.tsx`.

## Decisions taken in W6

- **`noindex` on everything, including shared pages** (open question Q17 default): header on every
  response, meta tag on the SPA and share pages, `robots.txt` disallows all.
- **One live link per credential** (`uq_share_grants_active`). Updating options keeps the link;
  withdrawing then re-sharing issues a new random id, so an old link never comes back.
- **Withdrawn and unknown links are indistinguishable** (same 404 body). The SECURITY DEFINER
  lookup `app.institution_for_share` only resolves active grants.
- **Open Graph never carries the learner's name**, even when the learner shows it on the page.
  SVG artwork is not offered as `og:image` (most preview crawlers ignore it).
- **Other people's credentials return 404**, not 403 (scenario 10 "without disclosure"). W7
  aligned the W4 export endpoint the same way.
- Migration `0006` (after W7's `0005`).
- **Badge images** referenced from credentials are now served at `/assets/public/<sha256>.<ext>`,
  only for assets of published versions (`app.institution_for_public_asset`).
- **LinkedIn**: `organizationId` when the institution sets `policy.linkedin_organization_id`,
  otherwise `organizationName`. No LinkedIn login, API or scraping.
- API shape: `PUT /credentials/{id}/share` (idempotent) instead of the `POST` sketched in api.md.

## Not done / follow-ups

- Learner Credential Wallet **app** import is not yet demonstrated (C-WALLET-01): it needs a
  public HTTPS verification host. The engine LCW uses is tested in CI. Manual steps:
  [../students/wallets.md](../students/wallets.md).
- `AppLink` (W5) renders InstUI links with a click handler, which InstUI exposes as role
  "button". Screen readers announce navigation links as buttons; worth fixing in W8's
  accessibility pass.
- Accessibility audit with assistive technology (spec §19.5) is W8.
