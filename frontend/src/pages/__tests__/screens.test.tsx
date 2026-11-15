// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
    expect(await screen.findByRole("heading", { name: "Create a badge" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 1 of 7: Course and issuer/ })).toBeInTheDocument();
    // Single course and single issuer are preselected, so step 1 passes.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: /Step 2 of 7: About the badge/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Give the badge a title.")).toBeInTheDocument();
    expect(screen.getByText("Choose a category.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 2 of 7/ })).toBeInTheDocument();
    // The problems are announced and take focus, so a screen-reader user hears why Next did nothing.
    const problems = screen.getByRole("alert");
    expect(problems).toHaveTextContent("Give the badge a title.");
    await waitFor(() => expect(problems).toHaveFocus());
    // Fixing a problem takes it off the list straight away.
    await userEvent.type(screen.getByLabelText("Title"), "Lab Safety");
    expect(screen.queryByText("Give the badge a title.")).toBeNull();
    expect(screen.getByText("Choose a category.")).toBeInTheDocument();
    // A step already done can be opened from the step list.
    await userEvent.click(screen.getByRole("button", { name: /1\. Course and issuer \(done\)/ }));
    expect(await screen.findByRole("heading", { name: /Step 1 of 7/ })).toBeInTheDocument();
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
    const base = definition();
    const withArt = { ...base, working_version: { ...base.working_version, asset_id: "a-1" as string | null } };
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": withArt,
      "PATCH /api/v1/achievements/d-1": withArt,
      "PUT /api/v1/achievements/d-1/rules": withArt,
    });
    renderAt("/badges/d-1/edit");
    expect(await screen.findByRole("heading", { name: "Edit badge" })).toBeInTheDocument();
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

  /** Fills "About the badge" on a new badge and leaves the wizard on that step. */
  async function startNewBadge() {
    renderAt("/badges/new");
    await screen.findByRole("heading", { name: /Step 1 of 7/ });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 2 of 7/ });
    await userEvent.type(screen.getByLabelText("Title"), "Lab Safety");
    await userEvent.type(screen.getByLabelText(/Short description/), "Works safely in a teaching lab.");
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(await screen.findByRole("option", { name: "Completion" }));
  }
  const writes = (calls: { method: string; url: string }[]) =>
    calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`);

  it("saves a new badge as a draft from step 2 and keeps saving on each Next", async () => {
    const draft = definition({ id: "d-new" });
    const calls = stubApi({
      ...COURSE_ROUTES,
      "POST /api/v1/achievements": draft,
      "PATCH /api/v1/achievements/d-new": draft,
    });
    await startNewBadge();
    // Nothing is saved for step 1 alone: there is nothing worth keeping yet.
    expect(writes(calls)).toEqual([]);
    expect(screen.getByTestId("draft-status")).toHaveTextContent(/saved as a draft each time you choose Next/);

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 3 of 7/ });
    expect(writes(calls)).toEqual(["POST /api/v1/achievements"]);
    const created = calls.find((c) => c.method === "POST")!.body as {
      issuer_id: string;
      course_id: string;
      rules: unknown;
      fields: Record<string, unknown>;
    };
    expect(created.issuer_id).toBe("iss-1");
    expect(created.course_id).toBe("c-1");
    expect(created.rules).toBeNull();
    expect(created.fields.title).toBe("Lab Safety");
    expect(screen.getByTestId("draft-status")).toHaveTextContent(/Draft saved at .* come back to it from Badges/);

    await userEvent.type(screen.getByLabelText("Learning outcome 1"), "Handle reagents safely");
    await userEvent.type(screen.getByLabelText(/Criteria/), "Pass the lab induction.");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 4 of 7/ });
    expect(writes(calls)).toEqual(["POST /api/v1/achievements", "PATCH /api/v1/achievements/d-new"]);
    const patch = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(patch.learning_outcomes).toEqual(["Handle reagents safely"]);
    expect(patch.criteria_narrative).toBe("Pass the lab induction.");

    // The artwork step cannot be passed without artwork, and says so; nothing more is saved.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/Add the badge artwork/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 4 of 7/ })).toBeInTheDocument();
    // Going back does not create a second draft.
    for (let back = 3; back >= 1; back--) {
      await userEvent.click(screen.getByRole("button", { name: "Back" }));
      await screen.findByRole("heading", { name: new RegExp(`Step ${back} of 7`) });
    }
    expect(writes(calls)).toHaveLength(2);
    // The draft belongs to its course and issuer now, so step 1 can no longer change them.
    expect(screen.getByText(/course, issuer and template are fixed now that your draft is saved/)).toBeInTheDocument();
  });

  it("stays on the step and says why when the draft cannot be saved", async () => {
    const calls = stubApi({
      ...COURSE_ROUTES,
      "POST /api/v1/achievements": () =>
        new Response(
          JSON.stringify({ status: 403, code: "FORBIDDEN", title: "Forbidden", detail: "You cannot create badges for this issuer." }),
          { status: 403, headers: { "content-type": "application/problem+json" } },
        ),
    });
    await startNewBadge();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("You cannot create badges for this issuer.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 2 of 7/ })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Lab Safety")).toBeInTheDocument();
    expect(writes(calls)).toEqual(["POST /api/v1/achievements"]);
  });

  it("names the field and the limit when the server refuses what was typed", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "POST /api/v1/achievements": () =>
        new Response(
          JSON.stringify({
            status: 422,
            code: "VALIDATION_FAILED",
            title: "Request validation failed",
            detail: null,
            errors: [
              {
                field: "body.fields.short_description",
                code: "string_too_long",
                message: "String should have at most 280 characters",
                limits: { max_length: 280 },
              },
              { field: "body.fields.category", code: "string_too_long", message: "x", limits: { max_length: 60 } },
            ],
          }),
          { status: 422, headers: { "content-type": "application/problem+json" } },
        ),
    });
    await startNewBadge();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/Short description is too long: use up to 280 characters\./)).toBeInTheDocument();
    expect(screen.getByText(/Category is too long: use up to 60 characters\./)).toBeInTheDocument();
    expect(screen.queryByText(/validation failed/i)).not.toBeInTheDocument();
  });

  it("limits the short description while it is typed and counts the characters", async () => {
    stubApi(COURSE_ROUTES);
    renderAt("/badges/new");
    await screen.findByRole("heading", { name: /Step 1 of 7/ });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const short = await screen.findByLabelText(/Short description/);
    expect(short).toHaveAttribute("maxlength", "280");
    expect(screen.getByLabelText(/Full description/)).toHaveAttribute("maxlength", "4000");
    await userEvent.type(short, "Works safely.");
    expect(screen.getByText("13 of 280 characters.")).toBeInTheDocument();
  });

  it("makes artwork from colours picked by eye, not typed as codes", async () => {
    const draft = definition({ id: "d-new" });
    const calls = stubApi({
      ...COURSE_ROUTES,
      "POST /api/v1/achievements": draft,
      "PATCH /api/v1/achievements/d-new": draft,
      "POST /api/v1/assets/from-template": {
        id: "a-1",
        media_type: "image/svg+xml",
        alt_text: "Green shield",
        data_url: "data:image/svg+xml;base64,AA==",
        warnings: [],
      },
    });
    await startNewBadge();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 3 of 7/ });
    await userEvent.type(screen.getByLabelText("Learning outcome 1"), "Handle reagents safely");
    await userEvent.type(screen.getByLabelText(/Criteria/), "Pass the lab induction.");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 4 of 7/ });
    const main = screen.getByLabelText("Main colour");
    expect(main).toHaveAttribute("type", "color");
    expect(screen.queryByLabelText(/\(hex\)/)).not.toBeInTheDocument();
    fireEvent.change(main, { target: { value: "#0b6e4f" } });
    fireEvent.change(screen.getByLabelText("Accent colour"), { target: { value: "#ffd166" } });
    await userEvent.type(screen.getByLabelText(/Alternative text/), "Green shield");
    await userEvent.click(screen.getByRole("button", { name: "Create artwork" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/assets/from-template")).toBe(true));
    const sent = calls.find((c) => c.url === "/api/v1/assets/from-template")!.body as Record<string, string>;
    expect(sent.primary_colour).toBe("#0b6e4f");
    expect(sent.secondary_colour).toBe("#ffd166");
  });

  it("tells the author their draft is safe when the session ends part-way through", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "POST /api/v1/achievements": definition({ id: "d-new" }),
      "PATCH /api/v1/achievements/d-new": () =>
        new Response(JSON.stringify({ status: 401, code: "SESSION_INVALID", title: "Your session has expired or is invalid" }), {
          status: 401,
          headers: { "content-type": "application/problem+json" },
        }),
    });
    await startNewBadge();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 3 of 7/ });
    await userEvent.type(screen.getByLabelText("Learning outcome 1"), "Handle reagents safely");
    await userEvent.type(screen.getByLabelText(/Criteria/), "Pass the lab induction.");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const alert = await screen.findByText(/Your session has ended/);
    expect(alert).toHaveTextContent(/Choose Badges in the Canvas course menu again/);
    expect(alert).toHaveTextContent(/saved as a draft: you will find it under Badges/);
    expect(screen.getByRole("heading", { name: /Step 3 of 7/ })).toBeInTheDocument();
  });

  it("keeps the step in hand when the author leaves the wizard", async () => {
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition(),
      "PATCH /api/v1/achievements/d-1": definition(),
    });
    const view = renderAt("/badges/d-1/edit");
    await screen.findByRole("heading", { name: "Edit badge" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const title = await screen.findByLabelText("Title");
    await userEvent.type(title, " (2027)");
    expect(writes(calls)).toEqual([]);
    view.unmount();
    await waitFor(() => expect(writes(calls)).toEqual(["PATCH /api/v1/achievements/d-1"]));
    expect((calls.find((c) => c.method === "PATCH")!.body as { title: string }).title).toBe(
      "Academic Writing Foundations (2027)",
    );
  });

  it("does not touch a draft that was opened and left unchanged", async () => {
    const calls = stubApi({ ...COURSE_ROUTES, "GET /api/v1/achievements/d-1": definition() });
    const view = renderAt("/badges/d-1/edit");
    await screen.findByRole("heading", { name: "Edit badge" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("heading", { name: /Step 2 of 7/ });
    view.unmount();
    await new Promise((r) => setTimeout(r, 20));
    expect(writes(calls)).toEqual([]);
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

  it("asks before archiving, and an archived badge can be restored", async () => {
    const live = definition({ state: "published", live_version_id: "v-1" });
    const archived = definition({ state: "archived", live_version_id: null });
    let current = live;
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": () => current,
      "POST /api/v1/achievements/d-1/archive": () => (current = archived),
      "POST /api/v1/achievements/d-1/restore": () => (current = live),
    });
    const posts = () => calls.filter((c) => c.method === "POST").map((c) => c.url);
    renderAt("/badges/d-1");
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    // The first press only explains: nothing is archived yet.
    expect(screen.getByRole("alert")).toHaveTextContent(/No new awards will be made .* Badges already issued stay valid/);
    expect(posts()).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Keep it live" }));
    expect(posts()).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    await userEvent.click(screen.getByRole("button", { name: "Archive this badge" }));
    expect((await screen.findAllByText(/Archived\. No new awards will be made/)).length).toBeGreaterThan(0);
    expect(posts()).toEqual(["/api/v1/achievements/d-1/archive"]);

    await userEvent.click(await screen.findByRole("button", { name: "Restore this badge" }));
    expect((await screen.findAllByText(/Restored\. The badge is live again/)).length).toBeGreaterThan(0);
    expect(posts()).toEqual(["/api/v1/achievements/d-1/archive", "/api/v1/achievements/d-1/restore"]);
    expect(await screen.findByRole("button", { name: "Archive" })).toBeInTheDocument();
  });

  it("says an archived badge can be restored when it is opened later", async () => {
    stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition({ state: "archived", live_version_id: null }),
    });
    renderAt("/badges/d-1");
    expect(await screen.findByText(/This badge is archived: no new awards are made/)).toHaveTextContent(
      /Restore it to start awarding again/,
    );
    expect(screen.getByRole("button", { name: "Restore this badge" })).toBeInTheDocument();
  });

  it("asks before deleting a draft", async () => {
    const calls = stubApi({
      ...COURSE_ROUTES,
      "GET /api/v1/achievements/d-1": definition(),
      "GET /api/v1/achievements": { items: [] },
      "DELETE /api/v1/achievements/d-1": new Response(null, { status: 204 }),
    });
    renderAt("/badges/d-1");
    await userEvent.click(await screen.findByRole("button", { name: "Delete draft" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/cannot be brought back/);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Delete this draft" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByRole("heading", { name: "Badges" })).toBeInTheDocument();
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
      "GET /api/v1/awards?status=awaiting_confirmation&limit=500": [
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
      "POST /api/v1/awards/dec-1/confirm": { id: "dec-1", status: "ready" },
    });
    renderAt("/awards");
    await userEvent.click(await screen.findByRole("button", { name: "Award to Sam Student" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/awards/dec-1/confirm")).toBe(true));
  });

  it("awards everyone waiting in one go, and says who was left and why", async () => {
    const waiting = (id: string, who: string, kind = "confirmed") => ({
      id,
      version_id: "v-1",
      definition_id: "d-1",
      badge_title: "Academic Writing Foundations",
      user_id: `u-${id}`,
      learner_name: who,
      kind,
      status: "awaiting_confirmation",
      justification: null,
      evidence: [],
      rejection_reason: null,
      decided_at: "2026-11-13T10:00:00Z",
      current_eligibility: null,
    });
    const calls = stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation&limit=500": [
        waiting("dec-1", "Sam Student"),
        waiting("dec-2", "Priya Patel"),
        waiting("dec-3", "Lee Wong"),
        waiting("dec-4", "Ana Silva", "manual"),
      ],
      "GET /api/v1/achievements?awardable=true": { items: [] },
      "POST /api/v1/awards/confirm-all": {
        confirmed: 2,
        left: 1,
        rows: [
          { id: "dec-1", learner_name: "Sam Student", badge_title: "Academic Writing Foundations", confirmed: true, code: null, message: null },
          { id: "dec-2", learner_name: "Priya Patel", badge_title: "Academic Writing Foundations", confirmed: true, code: null, message: null },
          { id: "dec-3", learner_name: "Lee Wong", badge_title: "Academic Writing Foundations", confirmed: false, code: "ELIGIBILITY_CHANGED", message: "The score is now below 70%." },
        ],
      },
    });
    renderAt("/awards");
    // The tab carries the count; the first press only asks.
    expect(await screen.findByRole("tab", { name: "Waiting to confirm (4)" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Award all 3" }));
    expect(screen.getByRole("alert")).toHaveTextContent("3 badges will be awarded now");
    expect(screen.getByRole("alert")).toHaveTextContent("1 manual award is not included");
    expect(calls.some((c) => c.url === "/api/v1/awards/confirm-all")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Yes, award all 3" }));
    expect(await screen.findByText(/2 badges awarded\. 1 award was not made and is still on the list/)).toBeInTheDocument();
    expect(screen.getByText("Lee Wong, Academic Writing Foundations: The score is now below 70%.")).toBeInTheDocument();
    // The manual award, which needs its justification read, is never sent with the rest.
    const body = calls.find((c) => c.url === "/api/v1/awards/confirm-all")!.body as { decision_ids: string[] };
    expect(body.decision_ids).toEqual(["dec-1", "dec-2", "dec-3"]);
  });

  it("finds a student by typing part of their name", async () => {
    // The badge has a new version in draft: its published version must still be awardable.
    const calls = stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation&limit=500": [],
      "GET /api/v1/achievements?awardable=true": {
        items: [{ id: "d-1", state: "draft", course_id: "c-1", course_title: "Writing", title: "Seminar Participation", category: "Participation", version_no: 1, live_version_id: "v-1", award_policy: "manual", updated_at: "2026-11-14T10:00:00Z" }],
      },
      "GET /api/v1/courses/c-1/progress": {
        course: { id: "c-1", title: "Writing" },
        badges: [],
        learners: [
          { user_id: "u-1", name: "Sam Student", cells: [] },
          { user_id: "u-2", name: "Priya Patel", cells: [] },
          { user_id: "u-3", name: "Samira Khan", cells: [] },
        ],
      },
      "POST /api/v1/awards/manual": { id: "dec-9", status: "ready" },
    });
    renderAt("/awards");
    await userEvent.click(await screen.findByRole("tab", { name: "One student" }));
    await userEvent.click(await screen.findByLabelText("Badge"));
    await userEvent.click(await screen.findByRole("option", { name: "Seminar Participation" }));
    await userEvent.type(screen.getByLabelText("Student"), "sami");
    expect(screen.queryByRole("option", { name: "Priya Patel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Sam Student" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: "Samira Khan" }));
    expect(screen.getByLabelText("Student")).toHaveValue("Samira Khan");
    await userEvent.type(screen.getByLabelText(/^Justification \(at least/), "Led two seminars, observed by the tutor.");
    await userEvent.click(screen.getByRole("button", { name: "Award badge" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/awards/manual")).toBe(true));
    expect((calls.find((c) => c.url === "/api/v1/awards/manual")!.body as { user_id: string }).user_id).toBe("u-3");
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
      "GET /api/v1/awards?status=awaiting_confirmation&limit=500": [],
      "GET /api/v1/achievements?awardable=true": {
        items: [{ id: "d-9", state: "published", course_id: "c-1", course_title: "WP Volunteers", title: "WP Volunteer", category: "Participation", version_no: 1, live_version_id: "v-9", award_policy: "manual", updated_at: "2026-11-14T10:00:00Z", can_award: true }],
      },
      "POST /api/v1/awards/bulk": preview,
      "POST /api/v1/courses/c-1/sync": { queued: true, job_id: "j-1" },
    });
    renderAt("/awards?tab=list");
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
    expect(screen.getByRole("button", { name: "Award to 1 student" })).toBeInTheDocument();
    // Entries nobody matched: offer a roster refresh, for students who joined today.
    await userEvent.click(screen.getByRole("button", { name: "Refresh the course from Canvas" }));
    expect(await screen.findByText("Refresh started. Check the list again in a minute.")).toBeInTheDocument();
  });

  it("says up front when list awards need a second member of staff", async () => {
    stubApi({
      "GET /api/v1/awards?status=awaiting_confirmation&limit=500": [],
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
    renderAt("/awards?tab=list");
    await userEvent.click(await screen.findByLabelText("Badge to award"));
    await userEvent.click(await screen.findByRole("option", { name: "WP Volunteer" }));
    await userEvent.type(screen.getByLabelText("Student ID numbers or emails"), "1, 2");
    await userEvent.type(screen.getByLabelText(/Justification for everyone/), "Logged ten hours of volunteering.");
    await userEvent.click(screen.getByRole("button", { name: "Check the list" }));
    expect(await screen.findByText(/A second member of staff must confirm each award/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record for 2 students" })).toBeInTheDocument();
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

  it("does not call a badge the student holds pending when staff awarded it by hand", async () => {
    stubApi({
      "GET /api/v1/learners/me": { ...STAFF_ME, memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "S" }] },
      "GET /api/v1/learners/me/achievements": [
          {
            definition_id: "d-2",
            version_id: "v-2",
            course: { id: "c-1", title: "Library Volunteers" },
            title: "Library Induction",
            short_description: "Completed the library induction.",
            category: "Completion",
            issuer: "University Library",
            image: { data_url: null, alt_text: null },
            award_policy: "lecturer_confirmed",
            status: "earned",
            outcome: "unknown",
            credential_id: "cred-2",
            progress: { completed: 0, total: 1, mode: "ALL" },
            requirements: [
              { rule_id: "r1", type: "manual_approval", description: "Passed the catalogue quiz.", outcome: "unknown", status: "pending", confirmed: false, label: "Awaiting confirmation by course staff", explanation_code: "AWAITING_STAFF", message: "", as_of: null },
            ],
          },
      ],
    });
    renderAt("/me/progress");
    const card = await screen.findByRole("region", { name: "Library Induction" });
    expect(within(card).getByText("Earned")).toBeInTheDocument();
    expect(within(card).getByText("You have this badge. Nothing more is needed from you.")).toBeInTheDocument();
    expect(within(card).queryByRole("heading", { name: "Pending" })).toBeNull();
    expect(within(card).queryByText(/0 of 1 confirmed/)).toBeNull();
    expect(within(card).queryByText(/Awaiting confirmation/)).toBeNull();
  });

  it("says a badge is waiting for staff when that is all that is missing", async () => {
    stubApi({
      "GET /api/v1/learners/me": { ...STAFF_ME, memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "S" }] },
      "GET /api/v1/learners/me/achievements": [
        {
          definition_id: "d-3",
          version_id: "v-3",
          course: { id: "c-1", title: "Library Volunteers" },
          title: "Volunteer hours",
          short_description: "Ten hours of volunteering.",
          category: "Participation",
          issuer: "University Library",
          image: { data_url: null, alt_text: null },
          award_policy: "manual",
          status: "pending",
          outcome: "unknown",
          credential_id: null,
          progress: { completed: 0, total: 1, mode: "ALL" },
          requirements: [
            { rule_id: "r1", type: "manual_approval", description: "Check the hours log", outcome: "unknown", status: "pending", confirmed: false, label: "Awaiting confirmation by course staff", explanation_code: "AWAITING_STAFF", message: "", as_of: null },
          ],
        },
      ],
    });
    renderAt("/me/progress");
    const card = await screen.findByRole("region", { name: "Volunteer hours" });
    expect(within(card).getByText("Waiting for staff to confirm")).toBeInTheDocument();
    expect(within(card).queryByText("Waiting for information")).toBeNull();
  });
});

describe("course activation", () => {
  it("lets a lecturer switch badges on from the launch page", async () => {
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
    const button = await screen.findByRole("button", { name: "Switch on badges for this course" });
    await userEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/activate"))).toBe(true));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Switch on badges for this course" })).toBeNull(),
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
    const history = await screen.findByRole("table", { name: /Badges issued in Study Skills 101/ });
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

describe("a Canvas administrator with no role here", () => {
  it("explains how to get administration access and who to ask", async () => {
    stubApi({
      "GET /api/v1/learners/me": {
        ...STAFF_ME,
        memberships: [],
        canvas_admin_without_access: true,
        institution_admins: ["Ada Admin", "Tess Teacher"],
      },
    });
    renderAt("/");
    const box = await screen.findByRole("region", { name: "Setting up badges" });
    expect(box).toHaveTextContent("You are a Canvas administrator");
    expect(box).toHaveTextContent("Ada Admin, Tess Teacher");
  });

  it("says who makes the first administrator when there is none", async () => {
    stubApi({
      "GET /api/v1/learners/me": { ...STAFF_ME, memberships: [], canvas_admin_without_access: true, institution_admins: [] },
    });
    renderAt("/");
    const box = await screen.findByRole("region", { name: "Setting up badges" });
    expect(box).toHaveTextContent("Whoever runs the Badges service makes the first one");
  });

  it("stays quiet for everyone else", async () => {
    stubApi({ "GET /api/v1/learners/me": STAFF_ME });
    renderAt("/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("region", { name: "Setting up badges" })).toBeNull();
  });
});

describe("staff pages reached by a student", () => {
  it.each(["/awards", "/badges/new", "/badges", "/reviews"])("%s says it is for course staff and draws no forms", async (path) => {
    stubApi({
      "GET /api/v1/learners/me": { ...STAFF_ME, memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "S" }] },
    });
    renderAt(path);
    expect(await screen.findByRole("heading", { name: "This page is for course staff" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "My badges" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
