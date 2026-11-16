# OpenCredential (CanvasBadging)

Open-source micro-credentialling and digital badging for Canvas LMS. OpenCredential launches
inside Canvas over LTI 1.3, lets staff define badges with clear criteria, evaluates award rules
against real Canvas data, and issues signed [Open Badges 3.0](https://www.imsglobal.org/spec/ob/v3p0/)
verifiable credentials that learners own and can share.

Licence: [AGPL-3.0-or-later](LICENSE). Documentation: CC BY-SA 4.0.

## Status

OpenCredential works end to end and is tested on every change, but it has **not yet been used
with real students**. It is at version 0.1.0 with no published release.

What works today:

- **Inside Canvas.** Staff and students open "Badges" from the course menu (LTI 1.3). The class
  list comes from Canvas, and progress comes from Canvas modules, assignments and released
  marks.
- **Creating badges.** A step-by-step wizard with ready-made templates, artwork, review by a
  second person where the institution asks for it, and versions.
- **Awarding.** Automatically from Canvas data, confirmed by course staff, or by hand for one
  student or a list of student ID numbers. Badges for activity outside a module (library,
  volunteering, schemes) are supported.
- **Genuine Open Badges 3.0.** Every award is a signed verifiable credential
  (`eddsa-rdfc-2022`) that can be revoked. On every change, 1EdTech's own validator and the
  Digital Credentials Consortium verifier check the badges the product issues
  ([conformance report](docs/reports/conformance.md)). OpenCredential is **not 1EdTech
  certified**.
- **For students.** Progress towards each badge, badges private until the student shares
  them, a public page anyone can check, a download of the credential, a badge image, a
  printable certificate and a LinkedIn link.
- **For administrators.** Areas and issuers, signing keys, roles, policies, reports, an audit
  log, retention and erasure of personal data.
- **Running it.** A development stack in one command, and a production kit with TLS, rate
  limits and a release build ([deployment](docs/deployment/README.md)).

What is still to do before real use:

- It has only run against a Canvas installed on a developer's computer. It has not run on a
  hosted Canvas, and reading the class list has not been confirmed there.
- The permanent web address that badges are checked at has not been chosen. It is written
  into every badge, so it must be settled before the first real badge is issued.
- Nobody is notified of anything yet: no email and no Canvas message.
- A manual screen-reader pass and a usability test with lecturers have not been done.

The evidence for each requirement is in [docs/reports/dod.md](docs/reports/dod.md) and
[docs/reports/rtm-evidence.md](docs/reports/rtm-evidence.md).

## Quick start (development)

Requirements: Docker with Compose v2.

```bash
git clone https://github.com/bwoybcn/CanvasBadging.git
cd CanvasBadging
docker compose up --build
```

Then open <http://localhost:8000/app/> and sign in as one of the synthetic demo users. Compose
starts PostgreSQL 16, applies migrations, starts the signer, loads the demo data (the Academic
Skills Passport badges and 12 synthetic students), and runs the api, worker and an HTTPS proxy at
<https://localhost:8443> for LTI launches from a local Canvas. `scripts/smoke.sh` checks that it
all came up.

Every secret in `compose.yaml` and `.env.example` is a **development** value. The api and signer
refuse to start with them when `OC_ENV=production`, and refuse while a development signing key
is active. `OC_ENV` itself is required: no service starts without it. See [docs/development/local-setup.md](docs/development/local-setup.md) for running
the pieces without Docker, tests and troubleshooting.

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI app and worker (Python 3.12, package `opencredential`), Alembic migrations, Pytest suite |
| `signer/` | Node 22 / TypeScript signer service, the only process that touches private keys |
| `frontend/` | React + TypeScript + Instructure UI single-page app |
| `examples/` | Reusable demonstration data (Academic Skills Passport) |
| `docker/` | Dockerfiles, Postgres bootstrap, the development proxy and the production kit |
| `docs/` | Architecture, ADRs, API, development, security, deployment |
| `tests/` | Cross-cutting suites: end-to-end (Playwright) and standards conformance |
| `scripts/` | Smoke tests, backup and restore, and the licence gate |

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
