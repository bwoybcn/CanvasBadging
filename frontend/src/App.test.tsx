// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes, Providers } from "./App";

const USERS = [
  { id: "u-1", display_name: "Amara Synthetic", roles: ["student"] },
  { id: "u-2", display_name: "Lee Lecturer", roles: ["lecturer"] },
];
const ME = {
  id: "u-1",
  display_name: "Amara Synthetic",
  institution: { id: "i-1", slug: "demo-university", name: "Demo University (development)", is_demo: true },
  memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "Academic Skills Passport (demo)" }],
  session_method: "dev",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderAt(path: string) {
  return render(
    <Providers>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("development sign-in", () => {
  it("redirects to dev sign-in without a session and signs in as a demo user", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith("/dev/institutions/")) return json(USERS);
      if (url === "/dev/login") {
        expect(JSON.parse(String(init?.body))).toEqual({ institution: "demo-university", user_id: "u-1" });
        return json({ token: "t0k" });
      }
      if (url === "/api/v1/learners/me") {
        expect(new Headers(init?.headers).get("authorization")).toBe("Bearer t0k");
        return json(ME);
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Development sign-in" })).toBeInTheDocument();
    expect(screen.getByText(/Every person listed here is synthetic/)).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: "Sign in as Amara Synthetic" }));

    expect(await screen.findByRole("heading", { name: "Welcome, Amara Synthetic" })).toBeInTheDocument();
    expect(screen.getByText("Student in Academic Skills Passport (demo)")).toBeInTheDocument();
    expect(screen.getByText(/demonstration data/)).toBeInTheDocument();
  });

  it("explains when development sign-in is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ status: 404, code: "NOT_FOUND", title: "x" }, 404)));
    renderAt("/dev-login");
    expect(await screen.findByText(/Development sign-in is not available/)).toBeInTheDocument();
  });
});
