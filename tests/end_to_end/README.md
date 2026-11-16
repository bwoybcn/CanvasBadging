# End-to-end tests

Playwright drives a real browser against a running stack (database, signer, API with the built
screens, worker).

| File | What it covers |
|---|---|
| `specs/scenarios.spec.ts` | The twelve journeys of spec §19.3 (E1 to E12): a lecturer creates and publishes a badge, a student earns it from Canvas progress, a manual award, download, sharing, checking by someone with no account, LinkedIn, revocation, access by the wrong person, and recovery after the signer stops |
| `specs/a11y.spec.ts` | WCAG 2.2 A and AA checks (axe) on every screen, on a desktop and a phone, plus keyboard use, page structure, 400% zoom, reduced motion and the words on the screen |
| `specs/canvas-sign-in.spec.ts` | Opening Badges the way Canvas does: a lecturer and a student open it inside Canvas's frame, a lecturer switches a course on and the class list arrives, Badges opens in a tab of its own, and two launches that must be refused are refused |
| `specs/canvas-standin.ts` | The stand-in Canvas those tests use (see below) |
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
npm run test:canvas     # sign-in from the stand-in Canvas only (needs OC_E2E_OC, below)
```

`OC_BASE_URL` points the tests at another address (default `http://localhost:8000`). Traces are
off by default; add `--trace on` to one test to debug it.

Two groups of tests need a command from you, because they act on the stack itself. Without it
they are skipped on your machine. In CI both are set, and a missing one fails the run rather
than skipping quietly.

| Setting | What it is for | Example |
|---|---|---|
| `OC_E2E_OC` | Runs `oc` for the stack under test. The Canvas sign-in tests use it once to register their stand-in Canvas | `cd ../../backend && uv run oc` |
| `OC_E2E_SIGNER_STOP`, `OC_E2E_SIGNER_START` | Stop and start the signer, for the signer outage journey (E12) | see `.github/workflows/ci.yml` |

```bash
OC_E2E_OC='cd ../../backend && uv run oc' npm run test:canvas

## Signing in from Canvas

Most tests sign in through the development sign-in page, which is quick. The tests in
`canvas-sign-in.spec.ts` go through the real sign-in instead (LTI 1.3), in a real browser:

1. a course page in "Canvas" posts the login request to Badges, in a frame;
2. Badges sends the browser to Canvas's authorize address;
3. Canvas posts a signed launch back, and Badges checks the signature against Canvas's
   published key;
4. Badges opens inside the frame, signed in as that person in that course.

"Canvas" is a small stand-in that the test starts on port 3210 (`OC_E2E_CANVAS_PORT` changes
it). It is reached at two addresses on purpose. At `127.0.0.1` it is a different site from
Badges at `localhost`, so the browser withholds the sign-in cookie inside the frame, as it does
for a real Canvas on its own domain, and Badges has to recognise the browser through Canvas's
storage frame. At `localhost` it is the same site, and the cookie alone is enough. Both ways
are tested.

The stand-in registers itself as an institution called "Stand-in Canvas (end-to-end tests)",
separate from the demo institution. Each test uses a course nobody has opened before, so the
tests can run again and again against the same stack. The API must run on the same machine as
the tests (not in Docker), because it fetches the stand-in's signing key from a local address.
The stand-in keeps its signing key in `.cache/` (ignored by Git), because Badges remembers a
Canvas's keys for an hour.

## What these do not cover

The stand-in follows the same steps as Canvas, but it is not Canvas. These tests prove the
browser side of the sign-in: frames, cookies, the storage frame, redirects and the screens.
They do not prove that a real Canvas sends what the stand-in sends. That was checked by hand
against a local Canvas ([docs/reports/e2e.md](../../docs/reports/e2e.md)); the class list from
a hosted Canvas has not yet been seen working. Every refusal of a bad launch is tested without
a browser in `backend/tests/integration/test_lti_launch.py`.
