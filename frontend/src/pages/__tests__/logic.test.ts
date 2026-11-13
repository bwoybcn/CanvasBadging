// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";

import { hasScoreRule, ruleProblems } from "../../components/RuleBuilder";
import { cellText } from "../CourseProgress";
import { stepProblems, toDraftFields } from "../CreateBadge";

const CATALOGUE = {
  categories: ["Completion", "Competency"],
  competency_categories: ["Competency", "Skills demonstration"],
  demonstration_kinds: {},
  achievement_types: ["Badge"],
  review_checklist: [],
};

function form(fields: Record<string, unknown> = {}) {
  return {
    course_id: "c-1",
    issuer_id: "iss-1",
    fields: {
      title: "T",
      short_description: "S",
      description: "",
      criteria_narrative: "C",
      category: "Completion",
      achievement_type: "Badge",
      demonstration_kind: "completing",
      evidence_description: "",
      validity_days: "",
      learning_outcomes: ["LO"],
      skills: [],
      asset_id: null,
      award_policy: "",
      ...fields,
    },
    rules: { mode: "ALL" as const, rules: [] },
  };
}

describe("rule checks", () => {
  it("requires at least one complete requirement", () => {
    expect(ruleProblems({ mode: "ALL", rules: [] })).toContain("Add at least one requirement.");
    expect(ruleProblems({ mode: "ALL", rules: [{ type: "module_completed", module_id: "" }] })).toEqual([
      "Requirement 1: choose a module.",
    ]);
    expect(ruleProblems({ mode: "ALL", rules: [{ type: "module_completed", module_id: "m1" }] })).toEqual([]);
  });

  it("checks score thresholds, groups and lecturer confirmations", () => {
    const problems = ruleProblems({
      mode: "ANY",
      rules: [
        { type: "assignment_score", assignment_id: "a1", operator: ">=", threshold_percent: 0 },
        { type: "group", mode: "ALL", rules: [{ type: "manual_approval", instructions: "" }] },
      ],
    });
    expect(problems).toEqual([
      "Requirement 1: the score must be above 0 and at most 100 per cent.",
      "Requirement 2: a group needs at least two requirements.",
      "Requirement 2.1: say what the lecturer is confirming.",
    ]);
  });

  it("detects score rules inside groups", () => {
    expect(
      hasScoreRule({
        mode: "ALL",
        rules: [
          {
            type: "group",
            mode: "ANY",
            rules: [
              { type: "module_completed", module_id: "m1" },
              { type: "assignment_score", assignment_id: "a1", operator: ">=", threshold_percent: 60 },
            ],
          },
        ],
      }),
    ).toBe(true);
    expect(hasScoreRule({ mode: "ALL", rules: [{ type: "module_completed", module_id: "m1" }] })).toBe(false);
  });
});

describe("wizard steps", () => {
  it("separates completion from competency", () => {
    expect(stepProblems(1, form(), CATALOGUE)).toEqual([]);
    const bad = stepProblems(1, form({ category: "Competency", demonstration_kind: "attending" }), CATALOGUE);
    expect(bad[0]).toMatch(/competency badge must be earned by demonstrating/i);
    expect(stepProblems(1, form({ category: "Competency", demonstration_kind: "assessed" }), CATALOGUE)).toEqual([]);
  });

  it("needs an issuer, outcomes and criteria", () => {
    expect(stepProblems(0, { ...form(), issuer_id: "" })).toEqual(["Choose the issuer that will award this badge."]);
    expect(stepProblems(2, form({ learning_outcomes: [" "], criteria_narrative: "" }))).toHaveLength(2);
  });

  it("sends blanks as unset and the institution default as null", () => {
    const out = toDraftFields(form({ learning_outcomes: ["A", " "], validity_days: "365" }).fields);
    expect(out.learning_outcomes).toEqual(["A"]);
    expect(out.validity_days).toBe(365);
    expect(out.description).toBeNull();
    expect(out.award_policy).toBeNull();
  });
});

describe("course progress wording", () => {
  it("never shows an uncertain result as met", () => {
    expect(cellText("unknown", null, ["AWAITING_RELEASE"])).toBe("Pending: mark not released");
    expect(cellText("unknown", null, ["DATA_STALE"])).toBe("Pending: Canvas data unavailable");
    expect(cellText("met", "awaiting_confirmation", [])).toBe("Awaiting your confirmation");
    expect(cellText(null, null, [])).toBe("Not evaluated yet");
  });
});
