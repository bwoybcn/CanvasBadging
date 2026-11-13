// SPDX-License-Identifier: AGPL-3.0-or-later
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { AppRoutes, Providers } from "../App";

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export const STAFF_ME = {
  id: "u-lec",
  display_name: "Lee Lecturer",
  institution: { id: "i-1", slug: "demo", name: "Demo University", is_demo: true },
  memberships: [{ role: "lecturer", scope_type: "course", scope_id: "c-1", scope_name: "Study Skills 101" }],
  session_method: "dev",
};

export interface Call {
  url: string;
  method: string;
  body: unknown;
}

/** Stubs fetch with a route table of "METHOD /path" -> response body (or function). */
export function stubApi(routes: Record<string, unknown | ((body: unknown) => unknown)>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const key = `${method} ${url}`;
      if (key in routes) {
        const r = routes[key];
        const out = typeof r === "function" ? (r as (b: unknown) => unknown)(body) : r;
        if (out instanceof Response) return out;
        return json(out);
      }
      if (method === "GET" && url === "/api/v1/learners/me") return json(STAFF_ME);
      return json({ status: 404, code: "NOT_FOUND", title: `No stub for ${key}` }, 404);
    }),
  );
  return calls;
}

export function renderAt(path: string) {
  return render(
    <Providers token="t0k">
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}
