// SPDX-License-Identifier: AGPL-3.0-or-later
/** W7 administration screens: issuer authorisation, revocation, erasure and access. */
import { screen, waitFor } from "@testing-library/react";
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
    expect(await screen.findByText("Only administrators can use this page.")).toBeInTheDocument();
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
    renderAt("/admin/people");
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
    renderAt("/admin/people");
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
    renderAt("/admin/people");
    await userEvent.click(await screen.findByLabelText("Library"));
    await userEvent.click(screen.getByLabelText("Link to"));
    await userEvent.click(await screen.findByRole("option", { name: "Existing area: Library" }));
    await userEvent.click(screen.getByRole("button", { name: "Link selected (1)" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/canvas-accounts/link"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/canvas-accounts/link"))!.body).toEqual({
      items: [{ id: "a4", org_unit_id: "ou-1" }],
    });
    await userEvent.click(screen.getByRole("button", { name: "Unlink Careers" }));
    expect(await screen.findByText("Unlinked Careers. Courses already in Library stay there.")).toBeInTheDocument();
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
    expect(screen.getByText(/including copies the learner has already downloaded/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Explanation/), "Awarded to the wrong learner");
    await userEvent.click(screen.getByRole("button", { name: "Confirm revocation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      reason_code: "issued_in_error",
      reason_text: "Awarded to the wrong learner",
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
        json({ credentials_kept: 1, active_share_links: 1, awards_cancelled: 0 }),
    });
    renderAt("/admin/privacy");
    await userEvent.type(await screen.findByLabelText("Find a person by name"), "Sa");
    await userEvent.click(screen.getByLabelText("Person"));
    await userEvent.click(await screen.findByText("Sam Student"));
    expect(await screen.findByText(/does not revoke credentials already issued/)).toBeInTheDocument();
    const erase = screen.getByRole("button", { name: "Erase this person's personal data" });
    expect(erase).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type ERASE to confirm"), "ERASE");
    await userEvent.click(erase);
    expect(await screen.findByText(/1 issued credentials kept; 1 public share/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ confirm: "ERASE" });
  });
});
