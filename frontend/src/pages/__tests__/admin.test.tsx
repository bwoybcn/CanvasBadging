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

  it("adds the ready-made templates for badges outside modules", async () => {
    const calls = admin({
      "GET /api/v1/admin/templates": [],
      "POST /api/v1/admin/templates/starters": [
        { id: "t-1", name: "Volunteering hours", description: null, org_unit_id: null, org_unit_name: null, status: "active", defaults: {} },
      ],
    });
    renderAt("/admin/templates");
    await userEvent.click(await screen.findByRole("button", { name: "Add ready-made templates" }));
    expect(await screen.findByText("Added 1 template.")).toBeInTheDocument();
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
