# SPDX-License-Identifier: AGPL-3.0-or-later
"""LMS abstraction (spec §4.5). Canvas is the first implementation; others come later."""

from __future__ import annotations

from typing import Protocol


class LmsAdapter(Protocol):
    """Read-only access to an LMS, normalised into snapshot rows by the sync module.

    Methods are added by W3 as the Canvas adapter is built; keep LMS-specific types out of
    this protocol so other LMSs can implement it.
    """

    name: str
