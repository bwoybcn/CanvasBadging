// SPDX-License-Identifier: AGPL-3.0-or-later
/** Minimal API client. The session token lives in memory only (ADR-0015, no cookies). */

export interface Problem {
  status: number;
  code: string;
  title: string;
  detail?: string | null;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.title);
  }
}

export async function apiFetch<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body) headers.set("content-type", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let problem: Problem = { status: res.status, code: "HTTP_ERROR", title: res.statusText };
    try {
      problem = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(problem);
  }
  return res.json() as Promise<T>;
}

export interface DevUser {
  id: string;
  display_name: string | null;
  roles: string[];
}

export interface Me {
  id: string;
  display_name: string | null;
  institution: { id: string; slug: string; name: string; is_demo: boolean };
  memberships: { role: string; scope_type: string; scope_id: string; scope_name: string | null }[];
  session_method: string;
}
