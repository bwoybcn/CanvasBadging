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
    expect(ctx).toHaveTextContent("My badges and progress");
    expect(ctx).not.toHaveTextContent("Course progress");
  });
});
