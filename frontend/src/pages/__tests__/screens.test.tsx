// SPDX-License-Identifier: AGPL-3.0-or-later
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderAt, STAFF_ME, stubApi } from "../../test/util";

afterEach(() => vi.unstubAllGlobals());

const CATALOGUE = {
  categories: ["Completion", "Competency"],
  competency_categories: ["Competency"],
  demonstration_kinds: { completing: "Completing", assessed: "Achieving assessed proficiency" },
  achievement_types: ["Badge"],
  review_checklist: ["clarity", "level", "evidence", "alignment", "accessibility", "consistency", "terminology"],
};

function definition(over: Record<string, unknown> = {}) {
  return {
    id: "d-1",
    state: "draft",
    course_id: "c-1",
    issuer: { id: "iss-1", name: "Skills Centre", did: "did:key:z" },
    owner_user_id: "u-lec",
    award_policy: "automatic",
    live_version_id: null,
    working_version: {
      id: "v-1",
      version_no: 1,
      frozen: false,
      title: "Academic Writing Foundations",
      short_description: "Plans and writes a short academic text.",
      description: "",
      learning_outcomes: ["Structure an academic argument"],
      criteria_narrative: "Complete the writing module.",
      category: "Completion",
      achievement_type: "Badge",
      demonstration_kind: "completing",
      evidence_description: null,
      validity_days: null,
      skills: [],
      asset_id: null,
      award_policy: null,
      credit_claim_approved: false,
      content_hash: null,
      published_at: null,
    },
    rules: { mode: "ALL", rules: [{ id: "r-1", type: "module_completed", module_id: "m1" }] },
    readiness: [],
    reviews: [],
    can_edit: true,
    can_review: false,
    effective_award_policy: "automatic",
    review: {
      mode: "required",
      area_mode: "required",
      forced_by: null,
      set_by_org_unit_id: null,
      self_approval_allowed: false,
    },
    ...over,
  };
}

const COURSE_ROUTES = {
  "GET /api/v1/categories": CATALOGUE,
  "GET /api/v1/courses": [{ id: "c-1", title: "Study Skills 101", course_code: null, status: "active", roles: ["lecturer"] }],
  "GET /api/v1/courses/c-1/issuers": [{ id: "iss-1", name: "Skills Centre", did: "did:key:z" }],
  "GET /api/v1/courses/c-1/canvas/modules": {
    items: [
      { id: "m1", name: "Writing Foundations", published: true, has_requirements: true, requirement_type: "all", usable: true },
      { id: "m-noreq", name: "Welcome", published: true, has_requirements: false, requirement_type: null, usable: false },
    ],
    sync: { last_run: null, last_success_at: null },
  },
  "GET /api/v1/courses/c-1/canvas/assignments": { items: [], sync: { last_run: null, last_success_at: null } },
  "GET /api/v1/artwork-templates": [{ key: "shield", name: "Shield", description: "", licence: "CC0-1.0" }],
};

describe("Create Micro-Credential wizard", () => {
  it("blocks a step until its problems are fixed", async () => {
    stubApi(COURSE_ROUTES);
    renderAt("/badges/new");
    expect(await screen.findByRole("heading", { name: "Create micro-credential" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 1 of 7: Course and issuer/ })).toBeInTheDocument();
    // Single course and single issuer are preselected, so step 1 passes.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: /Step 2 of 7: About the badge/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Give the badge a title.")).toBeInTheDocument();
    expect(screen.getByText("Choose a category.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 2 of 7/ })).toBeInTheDocument();
  });

  it("starts from a badge template and asks the author to replace its placeholders", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/templates?course_id=c-1": [
        {
          id: "t-vol",
          name: "Volunteering hours",
          description: "Recognises volunteering hours.",
          org_unit_id: null,
          org_unit_name: null,
          status: "active",
          defaults: {
            title: "[Scheme name] Volunteer: [10] hours",
            short_description: "Completed [10] hours of volunteering.",
            category: "Completion",
            achievement_type: "Badge",
            demonstration_kind: "completing",
            award_policy: "manual",
          },
        },
      ],
    });
    renderAt("/badges/new");
    await userEvent.click(await screen.findByLabelText("Start from a badge template (optional)"));
    await userEvent.click(await screen.findByRole("option", { name: "Volunteering hours" }));
    expect(await screen.findByText(/Replace anything in \[square brackets\]/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByDisplayValue("[Scheme name] Volunteer: [10] hours")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Replace the template text in [square brackets] with your own details.")).toBeInTheDocument();
  });

  it("edits a draft through every step and saves fields and rules", async () => {
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition(),
      "PATCH /api/v1/achievements/d-1": definition(),
      "PUT /api/v1/achievements/d-1/rules": definition(),
    });
    renderAt("/badges/d-1/edit");
    expect(await screen.findByRole("heading", { name: "Edit micro-credential" })).toBeInTheDocument();
    await screen.findByDisplayValue("Academic Writing Foundations").catch(() => null);
    for (let i = 0; i < 6; i++) {
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      await screen.findByRole("heading", { name: new RegExp(`Step ${i + 2} of 7`) });
    }
    expect(screen.getByText(/Requirements: 1 \(all required\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(patch.title).toBe("Academic Writing Foundations");
    expect(patch.learning_outcomes).toEqual(["Structure an academic argument"]);
    expect(patch.award_policy).toBeNull();
    const put = calls.find((c) => c.method === "PUT")!.body as { mode: string; rules: { module_id: string }[] };
    expect(put.mode).toBe("ALL");
    expect(put.rules[0].module_id).toBe("m1");
  });
});

describe("badge page", () => {
  it("shows a preview that is clearly not a credential", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition(),
      "GET /api/v1/achievements/d-1/preview": {
        preview: true,
        notice: "PREVIEW: NOT ISSUED AND NOT VERIFIABLE",
        version_no: 1,
        state: "draft",
        artwork: { data_url: null, alt_text: null },
        achievement: {
          title: "Academic Writing Foundations",
          short_description: "s",
          description: "d",
          category: "Completion",
          achievement_type: "Badge",
          demonstration: "Completing",
          learning_outcomes: ["Structure an academic argument"],
          criteria: "Complete the writing module.",
          requirements: ["Complete the module “Writing Foundations”"],
          skills: [],
          validity_days: null,
        },
        issuer: { name: "Skills Centre", url: null, did: "did:key:z" },
      },
    });
    renderAt("/badges/d-1");
    expect(await screen.findByRole("heading", { name: "Academic Writing Foundations" })).toBeInTheDocument();
    expect(screen.getByText("Ready to submit for review.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Preview" }));
    expect(await screen.findByText("PREVIEW: NOT ISSUED AND NOT VERIFIABLE")).toBeInTheDocument();
    expect(screen.getByText(/Writing Foundations/, { selector: "li" })).toBeInTheDocument();
  });

  it("lets the author skip review where their area allows it", async () => {
    const authorDecides = {
      mode: "author_decides",
      area_mode: "author_decides",
      forced_by: null,
      set_by_org_unit_id: "ou-1",
      self_approval_allowed: false,
    };
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({ review: authorDecides }),
      "POST /api/v1/achievements/d-1/submit": { state: "approved", warnings: [] },
    });
    renderAt("/badges/d-1");
    expect(await screen.findByRole("button", { name: "Submit for review" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Publish without review/ }));
    await userEvent.click(screen.getByRole("button", { name: "Mark ready to publish" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/submit"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/submit"))!.body).toEqual({ review: "skip" });
  });

  it("explains why review cannot be skipped", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({
        review: {
          mode: "required",
          area_mode: "not_required",
          forced_by: "assessed",
          set_by_org_unit_id: null,
          self_approval_allowed: false,
        },
      }),
    });
    renderAt("/badges/d-1");
    expect(await screen.findByText(/assessed proficiency always need a colleague/)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("adds a colleague to a badge's team", async () => {
    const team = {
      enabled: true,
      members: [{ user_id: "u-lec", name: "Lee Lecturer", role: "owner" }],
      candidates: [{ user_id: "u-rob", name: "Robin Librarian" }],
      can_manage: true,
    };
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({ state: "published" }),
      "GET /api/v1/achievements/d-1/team": team,
      "PUT /api/v1/achievements/d-1/team/u-rob": {
        ...team,
        members: [...team.members, { user_id: "u-rob", name: "Robin Librarian", role: "awarder" }],
        candidates: [],
      },
    });
    renderAt("/badges/d-1");
    await userEvent.click(await screen.findByRole("tab", { name: "Team" }));
    expect(await screen.findByText(/Badge teams are on/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Add a colleague from this course"));
    await userEvent.click(await screen.findByRole("option", { name: "Robin Librarian" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to team" }));
    expect(await screen.findByText("Robin Librarian: Can award")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ role: "awarder" });
  });

  it("asks before removing a team member and can hand the badge over", async () => {
    const team = {
      enabled: true,
      members: [
        { user_id: "u-lec", name: "Lee Lecturer", role: "owner" },
        { user_id: "u-rob", name: null, role: "editor" },
      ],
      candidates: [],
      can_manage: true,
      can_transfer: true,
    };
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({ state: "published" }),
      "GET /api/v1/achievements/d-1/team": team,
      "DELETE /api/v1/achievements/d-1/team/u-rob": { ...team, members: [team.members[0]] },
      "PUT /api/v1/achievements/d-1/owner": {
        ...team,
        members: [
          { user_id: "u-rob", name: null, role: "owner" },
          { user_id: "u-lec", name: "Lee Lecturer", role: "editor" },
        ],
      },
    });
    renderAt("/badges/d-1");
    await userEvent.click(await screen.findByRole("tab", { name: "Team" }));
    // A colleague without a name never shows as a raw id.
    expect(await screen.findByText("A colleague without a name in Canvas: Can edit and award")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("New owner"));
    await userEvent.click(await screen.findByRole("option", { name: "A colleague without a name in Canvas" }));
    await userEvent.click(screen.getByRole("button", { name: "Hand over" }));
    expect(await screen.findByText("A colleague without a name in Canvas now owns this badge.")).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/v1/achievements/d-1/owner")!.body).toEqual({ user_id: "u-rob" });
    await userEvent.click(screen.getByRole("button", { name: "Remove Lee Lecturer from the team" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false); // nothing happens until confirmed
    expect(screen.getByRole("button", { name: "Keep" })).toBeInTheDocument();
  });

  it("lets a reviewer approve only after every checklist point", async () => {
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({ state: "in_review", can_edit: false, can_review: true }),
      "POST /api/v1/achievements/d-1/approve": definition({ state: "approved", can_edit: false }),
    });
    renderAt("/badges/d-1");
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    for (const box of screen.getAllByRole("checkbox")) await userEvent.click(box);
    expect(approve).toBeEnabled();
    await userEvent.click(approve);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/approve"))).toBe(true));
    const body = calls.find((c) => c.url.endsWith("/approve"))!.body as { checklist: Record<string, boolean> };
    expect(Object.values(body.checklist).filter(Boolean)).toHaveLength(7);
  });
});

describe("awards and progress", () => {
  it("confirms a lecturer-confirmed award", async () => {
    const calls = stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation": [
        {
          id: "dec-1",
          version_id: "v-1",
          definition_id: "d-1",
          badge_title: "Academic Writing Foundations",
          user_id: "u-s1",
          learner_name: "Sam Student",
          kind: "confirmed",
          status: "awaiting_confirmation",
          justification: null,
          evidence: [],
          rejection_reason: null,
          decided_at: "2026-11-13T10:00:00Z",
          current_eligibility: null,
        },
      ],
      "GET /api/v1/achievements?state=published": { items: [] },
      "POST /api/v1/awards/dec-1/confirm": { id: "dec-1", status: "ready" },
    });
    renderAt("/awards");
    await userEvent.click(await screen.findByRole("button", { name: "Award to Sam Student" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/awards/dec-1/confirm")).toBe(true));
  });

  it("previews a list award before awarding", async () => {
    const preview = {
      committed: false,
      second_approval: false,
      counts: { will_award: 1, not_found: 1 },
      rows: [
        { identifier: "201111111", status: "will_award", user_id: "u-s1", learner_name: "Sam Student", decision_id: null, message: null },
        { identifier: "123", status: "not_found", user_id: null, learner_name: null, decision_id: null, message: null },
      ],
    };
    const calls = stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation": [],
      "GET /api/v1/achievements?awardable=true": {
        items: [{ id: "d-9", state: "published", course_id: "c-1", course_title: "WP Volunteers", title: "WP Volunteer", category: "Participation", version_no: 1, live_version_id: "v-9", award_policy: "manual", updated_at: "2026-11-14T10:00:00Z", can_award: true }],
      },
      "POST /api/v1/awards/bulk": preview,
      "POST /api/v1/courses/c-1/sync": { queued: true, job_id: "j-1" },
    });
    renderAt("/awards");
    await userEvent.click(await screen.findByLabelText("Badge to award"));
    await userEvent.click(await screen.findByRole("option", { name: "WP Volunteer (WP Volunteers)" }));
    await userEvent.type(screen.getByLabelText("Student ID numbers or emails"), "201111111{enter}123");
    await userEvent.type(screen.getByLabelText(/Justification for everyone/), "Logged ten");
    expect(screen.getByText("10 of at least 20 characters.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Justification for everyone/), " hours of volunteering.");
    await userEvent.click(screen.getByRole("button", { name: "Check the list" }));
    expect(await screen.findByText("No student in this badge's course has this ID or email")).toBeInTheDocument();
    const body = calls.find((c) => c.url === "/api/v1/awards/bulk")!.body as { confirm: boolean; identifiers: string[] };
    expect(body.confirm).toBe(false);
    expect(body.identifiers).toEqual(["201111111\n123"]);
    expect(screen.getByRole("button", { name: "Award to 1 learner" })).toBeInTheDocument();
    // Entries nobody matched: offer a roster refresh, for students who joined today.
    await userEvent.click(screen.getByRole("button", { name: "Refresh the course from Canvas" }));
    expect(await screen.findByText("Refresh started. Check the list again in a minute.")).toBeInTheDocument();
  });

  it("says up front when list awards need a second member of staff", async () => {
    stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation": [],
      "GET /api/v1/achievements?awardable=true": {
        items: [{ id: "d-9", state: "published", course_id: "c-1", course_title: null, title: "WP Volunteer", category: "Participation", version_no: 1, live_version_id: "v-9", award_policy: "manual", updated_at: "2026-11-14T10:00:00Z", can_award: true }],
      },
      "POST /api/v1/awards/bulk": {
        committed: false,
        second_approval: true,
        counts: { will_award: 2 },
        rows: [
          { identifier: "1", status: "will_award", user_id: "u-1", learner_name: "A", decision_id: null, message: null },
          { identifier: "2", status: "will_award", user_id: "u-2", learner_name: "B", decision_id: null, message: null },
        ],
      },
    });
    renderAt("/awards");
    await userEvent.click(await screen.findByLabelText("Badge to award"));
    await userEvent.click(await screen.findByRole("option", { name: "WP Volunteer" }));
    await userEvent.type(screen.getByLabelText("Student ID numbers or emails"), "1, 2");
    await userEvent.type(screen.getByLabelText(/Justification for everyone/), "Logged ten hours of volunteering.");
    await userEvent.click(screen.getByRole("button", { name: "Check the list" }));
    expect(await screen.findByText(/A second member of staff must confirm each award/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record for 2 learners" })).toBeInTheDocument();
  });

  it("shows a student what is confirmed and what is pending", async () => {
    stubApi({
      "GET /api/v1/learners/me": { ...STAFF_ME, memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "S" }] },
      "GET /api/v1/learners/me/achievements": [
        {
          definition_id: "d-1",
          version_id: "v-1",
          course: { id: "c-1", title: "Study Skills 101" },
          title: "Academic Writing Foundations",
          short_description: "Plans and writes a short academic text.",
          category: "Completion",
          issuer: "Skills Centre",
          image: { data_url: null, alt_text: null },
          award_policy: "automatic",
          status: "pending",
          outcome: "unknown",
          credential_id: null,
          progress: { completed: 1, total: 2, mode: "ALL" },
          requirements: [
            { rule_id: "r1", type: "module_completed", description: "Complete Writing Foundations", outcome: "met", status: "complete", confirmed: true, label: "Complete", explanation_code: "MODULE_COMPLETED", message: "", as_of: null },
            { rule_id: "r2", type: "assignment_score", description: "Score at least 70% on Short essay", outcome: "unknown", status: "pending", confirmed: false, label: "Awaiting published result", explanation_code: "AWAITING_RELEASE", message: "", as_of: null },
          ],
        },
      ],
    });
    renderAt("/me/progress");
    const card = await screen.findByRole("region", { name: "Academic Writing Foundations" });
    expect(within(card).getByText("Waiting for information")).toBeInTheDocument();
    expect(within(card).getByRole("heading", { name: "Confirmed" })).toBeInTheDocument();
    expect(within(card).getByRole("heading", { name: "Pending" })).toBeInTheDocument();
    expect(within(card).getByText(/Awaiting published result/)).toBeInTheDocument();
    expect(within(card).getByText(/1 of 2 confirmed/)).toBeInTheDocument();
  });
});

describe("course activation", () => {
  it("lets a lecturer switch micro-credentials on from the launch page", async () => {
    let status = "inactive";
    const launchCourse = () => ({
      id: "c-1",
      title: "Study Skills 101",
      course_code: null,
      canvas_course_id: "4",
      status,
      roles: ["lecturer"],
      view: "lecturer",
    });
    const calls = stubApi({
      "GET /api/v1/learners/me": () => ({ ...STAFF_ME, launch_course: launchCourse() }),
      "POST /api/v1/courses/c-1/activate": () => {
        status = "active";
        return { id: "c-1", status, activated_at: "2026-11-13T16:00:00Z", sync_queued: true };
      },
    });
    renderAt("/");
    const button = await screen.findByRole("button", { name: "Switch on micro-credentials for this course" });
    await userEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/activate"))).toBe(true));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Switch on micro-credentials for this course" })).toBeNull(),
    );
  });
});

describe("course progress: history and revocation requests", () => {
  it("shows the course award history and lets staff ask for a revocation, without revoking anything", async () => {
    const calls = stubApi({
      "GET /api/v1/learners/me": STAFF_ME,
      "GET /api/v1/courses/c-1/progress": {
        course: { id: "c-1", title: "Study Skills 101" },
        badges: [
          { definition_id: "d-1", version_id: "v-1", title: "Seminar Skills", award_policy: "automatic", rules: ["Complete module"], source_flags: [] },
        ],
        learners: [
          {
            user_id: "u-s1",
            name: "Sam Student",
            cells: [
              { version_id: "v-1", outcome: "met", evaluated_at: null, codes: [], progress: null, decision_status: "issued", decision_id: "dec-1", credential_id: "cred-1" },
            ],
          },
        ],
      },
      "GET /api/v1/courses/c-1/sync": { last_run: null, last_success_at: null },
      "GET /api/v1/courses/c-1/credentials": [
        {
          credential_id: "cred-1",
          definition_id: "d-1",
          course_id: "c-1",
          issued_at: "2026-11-13T10:00:00Z",
          badge_title: "Seminar Skills",
          version_no: 1,
          course_title: "Study Skills 101",
          course_code: null,
          issuer_name: "Skills Centre",
          learner_name: "Sam Student",
          award_kind: "automatic",
          status: "active",
          revoked_at: null,
          revocation_reason: null,
        },
      ],
      "POST /api/v1/credentials/cred-1/revocation-requests": { id: "rr-1", status: "pending" },
    });
    renderAt("/courses/c-1/progress");
    const history = await screen.findByRole("table", { name: /Credentials issued in Study Skills 101/ });
    expect(within(history).getByText("Seminar Skills (version 1)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download as CSV" })).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: "Request revocation for Sam Student" }));
    const send = await screen.findByRole("button", { name: "Send request" });
    await userEvent.type(screen.getByLabelText(/Why should it be revoked/), "Issued to the wrong learner");
    await userEvent.click(send);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/revocation-requests"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/revocation-requests"))!.body).toEqual({ reason: "Issued to the wrong learner" });
    expect(await screen.findByText(/stays valid until they approve/)).toBeTruthy();
  });
});
