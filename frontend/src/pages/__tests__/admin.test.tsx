// SPDX-License-Identifier: AGPL-3.0-or-later
/** W7 administration screens: issuer authorisation, revocation, erasure and access. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, renderAt, STAFF_ME, stubApi } from "../../test/util";

afterEach(() => vi.unstubAllGlobals());

const ADMIN_ME = {
  ...STAFF_ME,
  id: "u-adm",
  display_name: "Ada Admin",
  memberships: [{ role: "inst_admin", scope_type: "institution", scope_id: "i-1", scope_name: null }],
};

const DRAFT_ISSUER = {
  id: "iss-2",
  name: "Library Skills Centre",
  slug: "library",
  level: "department",
  org_unit_id: "ou-1",
  org_unit_name: "Library",
  url: null,
  email: null,
  description: null,
  did: null,
  status: "draft",
  authority_basis: null,
  authorised_at: null,
  may_issue: true,
  active_key: null,
  delegations: [],
};

const RECORD = {
  credential_id: "cr-1",
  definition_id: "d-1",
  course_id: "c-1",
  issued_at: "2026-11-13T10:00:00Z",
  badge_title: "Seminar Participation",
  version_no: 1,
  course_title: "Study Skills 101",
  course_code: null,
  issuer_name: "Library Skills Centre",
  learner_name: "Sam Student",
  award_kind: "manual",
  status: "active",
  revoked_at: null,
  revocation_reason: null,
};

function admin(routes: Record<string, unknown>) {
  return stubApi({
    "GET /api/v1/learners/me": ADMIN_ME,
    "GET /api/v1/admin/org-units": [
      {
        id: "ou-1",
        name: "Library",
        kind: "department",
        parent_id: null,
        may_issue: true,
        effective_may_issue: true,
        status: "active",
        manageable: true,
        review_policy: {},
        effective_review: {
          definition_review: "required",
          self_approval_allowed: false,
          manual_awards_require_second_approval: false,
          sources: { definition_review: null, self_approval_allowed: null, manual_awards_require_second_approval: null },
        },
      },
    ],
    "GET /api/v1/admin/courses": [],
    ...routes,
  });
}

describe("administration", () => {
  it("is not offered to lecturers", async () => {
    stubApi({});
    renderAt("/admin/issuers");
    expect(await screen.findByRole("heading", { name: "This page is for administrators" })).toBeInTheDocument();
    // No administration menu for someone who cannot use it.
    expect(screen.queryByRole("navigation", { name: "Administration sections" })).toBeNull();
  });

  it("authorises an issuer only with a recorded basis of authority", async () => {
    const calls = admin({
      "GET /api/v1/admin/issuers": [DRAFT_ISSUER],
      "POST /api/v1/admin/issuers/iss-2/authorise": { ...DRAFT_ISSUER, status: "active" },
    });
    renderAt("/admin/issuers");
    expect(await screen.findByText(/Not yet authorised/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Authorise Library Skills Centre" });
    expect(button).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText(/Basis of this issuer's authority/),
      "Senate resolution S/2026/14",
    );
    await userEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/authorise"))).toBe(true));
    const body = calls.find((c) => c.url.endsWith("/authorise"))!.body as { authority_basis: string };
    expect(body.authority_basis).toBe("Senate resolution S/2026/14");
  });

  const STEP = (key: string, title: string, done: boolean, detail: string, to: string | null) => ({
    key,
    title,
    done,
    detail,
    to,
    operator: to === null,
  });
  const SUMMARY = {
    issued: 0,
    revoked: 0,
    active: 0,
    pending_awards: { awaiting_confirmation: 0, awaiting_issuance: 0 },
    failed_issuance: { credentials_not_issued: 0, failed_jobs: 0 },
    by_course: [],
    by_badge: [],
    by_month: [],
  };

  it("shows the setup checklist with what is done, what is next and where to go", async () => {
    admin({
      "GET /api/v1/admin/reports/summary": SUMMARY,
      "GET /api/v1/admin/setup": {
        steps: [
          STEP("canvas", "Canvas is connected", true, "Connected to Canvas.", null),
          STEP("address", "The public address for checking badges is set", false, "Not set. This step is done by whoever runs the service, not on these pages.", null),
          STEP("area", "A faculty, department or service may issue badges", true, "Library may issue badges.", "/admin/areas"),
          STEP("issuer", "An issuer has been created", true, "Library Skills Centre.", "/admin/issuers"),
          STEP("authorised", "An issuer is authorised", false, "No issuer can sign badges yet.", "/admin/issuers"),
          STEP("delegated", "An authorised issuer is delegated to a department or course", false, "Authorise an issuer first.", "/admin/issuers"),
        ],
        done: 3,
        total: 6,
        complete: false,
        next: "address",
      },
    });
    renderAt("/admin");
    const setup = await screen.findByRole("region", { name: "Getting set up" });
    expect(within(setup).getByText(/3 of 6 done/)).toBeInTheDocument();
    const items = within(setup).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    // Each step says its state in words.
    expect(within(items[0]).getByText("Done")).toBeInTheDocument();
    expect(within(items[1]).getByText("Do this next")).toBeInTheDocument();
    expect(within(items[4]).getByText("To do")).toBeInTheDocument();
    expect(within(setup).getAllByText("Do this next")).toHaveLength(1);
    // A step the operator does has nowhere to send the administrator; the others link to their page.
    expect(within(items[1]).queryByText(/^Open /)).toBeNull();
    expect(within(items[4]).getByText("Open Issuers")).toBeInTheDocument();
    // A finished step needs no link.
    expect(within(items[2]).queryByText(/^Open /)).toBeNull();
  });

  it("folds the checklist away once everything is done", async () => {
    admin({
      "GET /api/v1/admin/reports/summary": SUMMARY,
      "GET /api/v1/admin/setup": {
        steps: [STEP("canvas", "Canvas is connected", true, "Connected to Canvas.", null)],
        done: 1,
        total: 1,
        complete: true,
        next: null,
      },
    });
    renderAt("/admin");
    const setup = await screen.findByRole("region", { name: "Getting set up" });
    expect(within(setup).getByText(/Setup is complete/)).toBeInTheDocument();
    expect(within(setup).queryByText("Canvas is connected")).toBeNull();
    await userEvent.click(within(setup).getByRole("button", { name: /Show the setup checklist/ }));
    expect(await within(setup).findByText("Canvas is connected")).toBeInTheDocument();
  });

  it("does not ask a department administrator to set the institution up", async () => {
    const calls = stubApi({
      "GET /api/v1/learners/me": { ...ADMIN_ME, memberships: [{ role: "dept_admin", scope_type: "org_unit", scope_id: "ou-1", scope_name: "Library" }] },
      "GET /api/v1/admin/reports/summary": SUMMARY,
    });
    renderAt("/admin");
    expect(await screen.findByRole("heading", { name: "Badges" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Getting set up" })).toBeNull();
    expect(calls.some((c) => c.url.endsWith("/admin/setup"))).toBe(false);
  });

  it("splits departments and roles into four pages, each in the menu, and keeps the old address working", async () => {
    admin({
      "GET /api/v1/admin/memberships": [],
      "GET /api/v1/admin/issuers": [],
      "GET /api/v1/admin/courses": [],
      "GET /api/v1/admin/canvas-accounts": [],
      "GET /api/v1/admin/review/published-without-review": [],
    });
    const view = renderAt("/admin/people");
    // The old address lands on the first of the new pages.
    expect(await screen.findByRole("heading", { level: 1, name: "Faculties and departments" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Your areas" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Canvas sub-accounts" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Who has which role" })).toBeNull();
    const menu = screen.getByRole("navigation", { name: "Administration sections" });
    for (const label of ["Faculties and departments", "Courses", "Staff roles", "Colleague review by area"]) {
      expect(within(menu).getByText(label)).toBeInTheDocument();
    }
    expect(within(menu).queryByText("Departments and roles")).toBeNull();
    view.unmount();
    for (const [path, title, section] of [
      ["/admin/courses", "Courses", "Where each course belongs"],
      ["/admin/roles", "Staff roles", "Who has which role"],
      ["/admin/review", "Colleague review by area", "Review rules for each area"],
    ]) {
      const page = renderAt(path);
      expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
      expect(await screen.findByRole("heading", { level: 2, name: section })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { level: 2, name: "Your areas" })).toBeNull();
      page.unmount();
    }
  });

  it("sets colleague review for one area and lists badges published without review", async () => {
    const calls = admin({
      "GET /api/v1/admin/memberships": [],
      "GET /api/v1/admin/issuers": [],
      "GET /api/v1/admin/review/published-without-review": [
        {
          id: "d-9",
          title: "WP Volunteer",
          version_no: 1,
          area: "Library",
          author: "Lee Lecturer",
          approved_at: "2026-11-14T10:00:00Z",
          reason: "Approved automatically: review is not required in this area.",
          review_now: "required",
        },
      ],
      "PATCH /api/v1/admin/org-units/ou-1": {},
    });
    renderAt("/admin/review");
    expect(await screen.findByText("WP Volunteer (version 1)")).toBeInTheDocument();
    await userEvent.click(await screen.findByLabelText("Badge review in Library"));
    await userEvent.click(await screen.findByRole("option", { name: "Not required" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      review_policy: { definition_review: "not_required" },
    });
  });

  it("links ticked Canvas sub-accounts to areas", async () => {
    const acct = (id: string, name: string, depth: number, extra: Record<string, unknown> = {}) => ({
      id,
      account_id: id,
      name,
      parent_account_id: null,
      depth,
      org_unit_id: null,
      org_unit_name: null,
      courses: 0,
      refreshed_at: "2026-11-14T17:00:00Z",
      ...extra,
    });
    const calls = admin({
      "GET /api/v1/admin/memberships": [],
      "GET /api/v1/admin/issuers": [],
      "GET /api/v1/admin/review/published-without-review": [],
      "GET /api/v1/admin/canvas-accounts": [
        acct("a1", "University of Liverpool", 0),
        acct("a2", "Faculty of Science", 1, { org_unit_id: "ou-9", org_unit_name: "Faculty of Science", courses: 4 }),
        acct("a4", "University Library", 1),
      ],
      "POST /api/v1/admin/canvas-accounts/refresh": { accounts: 3 },
      "POST /api/v1/admin/canvas-accounts/link": { linked: 1, courses_placed: 2 },
    });
    renderAt("/admin/areas");
    await userEvent.click(await screen.findByRole("button", { name: "Read sub-accounts from Canvas" }));
    expect(await screen.findByText("Read 3 accounts from Canvas.")).toBeInTheDocument();
    // The root account (the whole of Canvas) cannot be ticked.
    expect(screen.queryByLabelText("University of Liverpool")).toBeNull();
    // A linked sub-account shows its area and can be unlinked rather than ticked.
    expect(screen.getByRole("button", { name: "Unlink Faculty of Science" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Faculty of Science")).toBeNull();
    const linkButton = screen.getByRole("button", { name: /Link selected/ });
    expect(linkButton).toBeDisabled();
    await userEvent.click(screen.getByLabelText("University Library"));
    await userEvent.click(screen.getByLabelText("Kind for new areas"));
    await userEvent.click(await screen.findByRole("option", { name: "service" }));
    await userEvent.click(screen.getByRole("button", { name: "Link selected (1)" }));
    expect(await screen.findByText(/Linked 1 sub-account; 2 existing courses joined its area/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/canvas-accounts/link"))!.body).toEqual({
      items: [{ id: "a4", kind: "service" }],
    });
  });

  it("links a sub-account to an existing area and reassures on unlink", async () => {
    const calls = admin({
      "GET /api/v1/admin/memberships": [],
      "GET /api/v1/admin/issuers": [],
      "GET /api/v1/admin/review/published-without-review": [],
      "GET /api/v1/admin/canvas-accounts": [
        { id: "a4", account_id: "4", name: "Library", parent_account_id: "1", depth: 1, org_unit_id: null, org_unit_name: null, courses: 1, refreshed_at: "2026-11-14T17:00:00Z" },
        { id: "a5", account_id: "5", name: "Careers", parent_account_id: "1", depth: 1, org_unit_id: "ou-1", org_unit_name: "Library", courses: 0, refreshed_at: "2026-11-14T17:00:00Z" },
      ],
      "POST /api/v1/admin/canvas-accounts/link": { linked: 1, courses_placed: 0 },
      "DELETE /api/v1/admin/canvas-accounts/a5/link": new Response(null, { status: 204 }),
    });
    renderAt("/admin/areas");
    await userEvent.click(await screen.findByLabelText("Library"));
    await userEvent.click(screen.getByLabelText("Link to"));
    await userEvent.click(await screen.findByRole("option", { name: "Existing area: Library" }));
    await userEvent.click(screen.getByRole("button", { name: "Link selected (1)" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/canvas-accounts/link"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/canvas-accounts/link"))!.body).toEqual({
      items: [{ id: "a4", org_unit_id: "ou-1" }],
    });
    // Unlinking asks first, and says what it does and does not change.
    await userEvent.click(screen.getByRole("button", { name: "Unlink Careers" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/The area and the courses already in it stay as they are/);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Unlink it" }));
    expect(await screen.findByText("Unlinked Careers. Courses already in Library stay there.")).toBeInTheDocument();
  });

  it("asks before taking a role away from someone", async () => {
    const calls = admin({
      "GET /api/v1/admin/memberships": [
        {
          id: "m-1",
          user_id: "u-rev",
          user_name: "Rae Reviewer",
          role: "dept_admin",
          scope_type: "org_unit",
          scope_id: "ou-1",
          scope_name: "Library",
          source: "delegated",
          expires_at: null,
        },
      ],
      "GET /api/v1/admin/issuers": [],
      "GET /api/v1/admin/review/published-without-review": [],
      "GET /api/v1/admin/canvas-accounts": [],
      "DELETE /api/v1/admin/memberships/m-1": new Response(null, { status: 204 }),
    });
    renderAt("/admin/roles");
    await userEvent.click(await screen.findByRole("button", { name: /^Remove .* from Rae Reviewer$/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(/from Rae Reviewer for Library\? They lose what the role lets them do straight away/);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Keep the role" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /^Remove .* from Rae Reviewer$/ }));
    await userEvent.click(screen.getByRole("button", { name: "Remove the role" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/memberships/m-1"))).toBe(true));
  });

  it("saves brand colours chosen from a swatch and limits the fields to what the server accepts", async () => {
    const config = {
      id: "i-1",
      slug: "demo",
      name: "Demo University",
      description: null,
      website_url: null,
      branding: { primary_colour: "#212b58", secondary_colour: null },
      categories: ["Completion"],
      verification_host: null,
      linkedin_org_id: null,
      linkedin_org_name: null,
    };
    const calls = admin({
      "GET /api/v1/institutions/current": config,
      "PATCH /api/v1/institutions/current": config,
    });
    renderAt("/admin/institution");
    const brand = await screen.findByLabelText("Brand colour");
    expect(brand).toHaveAttribute("type", "color");
    expect(brand).toHaveValue("#212b58");
    expect(screen.getByLabelText("Institution name")).toHaveAttribute("maxlength", "200");
    expect(screen.getByLabelText("Description")).toHaveAttribute("maxlength", "4000");
    // The second colour is optional: nothing is sent until one is chosen.
    fireEvent.change(screen.getByLabelText("Second brand colour"), { target: { value: "#e8b10d" } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const sent = calls.find((c) => c.method === "PATCH")!.body as { branding: Record<string, string | null> };
    expect(sent.branding).toEqual({ primary_colour: "#212b58", secondary_colour: "#e8b10d" });
  });

  it("adds the ready-made templates for badges outside modules", async () => {
    const calls = admin({
      "GET /api/v1/admin/templates?include_archived=true": [
        { id: "t-0", name: "Seminar", description: null, org_unit_id: null, org_unit_name: null, status: "active", defaults: { title: "x", award_policy: "manual" } },
      ],
      "POST /api/v1/admin/templates/starters": [
        { id: "t-1", name: "Volunteering hours", description: null, org_unit_id: null, org_unit_name: null, status: "active", defaults: { title: "x", award_policy: "manual" } },
      ],
    });
    renderAt("/admin/templates");
    await userEvent.click(await screen.findByRole("button", { name: "Add ready-made templates" }));
    expect(await screen.findByText("Added 1 template.")).toBeInTheDocument();
    expect(screen.getByText("Pre-fills: title, how it is awarded")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/templates/starters"))).toBe(true);
  });

  it("revokes a credential with a reason and explains the effect", async () => {
    const calls = admin({
      "GET /api/v1/admin/revocation-requests": [],
      "GET /api/v1/admin/credentials": [RECORD],
      "POST /api/v1/credentials/cr-1/revoke": { credential_id: "cr-1", state: "revoked", changed: true, status_list_published: true },
    });
    renderAt("/admin/credentials");
    await userEvent.click(await screen.findByRole("button", { name: "Revoke Seminar Participation from Sam Student" }));
    expect(screen.getByText(/copies of the credential file the student has already downloaded/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Explanation/), "Awarded to the wrong student");
    await userEvent.click(screen.getByRole("button", { name: "Confirm revocation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      reason_code: "issued_in_error",
      reason_text: "Awarded to the wrong student",
    });
  });

  it("requires typing ERASE and says erasure does not revoke or unshare", async () => {
    const calls = admin({
      "GET /api/v1/admin/people?q=Sa": [{ id: "u-s1", display_name: "Sam Student" }],
      "GET /api/v1/institutions/current/retention": {
        snapshot_days_after_course_end: 365,
        evaluation_days: 730,
        failed_job_days: 90,
        audit_event_years: 7,
      },
      "POST /api/v1/admin/people/u-s1/erase": () =>
        json({ credentials_kept: 1, share_links_withdrawn: 1, awards_cancelled: 0 }),
    });
    renderAt("/admin/privacy");
    await userEvent.type(await screen.findByLabelText("Find a person by name"), "Sa");
    await userEvent.click(screen.getByLabelText("Person"));
    await userEvent.click(await screen.findByText("Sam Student"));
    expect(await screen.findByText(/does not revoke badges already issued/)).toBeInTheDocument();
    const erase = screen.getByRole("button", { name: "Erase this person's personal data" });
    expect(erase).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type ERASE to confirm"), "ERASE");
    await userEvent.click(erase);
    expect(await screen.findByText(/1 issued badges kept; 1 public share links taken down/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ confirm: "ERASE" });
  });
});
