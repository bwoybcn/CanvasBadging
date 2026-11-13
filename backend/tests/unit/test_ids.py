# SPDX-License-Identifier: AGPL-3.0-or-later
import time

from opencredential.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == "specified in RFC 4122"


def test_uuid7_embeds_current_time_and_sorts_by_time() -> None:
    before = time.time_ns() // 1_000_000
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert abs((first.int >> 80) - before) < 1000
    assert first < second


def test_uuid7_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000
