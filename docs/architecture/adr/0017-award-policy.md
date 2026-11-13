# ADR-0017: Award policy for score-based badges

Date: 2026-11-13 · Status: Accepted

## Context
Spec §6.4–6.5 and open question 5. Gary (13 Nov 2026) asked for both options.

## Decision
Each badge has `award_policy` ∈ {`automatic`, `lecturer_confirmed`, `manual`}. Released grades (ADR-0010) can trigger automatic issuance when the badge says `automatic`. With `lecturer_confirmed`, a `met` evaluation lands in the lecturer's confirmation queue. The institution sets the default for badges with score rules (`score_rules_default_policy`, UoL default `lecturer_confirmed`) and may force confirmation (`score_rules_force_confirmation`). The policy in force is snapshotted into the published version, so later policy changes do not silently change existing badges.
