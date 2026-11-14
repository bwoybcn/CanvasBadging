# Connecting OpenCredential to Canvas

This guide installs OpenCredential in a Canvas instance: one **LTI 1.3 developer key** (launch,
course menu item, roster) and one **API developer key** (read-only REST access for module
progress, assignments and released grades). It was written and checked against a local Canvas
(open-source build of 30 April 2026) at `http://localhost:3000`; differences for
Instructure-hosted Canvas are noted.

Why two keys: LTI authentication does not grant REST access (spec §4.3, ADR-0009). The LTI key
gives the launch and Names and Roles (NRPS). Module progress, submissions and grades need the
REST API, authorised once by an integration account.

## What you need

- Canvas root-account admin rights (to create developer keys).
- OpenCredential running and reachable by browsers at its public URL (`OC_PUBLIC_BASE_URL`).
  Locally that is `http://localhost:8000` (or `https://localhost:8443` through Caddy).
- A Canvas user to act as the **integration account** (see step 4).

## 1. Create the LTI 1.3 developer key

1. Print this deployment's configuration:

   ```bash
   docker compose exec api oc lti config > opencredential-lti.json
   ```

   It is also served at `<public URL>/lti/config.json`. It contains the tool's public key only.
   Use `--jwks-url` if Canvas can reach `<public URL>/lti/jwks` (production): key rotation then
   needs no Canvas change. Use `--label` to change the menu text.

2. In Canvas: **Admin → (root account) → Developer Keys → + Developer Key → + LTI Key**.
   Choose **Method: Paste JSON**, paste the file, set **Key Name** to `OpenCredential` and
   **Redirect URIs** to `<public URL>/lti/launch`. Save.
3. Switch the key **On**. Note the **Client ID** shown in the Details column (for example
   `10000000000012`).

What the configuration contains:

| Setting | Value | Why |
|---|---|---|
| Login URL | `<public URL>/lti/login` | OIDC third-party initiated login |
| Target link / redirect | `<public URL>/lti/launch` | id_token `form_post` |
| Placement | `course_navigation`, text **Micro-Credentials**, `default: disabled` | Each course opts in (Q15) |
| Privacy level | `public` | Name for the UI, email for the recipient identifier (Q5) |
| Custom fields | `canvas_course_id=$Canvas.course.id`, `canvas_user_id=$Canvas.user.id`, `canvas_user_sis_id=$Person.sourcedId`, `canvas_account_id=$Canvas.account.id` | Link LTI identities to REST ids; the student ID number lets staff award a badge to a list; the sub-account places the course in a linked area |
| Scopes | `contextmembership.readonly` (NRPS) only | Least privilege; no AGS |

Existing installs: add `canvas_user_sis_id=$Person.sourcedId` to the developer key's custom
fields to use list awards by student ID number. Without it, student IDs are still read from the
LTI `lis.person_sourcedid` claim and from the Names and Roles roster when Canvas includes them;
list awards by email work either way. Add `canvas_account_id=$Canvas.account.id` too so new
courses join the area linked to their sub-account on first launch; without it, linking looks each
course up through `GET /api/v1/courses/:id` instead. Reading the sub-account tree uses
`GET /api/v1/accounts` and `GET /api/v1/accounts/:id/sub_accounts?recursive=true`, so the
connected Canvas user must be an account administrator.

## 2. Install the tool

Deploy it at the root account so every course can use it (spec §4.1):

- **Current Canvas (LTI Registrations, 2025+)**: **Admin → Apps → Manage → OpenCredential (LTI)
  → Availability & Exceptions → Deploy**. API: `POST /api/v1/accounts/1/lti_registrations/<registration id>/deployments`.
  On the local Canvas the classic "install by client ID" answers *"This app has been locked by
  an administrator"* for keys created this way, so use this path.
- **Older Canvas**: **Admin → Settings → Apps → View App Configurations → + App → By Client
  ID**, paste the client id, **Install**.

Note the **Deployment Id** (for example `2:8865aa05b4b79b64a91a86042e43af5ea8ae79eb`): both
screens show it, and the API returns it.

## 3. Create the API developer key

**Developer Keys → + Developer Key → + API Key**:

- **Key Name**: `OpenCredential API`
- **Redirect URIs**: `<public URL>/api/v1/canvas/oauth/callback`
- **Enforce Scopes**: on, then tick only these (all GET):

  | Scope | Used for |
  |---|---|
  | `url:GET\|/api/v1/courses/:id` | course name and state |
  | `url:GET\|/api/v1/courses/:course_id/modules` | modules and per-student progress (`student_id=`) |
  | `url:GET\|/api/v1/courses/:course_id/modules/:module_id/items` | completion requirements |
  | `url:GET\|/api/v1/courses/:course_id/assignments` | assignments, points possible |
  | `url:GET\|/api/v1/courses/:course_id/students/submissions` | submissions, scores, `posted_at`, excused |
  | `url:GET\|/api/v1/courses/:course_id/enrollments` | enrolment checks |
  | `url:GET\|/api/v1/users/:user_id/profile` | the authorising account's identity |

  Note the profile scope is spelt `:user_id` on current Canvas (ADR-0009 originally said `:id`;
  `url:GET|/api/v1/users/:id/profile` does not exist).

Save, switch the key **On**, and note its **Client ID** and **Key** (secret).

## 4. Create the integration account

A Canvas user whose token OpenCredential uses for REST reads (ADR-0009). Give it an account
role with only:

- *Courses – view list* (`read_course_list`)
- *Course Content – view* (`read_course_content`)
- *Users – view list* (`read_roster`)
- *Grades – view all grades* (`view_all_grades`), needed for other students' module progress
  and submissions.

**Admin → Permissions → Account Roles → + Role** (`OpenCredential read-only`), enable the four
permissions, then **Admin → Settings → Admins → + Account Admins** and add the integration
user with that role. Scope it to a sub-account if only some courses use OpenCredential.

## 5. Register Canvas in OpenCredential

```bash
export OC_CANVAS_API_CLIENT_SECRET='<API key secret>'   # read from env, never stored in plain text
docker compose exec -e OC_CANVAS_API_CLIENT_SECRET api oc canvas register \
  --institution uol-dev --create-institution "University of Liverpool (Development)" \
  --base-url http://localhost:3000 \
  --client-id <LTI client id> --deployment-id <deployment id> \
  --api-client-id <API client id>
```

Defaults derive the platform endpoints from `--base-url`:
`/api/lti/authorize_redirect`, `/login/oauth2/token`, `/api/lti/security/jwks`, and issuer
`https://canvas.instructure.com` (the value the local Canvas sends; check `config/security.yml`
`lti_iss` on self-hosted Canvas). **Instructure-hosted Canvas** uses
`--auth-url https://sso.canvaslms.com/api/lti/authorize_redirect`,
`--token-url https://sso.canvaslms.com/login/oauth2/token`,
`--jwks-url https://sso.canvaslms.com/api/lti/security/jwks`.

Launches from a deployment id that is not registered are refused (`DEPLOYMENT_UNKNOWN`); add
more with `--deployment-id` (the command is idempotent).

## 6. Bootstrap an administrator and authorise the API

1. Open any course, enable **Micro-Credentials** in **Settings → Navigation** (it starts
   hidden), and launch it once as the person who will administer OpenCredential.
2. Grant them the institution admin role:
   `docker compose exec api oc admin grant --institution uol-dev --email <their Canvas email>`
3. Create the one-time authorisation link and open it in a browser **signed in to Canvas as the
   integration account**:
   `docker compose exec api oc canvas connect --institution uol-dev --admin-email <admin email>`
   (admins can also call `POST /api/v1/canvas/integrations/{id}/oauth/start`). Approve the
   scopes. The callback stores the tokens encrypted (AES-256-GCM, `OC_TOKEN_ENCRYPTION_KEY`),
   marks the integration **active**, and shows "Canvas is connected".

Tokens never reach a browser, a log line or an API response. Access tokens last an hour and are
refreshed server-side; `GET /api/v1/canvas/integrations` shows connection status only.

## 7. Use it in a course

Teachers enable **Micro-Credentials** under course **Settings → Navigation** (or an admin does
it with `PUT /api/v1/courses/:id/tabs/context_external_tool_<tool id>` `hidden=false`).
Launching shows the user's name, the course, and their role, and opens the lecturer view for
Teachers, TAs, Designers and course admins, and the student view for students.

| Canvas role (LTI) | OpenCredential course role |
|---|---|
| Teacher (`membership#Instructor`) | lecturer |
| TA (`membership/Instructor#TeachingAssistant`) | lecturer |
| Designer (`membership#ContentDeveloper`) | lecturer |
| Course admin context role (`membership#Administrator`) | course_admin + lecturer |
| Student (`membership#Learner`) | student |
| Student View test user (`person#TestUser`) | student only |
| Account admin, observer, institution roles | none (org roles are granted in OpenCredential) |

Roles are re-read from the signed launch every time and from NRPS on every sync; Canvas
removals revoke them (ADR-0013).

### Switch micro-credentials on for the course

By default (institution policy `course_activation_required`, Administration → Policy) a course
takes part only once a lecturer switches it on. The first lecturer launch shows **Switch on
micro-credentials for this course**. Switching on reads Canvas straight away and then every 30
minutes. A lecturer, course admin or administrator can switch it off again with
`POST /api/v1/courses/<id>/deactivate`. Issued credentials are not affected. If the policy is
off, every course joins at its first launch.

## Changing the tool's address

Canvas stores the launch URL in two places: the developer key's configuration and the
**installed tool** (the deployment). Changing the developer key (for example, moving from
`http://localhost:8000` to `https://localhost:8443`, or to the production domain) does **not**
update the installed tool, and the Canvas UI does not show the stale URL. Launches then keep
going to the old address. After changing the key, also update the installed tool:

```bash
curl -X PUT "$CANVAS/api/v1/accounts/1/external_tools/<tool id>" \
  -H "Authorization: Bearer $CANVAS_ADMIN_TOKEN" \
  -d "url=https://<new host>/lti/launch" \
  -d "domain=<new host>" \
  -d "course_navigation[url]=https://<new host>/lti/launch"
```

Then update the API developer key's redirect URI to
`https://<new host>/api/v1/canvas/oauth/callback`, and set `OC_PUBLIC_BASE_URL` to the new
address. Verified on the local Canvas on 13 November 2026 ([e2e report](../reports/e2e.md)).

## Local development notes

- `compose.yaml` sets `OC_CANVAS_URL_REWRITE=http://localhost:3000=http://host.docker.internal:3000`
  so containers reach a Canvas published on the host. Browsers still use `localhost:3000`.
- `http://localhost:8000` works for launches from an `http` Canvas: both are the same *site*,
  so the binding cookie is sent. Behind `https://localhost:8443` (Caddy) the tool is a
  different site from `http://localhost:3000`, so the cookie would be blocked in the iframe and
  the platform-storage path below is used. Both paths were exercised over HTTPS on 13 November
  2026 ([e2e report](../reports/e2e.md)); trust Caddy's local CA, or ignore certificate errors in
  a test browser.
- **NRPS fails on a local Canvas whose domain has a port** (`localhost:3000`): Canvas returns 500
  from Names and Roles (`URI::InvalidComponentError` in
  `NamesAndRolesController#find_memberships_page`). Sync then logs `sync.roster_failed` and keeps
  the existing roster; users still appear when they launch. Hosted Canvas is unaffected.
- A script that performs steps 1-5 through Canvas's APIs is in
  [`scripts/canvas-dev-register.sh`](../../scripts/canvas-dev-register.sh).

## How the launch is secured

See ADR-0008. In short: `state` and `nonce` are server-side, single use and expire after 10
minutes; the id_token is verified against Canvas's JWKS (RS256 only, cached, `kid` rotation)
and its `iss`, `aud`/`azp`, `exp`, `iat`, nonce, message type, LTI version, deployment id,
target link URI, resource link, roles and **course context** are checked. A replayed state,
nonce or token is refused. The browser that finishes the launch must prove it started it,
either with a short-lived cookie or, when third-party cookies are blocked, through Canvas
**platform storage** (`lti_storage_target=post_message_forwarding`, `lti.put_data` /
`lti.get_data`). The app session is a bearer token handed over in the URL fragment, so the
tool never needs a cookie after the launch.

## Verified Canvas behaviour (local install, 13 Nov 2026)

| Question (open-questions.md) | Finding |
|---|---|
| `iss` in launches | `https://canvas.instructure.com` (`config/security.yml` `lti_iss`) |
| Platform storage | Supported. Login initiation includes `lti_storage_target=post_message_forwarding` (omitted only in the mobile webview) |
| Throttling headers | `X-Rate-Limit-Remaining` (bucket, starts at 600) and `X-Request-Cost` on every response. Exhausted bucket: **HTTP 403** `403 Forbidden (Rate Limit Exceeded)`; 429 only if `request_throttle.send_429_response` is set |
| Scope strings | All ADR-0009 scopes exist except the profile scope, which is `url:GET\|/api/v1/users/:user_id/profile` |
| Pagination | RFC 8288 `Link` with `current`, `next`, `first`, `last` |
| Unreleased marks | A staff token sees the score of an unposted (manual post policy) grade, with `posted_at: null`. Only `posted_at` tells released from hidden |
| Excused | `workflow_state: graded`, `score: null`, `excused: true`, `posted_at` set. Never-graded rows have `excused: null` |
| Module completion | `GET /courses/:id/modules?student_id=` returns `state` (`locked`/`unlocked`/`started`/`completed`) and `completed_at` |
| Excused and modules | An excused assignment **satisfies** a `must_submit` requirement, so the module can be `completed` |
| Unposted grade and `must_submit` | A submitted-but-unposted assignment satisfies `must_submit`; that module can complete before marks are released |
| Unposted grade and `min_score` | **Not** satisfied while the grade is hidden (module stays `started`); completes once the grade is posted |
| NRPS | Client-credentials token issued correctly; the members call fails on this install because its domain has a port (see above). `rlid` support (per-member custom fields such as `canvas_user_id`) is from the Canvas source and is covered by mocked tests only |
