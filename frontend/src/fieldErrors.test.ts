// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";

import { ApiError, problemLines, problemText } from "./api";
import { fieldLabel, fieldProblem, fieldProblems } from "./fieldErrors";

const err = (field: string, code: string, limits?: Record<string, number>, message = "Input is not valid") => ({
  field,
  code,
  message,
  ...(limits ? { limits } : {}),
});

describe("naming the field in a refused form", () => {
  it("uses the name the screen uses", () => {
    expect(fieldLabel("body.fields.short_description")).toBe("Short description");
    expect(fieldLabel("body.fields.criteria_narrative")).toBe("Criteria");
    expect(fieldLabel("body.primary_colour")).toBe("Main colour");
    expect(fieldLabel("body.alt_text")).toBe("Alternative text");
    expect(fieldLabel("body.justification")).toBe("Justification");
    expect(fieldLabel("query.learner")).toBe("Student name");
    expect(fieldLabel("body.issuer_id")).toBe("Issuer");
    expect(fieldLabel("body")).toBe("This form");
  });

  it("says which entry of a list is wrong, counting from one", () => {
    expect(fieldLabel("body.fields.learning_outcomes.2")).toBe("Learning outcome 3");
    expect(fieldLabel("body.fields.skills.0.name")).toBe("Skill 1 (name)");
    expect(fieldLabel("body.rules.1.assignment_score.threshold_percent")).toBe("Requirement 2 (minimum score)");
    expect(fieldLabel("body.identifiers.11")).toBe("Entry 12");
  });

  it("spells out a name it has not been told about", () => {
    expect(fieldLabel("body.retention_months")).toBe("Retention months");
    expect(fieldLabel("body.org_unit_id")).toBe("Org unit");
  });
});

describe("saying what to change", () => {
  it("gives the limit that was broken", () => {
    expect(fieldProblem(err("body.fields.short_description", "string_too_long", { max_length: 280 }))).toBe(
      "Short description is too long: use up to 280 characters.",
    );
    expect(fieldProblem(err("body.fields.description", "string_too_long", { max_length: 4000 }))).toBe(
      "Description is too long: use up to 4,000 characters.",
    );
    expect(fieldProblem(err("body.reason", "string_too_short", { min_length: 5 }))).toBe(
      "Reason is too short: use at least 5 characters.",
    );
    expect(fieldProblem(err("body.narrative", "string_too_short", { min_length: 1 }))).toBe(
      "Evidence description cannot be empty.",
    );
    expect(fieldProblem(err("body.fields.learning_outcomes", "too_long", { max_length: 12 }))).toBe(
      "Learning outcomes has too many entries: use up to 12.",
    );
    expect(fieldProblem(err("body.fields.validity_days", "less_than_equal", { le: 3650 }))).toBe(
      "Validity in days must be 3,650 or less.",
    );
    expect(fieldProblem(err("body.fields.validity_days", "greater_than_equal", { ge: 1 }))).toBe(
      "Validity in days must be 1 or more.",
    );
  });

  it("explains formats in everyday words", () => {
    expect(fieldProblem(err("body.primary_colour", "string_pattern_mismatch"))).toBe(
      "Main colour must be a colour code such as #1f4e79.",
    );
    expect(fieldProblem(err("body.evidence.0.url", "string_pattern_mismatch"))).toBe(
      "Evidence item 1 (web address) must be a web address that starts with https://.",
    );
    expect(fieldProblem(err("body.title", "missing"))).toBe("Title is needed.");
    expect(fieldProblem(err("body.issuer_id", "uuid_parsing"))).toBe("Issuer is not one of the choices offered.");
    expect(fieldProblem(err("body.fields.validity_days", "int_parsing"))).toBe("Validity in days must be a whole number.");
  });

  it("falls back to the server's wording for anything else", () => {
    expect(fieldProblem(err("body.slug", "value_error", undefined, "Value error, Use lowercase letters and hyphens."))).toBe(
      "Short name: use lowercase letters and hyphens.",
    );
  });

  it("lists each problem once and counts the overflow", () => {
    const same = err("body.title", "missing");
    expect(fieldProblems([same, same])).toEqual(["Title is needed."]);
    const many = Array.from({ length: 9 }, (_, i) => err(`body.fields.learning_outcomes.${i}`, "string_too_long", { max_length: 500 }));
    const lines = fieldProblems(many);
    expect(lines).toHaveLength(7);
    expect(lines[6]).toBe("And 3 more.");
  });
});

describe("what a refused request says", () => {
  const refused = new ApiError({
    status: 422,
    code: "VALIDATION_FAILED",
    title: "Request validation failed",
    detail: null,
    errors: [
      err("body.fields.short_description", "string_too_long", { max_length: 280 }),
      err("body.fields.title", "missing"),
    ],
  });

  it("names the fields instead of saying only that validation failed", () => {
    expect(problemLines(refused)).toEqual([
      "Short description is too long: use up to 280 characters.",
      "Title is needed.",
    ]);
    expect(problemText(refused)).not.toMatch(/validation failed/i);
  });

  it("keeps the server's explanation for every other refusal", () => {
    const incomplete = new ApiError({
      status: 400,
      code: "DRAFT_INCOMPLETE",
      title: "This badge is not ready to submit.",
      detail: "Add artwork; Add a requirement",
      errors: [err("asset_id", "missing")],
    });
    expect(problemLines(incomplete)).toEqual(["Add artwork; Add a requirement"]);
    const bare = new ApiError({ status: 422, code: "VALIDATION_FAILED", title: "Request validation failed" });
    expect(problemText(bare)).toBe("Request validation failed");
    expect(problemText(new Error("boom"))).toBe("Something went wrong. Please try again.");
  });
});

describe("an error with no words", () => {
  it("still says something, so a failed download is never silent", () => {
    const blank = new ApiError({ status: 500, code: "HTTP_ERROR", title: "" });
    expect(problemText(blank)).toBe("Something went wrong. Please try again.");
  });
});
