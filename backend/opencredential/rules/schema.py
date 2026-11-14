# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule set schema ``rules/v1`` (spec §6.2-6.3, architecture.md §5).

A rule set is ``{"mode": "ALL"|"ANY", "rules": [...]}``. Each rule is one of the MVP types A-E,
or a ``group`` (type F) that combines leaf rules with its own ALL/ANY mode. Groups cannot contain
groups: one level of nesting keeps authoring understandable (§6.2 "limit nested complexity").

Every stored rule carries an ``id`` (the ``award_rules.id`` UUID) so explanations, manual
approvals and source-change flags can point at it. Rules submitted by the authoring UI may omit
``id``; the storage layer assigns one.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "rules/v1"
MAX_RULES = 12
MAX_GROUP_RULES = 8
MAX_MODULES_PER_RULE = 20

CanvasId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-:.]+$")]
Mode = Literal["ALL", "ANY"]


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=64)


class ModuleCompleted(_Rule):
    """Rule A: a Canvas module is reported complete for the learner."""

    type: Literal["module_completed"] = "module_completed"
    module_id: CanvasId


class ModulesCompleted(_Rule):
    """Rule B: every module in a collection is reported complete."""

    type: Literal["modules_completed"] = "modules_completed"
    module_ids: list[CanvasId] = Field(min_length=2, max_length=MAX_MODULES_PER_RULE)

    @field_validator("module_ids")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("module_ids must not repeat a module")
        return v


class AssignmentSubmitted(_Rule):
    """Rule C: a qualifying submission exists for a Canvas assignment."""

    type: Literal["assignment_submitted"] = "assignment_submitted"
    assignment_id: CanvasId


class AssignmentScore(_Rule):
    """Rule D: a released score at or above ``threshold_percent`` of points possible."""

    type: Literal["assignment_score"] = "assignment_score"
    assignment_id: CanvasId
    operator: Literal[">="] = ">="
    threshold_percent: float = Field(gt=0, le=100)


class ManualApproval(_Rule):
    """Rule E: an authorised lecturer or administrator confirms completion for the learner."""

    type: Literal["manual_approval"] = "manual_approval"
    instructions: str | None = Field(default=None, max_length=500)


LeafRule = Annotated[
    ModuleCompleted | ModulesCompleted | AssignmentSubmitted | AssignmentScore | ManualApproval,
    Field(discriminator="type"),
]


class Group(_Rule):
    """Rule F (nested): a combination of leaf rules with its own mode."""

    type: Literal["group"] = "group"
    mode: Mode
    rules: list[LeafRule] = Field(min_length=2, max_length=MAX_GROUP_RULES)


AnyRule = Annotated[
    ModuleCompleted
    | ModulesCompleted
    | AssignmentSubmitted
    | AssignmentScore
    | ManualApproval
    | Group,
    Field(discriminator="type"),
]


class RuleSet(BaseModel):
    """Rule F (top level): ALL or ANY of up to :data:`MAX_RULES` rules."""

    model_config = ConfigDict(extra="forbid")
    mode: Mode
    rules: list[AnyRule] = Field(min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _ids_unique(self) -> RuleSet:
        ids = [r.id for r in self.iter_rules() if r.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self

    def iter_rules(self) -> list[Any]:
        """All rules, groups included, depth first."""
        out: list[Any] = []
        for r in self.rules:
            out.append(r)
            if isinstance(r, Group):
                out.extend(r.rules)
        return out

    def leaves(self) -> list[Any]:
        return [r for r in self.iter_rules() if not isinstance(r, Group)]

    def has_score_rule(self) -> bool:
        return any(isinstance(r, AssignmentScore) for r in self.leaves())

    def module_ids(self) -> set[str]:
        out: set[str] = set()
        for r in self.leaves():
            if isinstance(r, ModuleCompleted):
                out.add(r.module_id)
            elif isinstance(r, ModulesCompleted):
                out.update(r.module_ids)
        return out

    def assignment_ids(self) -> set[str]:
        return {
            r.assignment_id
            for r in self.leaves()
            if isinstance(r, AssignmentSubmitted | AssignmentScore)
        }


def parse(data: dict[str, Any]) -> RuleSet:
    return RuleSet.model_validate(data)


def describe(rule: Any, names: dict[str, str] | None = None) -> str:
    """Plain-language description of a rule, for progress displays and previews."""
    names = names or {}

    def n(i: str, kind: str) -> str:
        return names.get(i) or f"{kind} {i}"

    if isinstance(rule, ModuleCompleted):
        return f"Complete the module “{n(rule.module_id, 'module')}”"
    if isinstance(rule, ModulesCompleted):
        listed = ", ".join(f"“{n(i, 'module')}”" for i in rule.module_ids)
        return f"Complete all of these modules: {listed}"
    if isinstance(rule, AssignmentSubmitted):
        return f"Submit “{n(rule.assignment_id, 'assignment')}”"
    if isinstance(rule, AssignmentScore):
        pct = f"{rule.threshold_percent:g}"
        return f"Score at least {pct}% in “{n(rule.assignment_id, 'assignment')}” (released mark)"
    if isinstance(rule, ManualApproval):
        return "Confirmation by course staff" + (
            f": {rule.instructions}" if rule.instructions else ""
        )
    if isinstance(rule, Group):
        joiner = " and " if rule.mode == "ALL" else " or "
        return "(" + joiner.join(describe(r, names) for r in rule.rules) + ")"
    raise TypeError(type(rule))
