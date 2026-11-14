# Demonstration environment (spec §18.3, §22.15)

This page takes a new developer from a clean clone to the full functional demonstration:
authoring, Canvas progress, automatic and manual awards, signed Open Badges 3.0 credentials,
sharing, external verification and revocation. It needs no Canvas and no internet access
(apart from pulling images). All the data is synthetic and marked as demonstration data.

## 1. Start it (about 5 minutes)

Requirements: Docker with Compose v2, and Git.

```bash
git clone https://github.com/bwoybcn/CanvasBadging.git && cd CanvasBadging
docker compose up -d --build
scripts/smoke.sh                       # prints "SMOKE OK" when everything is up
```

Compose starts PostgreSQL 16, applies the migrations, starts the signer, loads the demo
institution, and starts the API (which serves the app) and the worker. Open
<http://localhost:8000/app/>.

To start again from scratch: `docker compose down -v && docker compose up -d`.

## 2. What is in the demo

* **Demo University (development)**, with the issuer *Academic Skills Centre (DEVELOPMENT)*.
  Its key is a development `did:key`, refused in production.
* A course reading from a fake Canvas (the same adapter interface as real Canvas) with ten
  modules and five assignments.
* The **Academic Skills Passport** (spec §11.3): nine published badges in three themes, using
  every rule type and all three awarding policies
  (`examples/academic-skills-passport/passport.json`).
* Three staff (a lecturer, a reviewer and an administrator) and twelve synthetic students whose
  progress covers every case, including unreleased and excused marks.

## 3. Walk through it

Sign in from the development sign-in page. Each step names the user to choose.

| # | As | Do | You should see |
|---|---|---|---|
| 1 | Lee Lecturer | **Badges → Create micro-credential**. Complete the seven steps (the module picker lists the fake Canvas modules). **Save draft**, open **Preview**, then **Submit for review**. | A preview marked "not issued and not verifiable" |
| 2 | Riley Reviewer | **Review queue**, open the badge, tick every checklist point, **Approve** | The badge moves to Approved |
| 3 | Lee Lecturer | Open the badge, **Publish**. Then open **Course progress**. | Every student against every badge, with "Pending: mark not released" where marks are hidden |
| 4 | Lee Lecturer | **Award badges**: confirm one award on **Waiting to confirm**. Then, on **One student**, make a manual award with a justification. | The awards are issued within seconds (the worker signs them) |
| 5 | A student with an award (for example Chloe Synthetic) | **My credentials** | The credential, Valid and Private |
| 6 | Same student | Open it, **Download**; turn on the public link (check the preview first); open **Add to LinkedIn** | A signed `.json` file, a public link, prefilled LinkedIn values |
| 7 | Nobody (a private window) | Open the public link, or go to <http://localhost:8000/verify> and upload the file | "Verified", with the issuer, criteria and what verification means |
| 8 | Avery Admin | **Administration → Issued credentials**, revoke that credential with a reason | Uploading the same downloaded file on `/verify` now says "Revoked" |
| 9 | Avery Admin | **Reports**, **Audit log**, **Policy**, **Issuers** | Everything above, recorded and attributed |

To issue credentials to every qualifying demo student at once, without clicking:
`docker compose exec api oc issue-demo`.

## 4. Run the automated demonstration

The Playwright suite does the walk-through above, and more (E1–E12, plus the accessibility
checks), against the running stack:

```bash
cd tests/end_to_end
npm ci && npx playwright install chromium
npx playwright test --project=scenarios     # E12 needs OC_E2E_SIGNER_STOP/START, see the spec
```

Expect 12 passed. The [e2e report](reports/e2e.md) describes each scenario.

## 5. With a real Canvas

To connect a local Canvas instead of the fake one, follow
[integrations/canvas.md](integrations/canvas.md). `scripts/canvas-dev-register.sh` does the
Canvas-side registration through Canvas's API.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `smoke.sh` fails on `/readyz` with `signer` | The signer is still starting; wait a few seconds and retry |
| No development sign-in | `OC_ENV` is not `development`, or the seed did not run: `docker compose logs seed` |
| Awards are not turning into credentials (Administration shows them as "Awaiting issuance") | The worker is not running: `docker compose logs worker` |
| Port 5432 in use | Set `OC_POSTGRES_PORT=5433` before `docker compose up` |
| Development without Docker | [development/local-setup.md](development/local-setup.md) |
