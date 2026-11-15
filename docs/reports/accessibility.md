# Accessibility report (spec §14.2, §19.5)

Target: WCAG 2.2 level AA. This report records what was tested, what was found, what was fixed,
and what still needs a person. Tested on 13 November 2026 (W8) against the built SPA served by the
API, with the demo data set.

**Summary.** Automated checks pass on every screen for every role, at desktop and phone sizes.
Keyboard use, landmark structure, 320 px reflow (equal to 400% zoom) and reduced motion are
covered by automated tests. All of these run in CI on every pull request. A manual pass with a
real screen reader (NVDA or VoiceOver) **has not been done** and is listed below as open work.
We do not claim WCAG conformance until it has been done.

## How it is tested

All checks are in `tests/end_to_end/specs/a11y.spec.ts` and run in the CI job "End-to-end
scenarios and accessibility (Playwright)".

| RTM | Check | Tool | Viewports |
|---|---|---|---|
| A-AXE-01 | Every signed-in screen passes axe with the rule sets `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` | axe-core 4.14 via `@axe-core/playwright` 4.14.0 | desktop (1280×720) and mobile (Pixel 7) |
| A-KBD-01 | The skip link is the first Tab stop and moves focus to `<main>`. Every navigation item is reachable with Tab and shows a visible focus indicator. | Playwright keyboard | desktop |
| A-SR-01 (structure) | One `h1` per screen; `nav` and `main` landmarks; navigation exposed as links with `aria-current="page"` (not buttons) | Playwright accessibility tree | desktop |
| A-ZOOM-01 | At 320 CSS px wide (WCAG 1.4.10, the same as 1280 px at 400% zoom) no screen scrolls horizontally. Wide tables scroll inside their own focusable, labelled region. | Playwright | 320×800 |
| A-MOTION-01 | With `prefers-reduced-motion: reduce`, computed transition and animation durations are zero | Playwright media emulation | desktop |
| A-MOBILE-01 | axe on a phone viewport | as A-AXE-01 | Pixel 7 |

### Screens covered (26 per viewport)

| Role | Screens |
|---|---|
| Student | Home, My badges (progress), My credentials, Credential detail with sharing, Keeping your credentials |
| Lecturer | Home, Badges, Create micro-credential wizard, Badge detail with preview, Award badges (all three tabs), Course progress |
| Reviewer | Review queue |
| Institution admin | Overview (with the setup checklist), Institution settings, Faculties and departments, Courses, Staff roles, Issuers, Policy, Colleague review by area, Templates, Issued credentials, Reports, Audit log, Personal data and retention, Failed issuance |
| Public | Verify a credential, a shared credential page, development sign-in |

Result of the latest local run: **0 violations on 26 desktop screens and 0 on 26 mobile
screens** (`results/a11y-desktop.json`, `results/a11y-mobile.json`, uploaded as the
`e2e-results` CI artefact).

## Findings and fixes

Every issue below was found by the W8 tests and fixed in the same pull request.

| # | WCAG | Finding | Fix |
|---|---|---|---|
| 1 | 2.4.1 Bypass blocks | No way to skip the navigation | Added a "Skip to main content" link (visible on focus). The navigation is now outside `<main id="main-content">`. |
| 2 | 4.1.2 Name, role, value (carry-over from W6) | Navigation items were `role="button"` because InstUI `Link` with `onClick` renders as a button. Screen readers announced "button", and there was no current-page state. | `AppLink` now renders a real router link, with `aria-current="page"` on the current item |
| 3 | 1.3.1 Info and relationships (`definition-list`) | Copy buttons on Credential detail sat directly inside `<dl>` | Moved the button inside its `<dd>` |
| 4 | 1.4.1 Use of colour (`link-in-text-block`) | Links inside sentences were not underlined | Removed `isWithinText={false}`, so in-text links are underlined |
| 5 | 2.5.8 Target size (minimum) | Navigation links were under 24×24 px when the bar wrapped on a phone | Each item has padding and a minimum height of 24 px |
| 6 | 1.4.10 Reflow | Tables (admin lists, people, reports, awards, badges, course progress) and fixed-width form fields made the page scroll sideways at 320 px | Added `TableScroll` (a focusable, labelled scroll region, named from the table caption). Inputs are capped to the viewport width. Long DIDs and URLs wrap. |
| 7 | 2.3.3 Animation from interactions | InstUI transitions ignored the reduced-motion setting | A global `prefers-reduced-motion` rule switches off transitions and animations |
| 8 | 1.4.3 Contrast (test stability) | axe sometimes measured text halfway through InstUI's fade-in and reported low contrast | Not a product defect. The test now waits for transitions to settle before measuring. |

## Not yet done (needs a person)

| Item | Why it cannot be automated | Owner |
|---|---|---|
| **A-SR-01 manual screen-reader pass** with NVDA and Firefox on Windows, and VoiceOver and Safari on macOS or iOS, for the student journey (view progress, open a credential, preview and turn on sharing, download) and the lecturer journey (create a badge, submit, confirm an award) | Automated tests check structure, not what a listener hears or whether it makes sense | Recommended: the university's digital accessibility team, before the pilot |
| Real browser zoom at 200% and 400% in Chrome, Firefox and Safari | The 320 px test is equivalent for reflow, but text-spacing overrides (WCAG 1.4.12) were not tested | Same |
| Inside Canvas (iframe) with a screen reader | Page structure inside the Canvas frame depends on Canvas | Same |
| Plain-language review of the copy by a non-technical student panel | A matter of judgement | Product owner |

A blank record for the manual pass:

| Date | Tester | AT and browser | Journey | Issues found | Fixed in |
|---|---|---|---|---|---|
| | | | | | |

## Running it

```bash
cd tests/end_to_end
npm ci
OC_BASE_URL=http://localhost:8000 npx playwright test specs/a11y.spec.ts
```

The stack must be running with the built frontend (`OC_STATIC_DIR`) and the demo seed. See
[../demo.md](../demo.md).
