// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes, Providers } from "./App";
import { readLaunchSession } from "./auth";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const BASE_ME = {
  id: "u-9",
  display_name: "Tess Teacher",
  email: "oc.teacher@canvas.test",
  institution: { id: "i-1", slug: "uol-dev", name: "University of Liverpool (Development)", is_demo: false },
  memberships: [{ role: "lecturer", scope_type: "course", scope_id: "c-4", scope_name: "OpenCredential W3 Test Course" }],
  session_method: "lti",
  is_student: false,
  is_staff: true,
  is_admin: false,
  is_inst_admin: false,
  may_review: false,
  launch_course: {
    id: "c-4",
    title: "OpenCredential W3 Test Course",
    course_code: "OCW3",
    canvas_course_id: "4",
    status: "inactive",
    roles: ["lecturer"],
    view: "lecturer",
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe("LTI launch hand-over", () => {
  it("takes the session from the fragment, stores it per tab and cleans the address bar", () => {
    window.history.replaceState(null, "", "/app/launch#session=tok-123&course=c-4");
    expect(readLaunchSession()).toBe("tok-123");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/app/");
    expect(readLaunchSession()).toBe("tok-123"); // reload inside the Canvas iframe
  });

  it("shows the Canvas user and course context with the lecturer view", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(BASE_ME)));
    render(
      <Providers token="tok-123">
        <MemoryRouter initialEntries={["/launch"]}>
          <AppRoutes />
        </MemoryRouter>
      </Providers>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: /Welcome, Tess Teacher/ })).toBeInTheDocument();
    const ctx = await screen.findByTestId("course-context");
    expect(ctx).toHaveTextContent("OpenCredential W3 Test Course");
    expect(ctx).toHaveTextContent("Canvas course 4");
    expect(ctx).toHaveTextContent("Your role: Course staff");
    expect(ctx).toHaveTextContent("Course progress");
  });

  it("gives students the student view", async () => {
    const me = {
      ...BASE_ME,
      display_name: "Sam Student",
      launch_course: { ...BASE_ME.launch_course, roles: ["student"], view: "student" },
    };
    vi.stubGlobal("fetch", vi.fn(async () => json(me)));
    render(
      <Providers token="tok-1">
        <MemoryRouter initialEntries={["/"]}>
          <AppRoutes />
        </MemoryRouter>
      </Providers>,
    );
    const ctx = await screen.findByTestId("course-context");
    expect(ctx).toHaveTextContent("Your role: Student");
    expect(ctx).toHaveTextContent("Badges in my courses and my progress");
    expect(ctx).not.toHaveTextContent("Course progress");
  });

  function renderHome(launch_course: Record<string, unknown>, fetchImpl?: (url: string, init?: RequestInit) => Response) {
    const me = { ...BASE_ME, launch_course: { ...BASE_ME.launch_course, ...launch_course } };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
      String(url).endsWith("/learners/me") || !fetchImpl ? json(me) : fetchImpl(String(url), init),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <Providers token="tok-1">
        <MemoryRouter initialEntries={["/"]}>
          <AppRoutes />
        </MemoryRouter>
      </Providers>,
    );
    return fetchMock;
  }

  it("tells course staff when a course has ended and how long it is still read", async () => {
    renderHome({ status: "active", ended_at: "2026-06-30T00:00:00Z", read_until: "2026-08-29T00:00:00Z" });
    const ctx = await screen.findByTestId("course-context");
    expect(ctx).toHaveTextContent("This course ended in Canvas on 30 June 2026.");
    expect(ctx).toHaveTextContent("Canvas is still read until 29 August 2026, so marks released late still count.");
    expect(ctx).toHaveTextContent("Students keep the badges they earned.");
  });

  it("says an archived course has ended, and offers to switch it on again only through the server", async () => {
    const fetchMock = renderHome({ status: "archived", ended_at: "2026-06-30T00:00:00Z" }, (url) =>
      url.endsWith("/courses/c-4/activate")
        ? json(
            {
              code: "COURSE_ARCHIVED",
              title:
                "This course has ended in Canvas, so badges are switched off for it. If the course is opened again in Canvas, you can switch badges on here.",
              status: 409,
            },
            409,
          )
        : json([]),
    );
    const ctx = await screen.findByTestId("course-context");
    expect(ctx).toHaveTextContent("This course ended in Canvas on 30 June 2026, so it is no longer read");
    expect(ctx).not.toHaveTextContent("Badges are not switched on for this course yet");
    screen.getByRole("button", { name: "Switch badges on again" }).click();
    expect(await screen.findByText(/This course has ended in Canvas, so badges are switched off/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/activate") && init?.method === "POST")).toBe(true);
  });

  it("tells a student that an ended course awards no more badges", async () => {
    renderHome({ status: "archived", roles: ["student"], view: "student", ended_at: "2026-06-30T00:00:00Z" });
    const ctx = await screen.findByTestId("course-context");
    expect(ctx).toHaveTextContent("This course has ended");
    expect(ctx).toHaveTextContent("You keep the badges you earned.");
    expect(ctx).not.toHaveTextContent("have not switched on badges");
  });
});
