// SPDX-License-Identifier: AGPL-3.0-or-later
import { type APIRequestContext, type Page, expect } from "@playwright/test";

export const INSTITUTION = "demo-university";
export const STAFF = {
  admin: "Avery Admin",
  lecturer: "Lee Lecturer",
  reviewer: "Riley Reviewer",
} as const;

export interface DevUser {
  id: string;
  display_name: string;
  roles: string[];
}

export async function devUsers(request: APIRequestContext): Promise<DevUser[]> {
  const r = await request.get(`/dev/institutions/${INSTITUTION}/users`);
  expect(r.ok(), "dev sign-in must be enabled (OC_ENV=development and `oc seed`)").toBeTruthy();
  return (await r.json()) as DevUser[];
}

/** A bearer token for API set-up and checks, the same one the dev sign-in page obtains. */
export async function tokenFor(request: APIRequestContext, name: string): Promise<string> {
  const user = (await devUsers(request)).find((u) => u.display_name === name);
  if (!user) throw new Error(`no demo user called ${name}`);
  const r = await request.post("/dev/login", { data: { institution: INSTITUTION, user_id: user.id } });
  expect(r.ok()).toBeTruthy();
  return ((await r.json()) as { token: string }).token;
}

export class Api {
  constructor(
    readonly request: APIRequestContext,
    readonly token: string,
  ) {}

  static async as(request: APIRequestContext, name: string): Promise<Api> {
    return new Api(request, await tokenFor(request, name));
  }

  private h() {
    return { authorization: `Bearer ${this.token}` };
  }

  async get<T = unknown>(path: string): Promise<T> {
    const r = await this.request.get(path, { headers: this.h() });
    expect(r.status(), `${path}: ${await r.text()}`).toBe(200);
    return (await r.json()) as T;
  }

  async raw(method: string, path: string, data?: unknown) {
    return this.request.fetch(path, { method, headers: this.h(), data });
  }

  async post<T = unknown>(path: string, data?: unknown, expected = [200, 201, 202]): Promise<T> {
    const r = await this.raw("POST", path, data ?? {});
    expect(expected, `${path}: ${r.status()} ${await r.text()}`).toContain(r.status());
    return (await r.json()) as T;
  }
}

/**
 * Open the app the way a Canvas launch does: the session token arrives in the URL fragment of
 * /app/launch and is kept in sessionStorage for this tab (frontend/src/auth.tsx). The token
 * itself comes from the development sign-in endpoint, so no Canvas is needed.
 */
export async function signIn(page: Page, name: string): Promise<void> {
  const token = await tokenFor(page.request, name);
  await page.goto("/app/");
  await page.evaluate(() => sessionStorage.clear());
  await page.goto(`/app/launch#session=${token}`);
  await expect(page).not.toHaveURL(/dev-login|launch/);
}

/** Sign in by clicking through the development sign-in page, as a person would. */
export async function signInByClicking(page: Page, name: string): Promise<void> {
  await page.goto("/app/dev-login");
  await page.getByRole("button", { name: `Sign in as ${name}` }).click();
  await expect(page).not.toHaveURL(/dev-login/);
}

/** Poll until fn returns a truthy value (background jobs run in the worker). */
export async function eventually<T>(fn: () => Promise<T | null | undefined | false>, what: string, ms = 45_000): Promise<T> {
  const until = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > until) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 500));
  }
}

export interface Achievement {
  id: string;
  state: string;
  course_id: string;
  title: string;
  live_version_id: string | null;
  award_policy: string;
}

export interface Credential {
  id: string;
  name: string;
  status: string;
}
