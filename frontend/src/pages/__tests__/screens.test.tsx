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
