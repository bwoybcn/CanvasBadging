// SPDX-License-Identifier: AGPL-3.0-or-later
/** Builds an award rule set (spec §6): types A-F, ALL/ANY, one level of grouping. */
import {
  NumberInput,
  Alert,
  Button,
  Checkbox,
  CheckboxGroup,
  Flex,
  Heading,
  RadioInput,
  RadioInputGroup,
  SimpleSelect,
  Text,
  View,
} from "@instructure/ui";

import type {
  CanvasAssignment,
  CanvasModule,
  GroupRule,
  LeafRule,
  Rule,
  RuleSet,
} from "../api";
import { ChoiceSelect } from "./ChoiceSelect";
import { LimitedTextArea } from "./Fields";

export const RULE_TYPES: {
  value: LeafRule["type"];
  label: string;
  hint: string;
}[] = [
  {
    value: "module_completed",
    label: "Complete a module",
    hint: "Uses the module's completion requirements in Canvas.",
  },
  {
    value: "modules_completed",
    label: "Complete several modules",
    hint: "All the chosen modules must be complete.",
  },
  {
    value: "assignment_submitted",
    label: "Submit an assignment",
    hint: "A submission must exist; it does not need a mark.",
  },
  {
    value: "assignment_score",
    label: "Reach a score on an assignment",
    hint: "Only released (posted) marks count. Missing, excused or unreleased marks stay pending.",
  },
  {
    value: "manual_approval",
    label: "Staff confirm",
    hint: "A member of staff records that the student met this.",
  },
];

export function blankRule(type: LeafRule["type"]): LeafRule {
  switch (type) {
    case "module_completed":
      return { type, module_id: "" };
    case "modules_completed":
      return { type, module_ids: [] };
    case "assignment_submitted":
      return { type, assignment_id: "" };
    case "assignment_score":
      return { type, assignment_id: "", operator: ">=", threshold_percent: 70 };
    case "manual_approval":
      return { type, instructions: "" };
  }
}

/** Client-side checks mirroring the server schema, so problems show before saving. */
export function ruleProblems(rs: RuleSet): string[] {
  const out: string[] = [];
  if (rs.rules.length === 0) out.push("Add at least one requirement.");
  const leaf = (r: LeafRule, where: string) => {
    if (r.type === "module_completed" && !r.module_id)
      out.push(`${where}: choose a module.`);
    if (r.type === "modules_completed" && r.module_ids.length < 2)
      out.push(`${where}: choose at least two modules.`);
    if (
      (r.type === "assignment_submitted" || r.type === "assignment_score") &&
      !r.assignment_id
    )
      out.push(`${where}: choose an assignment.`);
    if (
      r.type === "assignment_score" &&
      !(r.threshold_percent > 0 && r.threshold_percent <= 100)
    )
      out.push(`${where}: the score must be above 0 and at most 100 per cent.`);
    if (
      r.type === "manual_approval" &&
      (r.instructions ?? "").trim().length < 5
    )
      out.push(`${where}: say what staff are confirming.`);
  };
  rs.rules.forEach((r, i) => {
    const where = `Requirement ${i + 1}`;
    if (r.type === "group") {
      if (r.rules.length < 2)
        out.push(`${where}: a group needs at least two requirements.`);
      r.rules.forEach((c, j) => leaf(c, `${where}.${j + 1}`));
    } else leaf(r, where);
  });
  return out;
}

/** How an unpublished Canvas item is named in the lists, so it is not chosen by mistake. */
const UNPUBLISHED = " (not published in Canvas)";
const nameOf = (x: { name: string; published: boolean }) =>
  x.published ? x.name : x.name + UNPUBLISHED;

function UnpublishedWarning({
  what,
  names,
}: {
  what: "module" | "assignment";
  names: string[];
}) {
  if (names.length === 0) return null;
  return (
    <Alert variant="warning" margin="small 0 0">
      {names.length === 1
        ? `The ${what} “${names[0]}” is`
        : `The ${what}s ${names.map((n) => `“${n}”`).join(", ")} are`}{" "}
      not published in Canvas. Students cannot see{" "}
      {names.length === 1 ? "it" : "them"}, so nobody can earn this badge until{" "}
      {names.length === 1 ? "it is" : "they are"} published in Canvas.
    </Alert>
  );
}

interface Sources {
  modules: CanvasModule[];
  assignments: CanvasAssignment[];
  /** Badges without a course can only use lecturer confirmation. */
  manualOnly?: boolean;
}

function LeafEditor({
  rule,
  onChange,
  sources,
  label,
}: {
  rule: LeafRule;
  onChange: (r: LeafRule) => void;
  sources: Sources;
  label: string;
}) {
  const modules = sources.modules.filter((m) => m.usable);
  const types = sources.manualOnly
    ? RULE_TYPES.filter((t) => t.value === "manual_approval")
    : RULE_TYPES;
  return (
    <View
      as="div"
      padding="small"
      borderWidth="small"
      borderRadius="medium"
      margin="0 0 small"
      display="block"
    >
      <SimpleSelect
        renderLabel={`${label}: type`}
        value={rule.type}
        onChange={(_e, { value }) =>
          onChange(blankRule(value as LeafRule["type"]))
        }
      >
        {types.map((t) => (
          <SimpleSelect.Option
            key={t.value}
            id={`${label}-${t.value}`}
            value={t.value}
          >
            {t.label}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <Text as="p" size="small" color="secondary">
        {RULE_TYPES.find((t) => t.value === rule.type)?.hint}
      </Text>
      {rule.type === "module_completed" && modules.length === 0 && (
        <Text as="p">
          This course has no modules with completion requirements in Canvas yet.
          Add requirements to a module in Canvas (Modules, then the
          module&rsquo;s settings), or choose another type of requirement.
        </Text>
      )}
      {rule.type === "module_completed" && modules.length > 0 && (
        <ChoiceSelect
          label="Module"
          value={rule.module_id}
          placeholder="Choose a module"
          options={modules.map((m) => ({ value: m.id, label: nameOf(m) }))}
          onChange={(value) => onChange({ ...rule, module_id: value })}
        />
      )}
      {rule.type === "modules_completed" && (
        <CheckboxGroup
          name={`${label}-modules`}
          description="Modules"
          value={rule.module_ids}
          onChange={(value) =>
            onChange({ ...rule, module_ids: value.map(String) })
          }
        >
          {modules.map((m) => (
            <Checkbox key={m.id} value={m.id} label={nameOf(m)} />
          ))}
        </CheckboxGroup>
      )}
      {(rule.type === "assignment_submitted" ||
        rule.type === "assignment_score") &&
        (sources.assignments.filter(
          (a) => rule.type === "assignment_submitted" || a.score_rules_allowed,
        ).length === 0 ? (
          <Text as="p">
            This course has no assignments that can be used here yet. Choose
            another type of requirement.
          </Text>
        ) : (
          <ChoiceSelect
            label="Assignment"
            value={rule.assignment_id}
            placeholder="Choose an assignment"
            options={sources.assignments
              .filter(
                (a) =>
                  rule.type === "assignment_submitted" || a.score_rules_allowed,
              )
              .map((a) => ({ value: a.id, label: nameOf(a) }))}
            onChange={(value) => onChange({ ...rule, assignment_id: value })}
          />
        ))}
      {(rule.type === "module_completed" ||
        rule.type === "modules_completed") && (
        <UnpublishedWarning
          what="module"
          names={modules
            .filter((m) => !m.published)
            .filter((m) =>
              rule.type === "module_completed"
                ? rule.module_id === m.id
                : rule.module_ids.includes(m.id),
            )
            .map((m) => m.name)}
        />
      )}
      {(rule.type === "assignment_submitted" ||
        rule.type === "assignment_score") && (
        <UnpublishedWarning
          what="assignment"
          names={sources.assignments
            .filter((a) => !a.published && a.id === rule.assignment_id)
            .map((a) => a.name)}
        />
      )}
      {rule.type === "assignment_score" && (
        <NumberInput
          renderLabel="Minimum score (per cent)"
          showArrows={false}
          width="10rem"
          value={String(rule.threshold_percent)}
          onChange={(_e, v) =>
            onChange({ ...rule, threshold_percent: Number(v) })
          }
        />
      )}
      {rule.type === "manual_approval" && (
        <LimitedTextArea
          maxLength={500}
          label="What a member of staff confirms"
          value={rule.instructions ?? ""}
          onChange={(e) => onChange({ ...rule, instructions: e.target.value })}
        />
      )}
    </View>
  );
}

export function RuleBuilder({
  value,
  onChange,
  sources,
}: {
  value: RuleSet;
  onChange: (rs: RuleSet) => void;
  sources: Sources;
}) {
  const setRule = (i: number, r: Rule) =>
    onChange({ ...value, rules: value.rules.map((x, j) => (j === i ? r : x)) });
  const remove = (i: number) =>
    onChange({ ...value, rules: value.rules.filter((_, j) => j !== i) });
  const firstType: LeafRule["type"] = sources.manualOnly
    ? "manual_approval"
    : "module_completed";
  const usable = sources.modules.filter((m) => m.usable).length;
  return (
    <View as="div" display="block">
      {!sources.manualOnly && sources.modules.length > 0 && usable === 0 && (
        <Alert variant="warning" margin="0 0 small">
          None of this course's modules have completion requirements in Canvas,
          so module rules cannot be used yet.
        </Alert>
      )}
      <RadioInputGroup
        name="rule-mode"
        description="A student earns this badge when they meet"
        value={value.mode}
        layout="columns"
        onChange={(_e, v) => onChange({ ...value, mode: v as RuleSet["mode"] })}
      >
        <RadioInput value="ALL" label="all of the requirements" />
        <RadioInput value="ANY" label="any one of the requirements" />
      </RadioInputGroup>
      <View as="div" margin="small 0" display="block">
        {value.rules.map((r, i) => {
          const label = `Requirement ${i + 1}`;
          if (r.type === "group") {
            const g = r as GroupRule;
            return (
              <View
                key={i}
                as="fieldset"
                padding="small"
                borderWidth="small"
                margin="0 0 small"
                display="block"
              >
                <Heading level="h4" as="legend">
                  {label}: a group
                </Heading>
                <RadioInputGroup
                  name={`group-${i}-mode`}
                  description="Within this group, meet"
                  value={g.mode}
                  layout="columns"
                  onChange={(_e, v) =>
                    setRule(i, { ...g, mode: v as GroupRule["mode"] })
                  }
                >
                  <RadioInput value="ALL" label="all" />
                  <RadioInput value="ANY" label="any one" />
                </RadioInputGroup>
                {g.rules.map((c, j) => (
                  <Flex key={j} alignItems="start" gap="small">
                    <Flex.Item shouldGrow shouldShrink>
                      <LeafEditor
                        rule={c}
                        label={`${label}.${j + 1}`}
                        sources={sources}
                        onChange={(nc) =>
                          setRule(i, {
                            ...g,
                            rules: g.rules.map((x, k) => (k === j ? nc : x)),
                          })
                        }
                      />
                    </Flex.Item>
                    {/* Its own item, so a long message beside it cannot squeeze the button. */}
                    <Flex.Item>
                      <Button
                        size="small"
                        onClick={() =>
                          setRule(i, {
                            ...g,
                            rules: g.rules.filter((_, k) => k !== j),
                          })
                        }
                      >
                        Remove {label}.{j + 1}
                      </Button>
                    </Flex.Item>
                  </Flex>
                ))}
                <Button
                  size="small"
                  interaction={g.rules.length >= 8 ? "disabled" : "enabled"}
                  onClick={() =>
                    setRule(i, {
                      ...g,
                      rules: [...g.rules, blankRule(firstType)],
                    })
                  }
                >
                  Add to group
                </Button>{" "}
                <Button size="small" onClick={() => remove(i)}>
                  Remove {label}
                </Button>
              </View>
            );
          }
          return (
            <Flex key={i} alignItems="start" gap="small">
              <Flex.Item shouldGrow shouldShrink>
                <LeafEditor
                  rule={r}
                  label={label}
                  sources={sources}
                  onChange={(nr) => setRule(i, nr)}
                />
              </Flex.Item>
              <Flex.Item>
                <Button size="small" onClick={() => remove(i)}>
                  Remove {label}
                </Button>
              </Flex.Item>
            </Flex>
          );
        })}
      </View>
      <Button
        interaction={value.rules.length >= 12 ? "disabled" : "enabled"}
        onClick={() =>
          onChange({ ...value, rules: [...value.rules, blankRule(firstType)] })
        }
      >
        Add requirement
      </Button>{" "}
      {!sources.manualOnly && (
        <Button
          interaction={value.rules.length >= 12 ? "disabled" : "enabled"}
          onClick={() =>
            onChange({
              ...value,
              rules: [
                ...value.rules,
                {
                  type: "group",
                  mode: "ANY",
                  rules: [blankRule(firstType), blankRule(firstType)],
                },
              ],
            })
          }
        >
          Add a group of alternatives
        </Button>
      )}
    </View>
  );
}

export function hasScoreRule(rs: RuleSet | null | undefined): boolean {
  if (!rs) return false;
  return rs.rules.some((r) =>
    r.type === "group"
      ? r.rules.some((c) => c.type === "assignment_score")
      : r.type === "assignment_score",
  );
}
