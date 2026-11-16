# End-to-end tests

Playwright drives a real browser against a running stack (database, signer, API with the built
screens, worker).

| File | What it covers |
|---|---|
| `specs/scenarios.spec.ts` | The twelve journeys of spec §19.3 (E1 to E12): a lecturer creates and publishes a badge, a student earns it from Canvas progress, a manual award, download, sharing, checking by someone with no account, LinkedIn, revocation, access by the wrong person, and recovery after the signer stops |
| `specs/a11y.spec.ts` | WCAG 2.2 A and AA checks (axe) on every screen, on a desktop and a phone, plus keyboard use, page structure, 400% zoom, reduced motion and the words on the screen |
| `specs/helpers.ts` | Signing in as a demo person and other shared steps |

The scenarios run first, because they create the badges the accessibility pass then looks at.

## Running them

Start the stack (`docker compose up --build`, or the steps without Docker in
[docs/development/local-setup.md](../../docs/development/local-setup.md)), then:

```bash
cd tests/end_to_end
npm ci
npx playwright install chromium
npm test                # everything
npm run test:a11y       # accessibility only
```

`OC_BASE_URL` points the tests at another address (default `http://localhost:8000`). Traces are
off by default; add `--trace on` to one test to debug it.

## What these do not cover

People sign in here through the development sign-in page, not through Canvas. The Canvas launch
itself is tested without a browser in `backend/tests/integration/test_lti_launch.py`, and was
run by hand against a local Canvas ([docs/reports/e2e.md](../../docs/reports/e2e.md)).
