# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choose the :class:`LmsAdapter` for an integration.

The Canvas REST adapter is built in W3 and registers itself with :func:`register`. Until then,
real integrations report ``ADAPTER_UNAVAILABLE`` (so rules stay ``unknown``), and the seeded
development course is served by the in-memory demo adapter. Tests override with
:func:`override`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from opencredential.db.models import CanvasIntegration
from opencredential.integrations.base import LmsAdapter, LmsError
from opencredential.settings import get_settings

DEV_PLACEHOLDER_CLIENT_ID = "dev-placeholder-client-id"

Factory = Callable[[CanvasIntegration], LmsAdapter]
_factory: Factory | None = None
_override: LmsAdapter | None = None


class AdapterUnavailable(LmsError):
    code = "ADAPTER_UNAVAILABLE"


def register(factory: Factory) -> None:
    global _factory
    _factory = factory


@contextmanager
def override(adapter: LmsAdapter) -> Iterator[LmsAdapter]:
    global _override
    previous, _override = _override, adapter
    try:
        yield adapter
    finally:
        _override = previous


def get_adapter(integration: CanvasIntegration, course_ref: str) -> LmsAdapter:
    if _override is not None:
        return _override
    if integration.lti_client_id == DEV_PLACEHOLDER_CLIENT_ID and not get_settings().is_production:
        from opencredential.integrations.fake import passport_adapter
        from opencredential.seed import load_passport

        return passport_adapter(load_passport(), course_ref)
    if _factory is not None and integration.status == "active":
        return _factory(integration)
    raise AdapterUnavailable(
        "No Canvas connection is configured for this integration yet. An administrator needs "
        "to finish the Canvas setup."
    )
