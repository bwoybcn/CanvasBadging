// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Turns the server's field-level validation errors into sentences a person can act on.
 *
 * A refused form used to say only "Request validation failed". The API already says which
 * field and why (`errors[]` on a 422); this names the field the way the screen does and says
 * what to change: "Short description is too long: use up to 280 characters."
 */

export interface FieldError {
  /** Where the problem is, for example `body.fields.short_description`. */
  field: string;
  /** Why, as a stable code (`string_too_long`, `missing`, …). */
  code: string;
  /** The server's own wording, used when we have nothing better. */
  message: string;
  /** The numbers behind the message (`max_length`, `min_length`, `ge`, `le`, …). */
  limits?: Record<string, number>;
}

/** Field names as the screens show them. Anything missing is spelled out from its name. */
const LABELS: Record<string, string> = {
  achievement_type: "Credential type",
  alt_text: "Alternative text",
  asset_id: "Artwork",
  assignment_id: "Assignment",
  authority_basis: "Basis of authority",
  award_policy: "Awarding",
  categories: "Categories",
  course_id: "Course",
  criteria_narrative: "Criteria",
  data_base64: "Image file",
  demonstration_kind: "How the achievement is demonstrated",
  email: "Email address",
  evidence_description: "Evidence",
  guidance: "Artwork guidance",
  identifiers: "Student ID numbers or emails",
  instructions: "What the lecturer confirms",
  issuer_id: "Issuer",
  label: "Short label",
  learning_outcomes: "Learning outcomes",
  linkedin_org_id: "LinkedIn organisation id",
  linkedin_org_name: "LinkedIn organisation name",
  module_id: "Module",
  module_ids: "Modules",
  narrative: "Evidence description",
  primary_colour: "Main colour",
  reason_text: "Explanation",
  rules: "Requirements",
  secondary_colour: "Accent colour",
  slug: "Short name",
  template: "Artwork style",
  threshold_percent: "Minimum score",
  url: "Web address",
  user_id: "Person",
  user_ids: "Learners",
  validity_days: "Validity in days",
  website_url: "Official website",
};

/** What one entry of a list is called. */
const ENTRY: Record<string, string> = {
  categories: "Category",
  evidence: "Evidence item",
  identifiers: "Entry",
  items: "Row",
  learning_outcomes: "Learning outcome",
  module_ids: "Module",
  rules: "Requirement",
  skills: "Skill",
};

const spellOut = (name: string) => {
  const words = name.replace(/_id$/, "").replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "This field";
};
const labelOf = (name: string) => LABELS[name] ?? spellOut(name);
const isIndex = (x: string) => /^\d+$/.test(x);

/** The on-screen name for a field path such as `body.fields.learning_outcomes.3`. */
export function fieldLabel(path: string): string {
  const parts = path.split(".").filter(Boolean);
  // Where the value came from, and wrappers that are not fields in their own right.
  while (parts.length > 1 && ["body", "query", "path", "header", "fields"].includes(parts[0])) parts.shift();
  if (!parts.length || (parts.length === 1 && parts[0] === "body")) return "This form";
  let at = -1;
  parts.forEach((p, i) => {
    if (isIndex(p) && i > 0 && !isIndex(parts[i - 1])) at = i;
  });
  if (at < 0) return labelOf(parts[parts.length - 1]);
  const list = parts[at - 1];
  const entry = `${ENTRY[list] ?? labelOf(list)} ${Number(parts[at]) + 1}`;
  const rest = parts.slice(at + 1).filter((p) => !isIndex(p));
  const inner = rest[rest.length - 1];
  return inner ? `${entry} (${labelOf(inner).toLowerCase()})` : entry;
}

const n = (x: number) => x.toLocaleString("en-GB");
const things = (count: number, one: string) => `${n(count)} ${one}${count === 1 ? "" : "s"}`;

/** What to change, as the end of a sentence that starts with the field's name. */
function whatToChange(e: FieldError): string {
  const l = e.limits ?? {};
  const name = e.field.split(".").pop() ?? "";
  switch (e.code) {
    case "missing":
      return "is needed";
    case "string_too_long":
      return l.max_length ? `is too long: use up to ${things(l.max_length, "character")}` : "is too long";
    case "string_too_short":
      if (!l.min_length || l.min_length <= 1) return "cannot be empty";
      return `is too short: use at least ${things(l.min_length, "character")}`;
    case "too_long":
      return l.max_length ? `has too many entries: use up to ${n(l.max_length)}` : "has too many entries";
    case "too_short":
      if (!l.min_length || l.min_length <= 1) return "needs at least one entry";
      return `needs at least ${n(l.min_length)} entries`;
    case "greater_than_equal":
      return l.ge === undefined ? "is too small" : `must be ${n(l.ge)} or more`;
    case "greater_than":
      return l.gt === undefined ? "is too small" : `must be more than ${n(l.gt)}`;
    case "less_than_equal":
      return l.le === undefined ? "is too big" : `must be ${n(l.le)} or less`;
    case "less_than":
      return l.lt === undefined ? "is too big" : `must be less than ${n(l.lt)}`;
    case "string_pattern_mismatch":
      if (/colour$/.test(name)) return "must be a colour code such as #1f4e79";
      if (/url$/.test(name)) return "must be a web address that starts with https://";
      return "is not in the form expected";
    case "int_parsing":
    case "int_type":
    case "int_from_float":
      return "must be a whole number";
    case "float_parsing":
    case "float_type":
      return "must be a number";
    case "uuid_parsing":
    case "uuid_type":
    case "enum":
    case "literal_error":
    case "union_tag_invalid":
      return "is not one of the choices offered";
    case "string_type":
    case "list_type":
    case "dict_type":
    case "model_attributes_type":
    case "bool_parsing":
    case "bool_type":
      return "is not in the form expected";
    case "date_from_datetime_parsing":
    case "date_parsing":
    case "date_type":
      return "must be a date such as 2026-11-14";
    case "datetime_parsing":
    case "datetime_from_date_parsing":
    case "datetime_type":
      return "must be a date and time";
    case "extra_forbidden":
      return "is not something this form accepts";
    default: {
      const said = e.message.replace(/^Value error,\s*/i, "").replace(/\.$/, "");
      return said ? `: ${said[0].toLowerCase()}${said.slice(1)}` : "is not valid";
    }
  }
}

/** One sentence for one refused field. */
export function fieldProblem(e: FieldError): string {
  const what = whatToChange(e);
  return `${fieldLabel(e.field)}${what.startsWith(":") ? "" : " "}${what}.`;
}

/** At most this many separate problems are listed; the rest are counted. */
const MOST = 6;

/** Every refused field as a sentence, without repeats. */
export function fieldProblems(errors: FieldError[]): string[] {
  const lines = [...new Set(errors.map(fieldProblem))];
  if (lines.length <= MOST) return lines;
  return [...lines.slice(0, MOST), `And ${lines.length - MOST} more.`];
}
