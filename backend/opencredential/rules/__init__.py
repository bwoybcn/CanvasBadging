# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure rules engine over :class:`LearnerSnapshot` (no I/O; enforced by import-linter).

* :mod:`.schema`: the ``rules/v1`` rule set (types A-F, one level of nesting).
* :mod:`.snapshot`: the immutable learner data the engine may read.
* :mod:`.engine`: three-valued, deterministic, explainable evaluation.
"""

from opencredential.rules.engine import MET, NOT_MET, UNKNOWN, Evaluation, RuleResult, evaluate
from opencredential.rules.schema import SCHEMA_VERSION, RuleSet, describe, parse

__all__ = [
    "MET",
    "NOT_MET",
    "SCHEMA_VERSION",
    "UNKNOWN",
    "Evaluation",
    "RuleResult",
    "RuleSet",
    "describe",
    "evaluate",
    "parse",
]
