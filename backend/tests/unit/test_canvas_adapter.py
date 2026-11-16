# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas adapter against recorded-shape responses: pagination, throttling, retries, token
refresh and explicit unknown/inaccessible results (spec §4.3-4.5, ADR-0010).

Response bodies mirror what the local Canvas returned for the W3 test course (see
docs/integrations/canvas.md), including Canvas's 403 "Rate Limit Exceeded" throttle."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from opencredential.integrations.base import (
    LmsNotFound,
    LmsPermissionError,
    LmsTransientError,
)
from opencredential.integrations.canvas.adapter import CanvasAdapter
from opencredential.integrations.canvas.http import CanvasAuthError, TokenProvider, next_link
from opencredential.settings import Settings

BASE = "http://canvas.local"


def make(handler: Any, *, tokens: TokenProvider | None = None, **kw: Any) -> CanvasAdapter:
    sleeps: list[float] = []
    settings = Settings(canvas_max_retries=kw.pop("retries", 3))
    a = CanvasAdapter(
        settings,
        BASE,
        tokens or TokenProvider(lambda: "tok"),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    a.sleeps = sleeps  # type: ignore[attr-defined]
    return a


def page(data: Any, next_url: str | None = None, **headers: str) -> httpx.Response:
    h = {"x-rate-limit-remaining": "600.0", **headers}
    if next_url:
        h["link"] = f'<{next_url}>; rel="next", <{BASE}/x>; rel="first"'
    return httpx.Response(200, json=data, headers=h)


MODULES = [
    {
        "id": 19,
        "name": "Module 1 - Foundations",
        "published": True,
        "requirement_type": "all",
        "state": "completed",
        "completed_at": "2026-11-13T13:40:01Z",
    },
    {
        "id": 20,
        "name": "Module 2 - Applied",
        "published": True,
        "requirement_type": "all",
        "state": "locked",
        "completed_at": None,
    },
]


def test_modules_with_requirements_and_pagination() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer tok"
        path = req.url.path
        if path == "/api/v1/courses/4/modules":
            if req.url.params.get("page") == "2":
                return page([MODULES[1]])
            assert req.url.params["per_page"] == "100"
            return page([MODULES[0]], f"{BASE}/api/v1/courses/4/modules?page=2&per_page=100")
        if path == "/api/v1/courses/4/modules/19/items":
            return page([{"id": 1, "completion_requirement": {"type": "must_view"}}])
        if path == "/api/v1/courses/4/modules/20/items":
            return page([{"id": 2}])
        return httpx.Response(404)

    mods = make(handler).list_modules("4")
    assert [(m.module_id, m.has_requirements, m.requirement_type) for m in mods] == [
        ("19", True, "all"),
        ("20", False, None),
    ]


def test_module_progress_states() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["student_id"] == "5"
        return page(
            [
                {**MODULES[0], "state": "started", "completed_at": None},
                {**MODULES[1], "state": "locked"},
                {"id": 21, "name": "No row", "state": None},
            ]
        )

    prog = make(handler).list_module_progress("4", "5")
    assert [(p.module_id, p.state, p.completed_at) for p in prog] == [
        ("19", "started", None),
        ("20", "locked", None),
        ("21", "unlocked", None),
    ]


def test_submissions_released_unreleased_excused() -> None:
    subs = [
        {
            "user_id": 4,
            "assignment_id": 7,
            "workflow_state": "graded",
            "score": 8.0,
            "excused": False,
            "posted_at": "2026-11-13T13:39:58Z",
            "grade_matches_current_submission": True,
        },
        {
            "user_id": 4,
            "assignment_id": 8,
            "workflow_state": "graded",
            "score": 85.0,
            "excused": False,
            "posted_at": None,
            "grade_matches_current_submission": True,
        },
        {
            "user_id": 4,
            "assignment_id": 9,
            "workflow_state": "graded",
            "score": None,
            "excused": True,
            "posted_at": "2026-11-13T13:40:00Z",
        },
        {
            "user_id": 6,
            "assignment_id": 7,
            "workflow_state": "unsubmitted",
            "score": None,
            "excused": None,
            "posted_at": None,
        },
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        params = req.url.params
        assert params.get_list("student_ids[]") in (["4"], ["4", "6"])
        assert set(params.get_list("assignment_ids[]")) <= {"7", "8", "9"}
        return page([s for s in subs if str(s["user_id"]) in params.get_list("student_ids[]")])

    a = make(handler)
    got = {
        (s.lms_user_id, s.assignment_id): s
        for s in a.list_submissions("4", ["7", "8", "9"], ["4", "6"])
    }
    assert got[("4", "8")].score == 85.0 and got[("4", "8")].posted_at is None
    assert got[("4", "9")].excused is True
    assert got[("6", "7")].excused is False  # Canvas sends null
    assert a.get_grade("4", "7", "4").status == "released"
    assert a.get_grade("4", "7", "4").score == 8.0
    unreleased = a.get_grade("4", "8", "4")
    assert unreleased.status == "unreleased" and unreleased.score is None  # never leak it
    assert a.get_grade("4", "9", "4").status == "excused"


def test_students_are_batched() -> None:
    seen: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(len(req.url.params.get_list("student_ids[]")))
        return page([])

    make(handler).list_submissions("4", ["7"], [str(i) for i in range(1, 101)])
    assert seen == [40, 40, 20]


def test_canvas_throttle_403_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                403,
                text="403 Forbidden (Rate Limit Exceeded)\n",
                headers={"x-rate-limit-remaining": "0.0"},
            )
        return page([{"id": 7, "name": "A1", "points_possible": 10, "published": True}])

    a = make(handler)
    assert [x.assignment_id for x in a.list_assignments("4")] == ["7"]
    assert len(a.sleeps) >= 2  # type: ignore[attr-defined]


def test_throttle_exhausted_is_transient() -> None:
    a = make(lambda r: httpx.Response(429, headers={"retry-after": "1"}), retries=2)
    with pytest.raises(LmsTransientError):
        a.list_assignments("4")


def test_server_errors_and_timeouts_are_transient() -> None:
    with pytest.raises(LmsTransientError):
        make(lambda r: httpx.Response(503), retries=1).list_assignments("4")

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(LmsTransientError):
        make(boom, retries=1).list_assignments("4")


def test_partial_pagination_failure_raises_not_partial_list() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("page") == "2":
            return httpx.Response(500)
        return page(
            [{"id": 7, "name": "A1", "published": True}],
            f"{BASE}/api/v1/courses/4/assignments?page=2",
        )

    with pytest.raises(LmsTransientError):
        make(handler, retries=1).list_assignments("4")


def test_permission_and_not_found_are_explicit() -> None:
    with pytest.raises(LmsPermissionError):
        make(
            lambda r: httpx.Response(403, json={"errors": [{"message": "unauthorized"}]})
        ).list_assignments("4")
    with pytest.raises(LmsNotFound):
        make(lambda r: httpx.Response(404)).get_course("99999")
    with pytest.raises(LmsNotFound):
        make(lambda r: page([])).list_assignments("4/../../users")  # ids must be numeric


def test_401_refreshes_once_then_fails() -> None:
    tokens = {"current": "old", "refreshes": 0}

    def refresh() -> str:
        tokens["refreshes"] += 1
        tokens["current"] = "new"
        return "new"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers["authorization"] == "Bearer new":
            return page(
                {"id": 4, "name": "OC", "course_code": "OCW3", "workflow_state": "available"}
            )
        return httpx.Response(401, headers={"www-authenticate": 'Bearer realm="canvas-lms"'})

    a = make(handler, tokens=TokenProvider(lambda: tokens["current"], refresh))
    assert a.get_course("4").name == "OC" and tokens["refreshes"] == 1

    always_401 = make(lambda r: httpx.Response(401), tokens=TokenProvider(lambda: "x", lambda: "x"))
    with pytest.raises(CanvasAuthError):
        always_401.get_course("4")


def test_next_link_to_another_origin_is_refused() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return page([{"id": 1, "name": "A", "published": True}], "https://evil.example/steal")

    with pytest.raises(LmsPermissionError):
        make(handler).list_assignments("4")


def test_low_bucket_slows_down() -> None:
    a = make(lambda r: page([], **{"x-rate-limit-remaining": "10.0"}))
    a.list_assignments("4")
    assert a.sleeps and a.sleeps[0] > 0  # type: ignore[attr-defined]


def test_next_link_parsing() -> None:
    header = (
        '<http://c/api?page=1>; rel="current",<http://c/api?page=2>; rel="next",'
        '<http://c/api?page=9>; rel="last"'
    )
    assert next_link(header) == "http://c/api?page=2"
    assert next_link('<http://c/api?page=9>; rel="last"') is None
    assert next_link(None) is None


def test_url_rewrite_for_containers() -> None:
    from opencredential.integrations.canvas.http import rewrite_url

    s = Settings(canvas_url_rewrite="http://localhost:3000=http://host.docker.internal:3000")
    assert rewrite_url(s, "http://localhost:3000/api/v1/courses/4") == (
        "http://host.docker.internal:3000/api/v1/courses/4"
    )
    assert rewrite_url(s, "https://other/x") == "https://other/x"


# ---- has the course ended? (whole-product review, finding 2) ----------------------------------


def _course_state(body: dict[str, Any]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/courses/4"
        assert req.url.params.get_list("include[]") == ["concluded", "term"]
        return page({"id": 4, "name": "Course", **body})

    return make(handler).course_state("4")


def test_running_course_has_not_ended() -> None:
    state = _course_state(
        {"workflow_state": "available", "concluded": False, "end_at": "2099-06-30T00:00:00Z"}
    )
    assert state.concluded is False and state.ended_at is None


def test_course_past_its_term_end_has_ended_on_that_date() -> None:
    state = _course_state(
        {
            "workflow_state": "available",
            "concluded": True,
            "end_at": None,
            "term": {"id": 2, "end_at": "2026-06-30T00:00:00Z"},
        }
    )
    assert state.concluded is True
    assert state.ended_at is not None and state.ended_at.isoformat() == "2026-06-30T00:00:00+00:00"


def test_course_end_date_wins_over_the_term() -> None:
    state = _course_state(
        {
            "workflow_state": "available",
            "concluded": True,
            "end_at": "2026-05-01T00:00:00Z",
            "term": {"id": 2, "end_at": "2026-06-30T00:00:00Z"},
        }
    )
    assert state.ended_at is not None and state.ended_at.month == 5


def test_course_concluded_by_hand_has_no_date() -> None:
    # "Conclude this course" in Canvas settings: workflow_state completed, no end date.
    state = _course_state({"workflow_state": "completed", "end_at": None, "term": {"end_at": None}})
    assert state.concluded is True and state.ended_at is None


def test_course_end_is_still_seen_when_canvas_drops_include_parameters() -> None:
    """A developer key with enforced scopes and without "Allow Include Parameters" gets the
    plain course record: no ``concluded``, no term. The course's own dates still tell."""
    ended = _course_state(
        {
            "workflow_state": "available",
            "end_at": "2026-05-01T00:00:00Z",
            "restrict_enrollments_to_course_dates": True,
        }
    )
    assert ended.concluded is True and ended.ended_at is not None
    # An end date that the course does not use for participation does not end it.
    running = _course_state(
        {
            "workflow_state": "available",
            "end_at": "2026-05-01T00:00:00Z",
            "restrict_enrollments_to_course_dates": False,
        }
    )
    assert running.concluded is False
