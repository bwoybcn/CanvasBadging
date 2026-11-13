# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institutional governance (spec §10, §12.5, Phase 7): configuration, issuers, delegated
permissions, templates, revocation, records, audit, retention, personal data, reconciliation.

Every function takes a tenant-scoped session (row-level security) *and* checks the actor's
scope itself, so a missing check in a route cannot widen access across institutions.
"""
