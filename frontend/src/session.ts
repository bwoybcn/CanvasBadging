// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Keeps a session alive while someone is working.
 *
 * A session token lasts 30 minutes by default. Without renewal, anyone who spent longer than
 * that on one task (the create-badge wizard, a long list award) lost what they had typed. While
 * the person is typing or clicking, and the token is past half its life, we swap it for a fresh
 * one (`POST /api/v1/session/renew`). An idle tab is left alone, so it still signs out on time,
 * and the server refuses to extend a session beyond its limit from the Canvas launch.
 *
 * The token the app was opened with stays the session's identity in React state (query keys
 * depend on it, and changing it would reload every screen). `currentToken` maps it to the
 * token to send now.
 */

export const STORAGE_KEY = "oc.session";

/** At most one renewal attempt in this long, however busy the person is. */
const RETRY_AFTER_MS = 30_000;

let live: { opened: string; current: string } | null = null;

/** The token to send for a session that was opened with `token`. */
export function currentToken(token: string | null): string | null {
  return token && live && live.opened === token ? live.current : token;
}

/** Issue and expiry times (in ms) of a session token, or null if it is not one of ours. */
export function tokenTimes(token: string): { issuedAt: number; expiresAt: number } | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as { iat?: unknown; exp?: unknown };
    if (typeof json.iat !== "number" || typeof json.exp !== "number") return null;
    return { issuedAt: json.iat * 1000, expiresAt: json.exp * 1000 };
  } catch {
    return null;
  }
}

/** True once a token is past half its life but has not yet expired. */
export function needsRenewal(token: string, now: number): boolean {
  const t = tokenTimes(token);
  if (!t) return false;
  const left = t.expiresAt - now;
  return left > 0 && left < (t.expiresAt - t.issuedAt) / 2;
}

function remember(token: string): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* storage blocked: the in-memory token still works for this page */
  }
}

/**
 * Asks for a fresh token. Resolves to "renewed", "ended" (the server will not extend this
 * session: stop asking) or "failed" (a network problem: try again later).
 */
export async function renewSession(opened: string): Promise<"renewed" | "ended" | "failed"> {
  const token = currentToken(opened);
  try {
    const res = await fetch("/api/v1/session/renew", {
      method: "POST",
      headers: { accept: "application/json", authorization: `Bearer ${token}` },
    });
    if (res.status === 401 || res.status === 404) return "ended";
    if (!res.ok) return "failed";
    const body = (await res.json()) as { token?: unknown };
    if (typeof body.token !== "string") return "failed";
    live = { opened, current: body.token };
    remember(body.token);
    return "renewed";
  } catch {
    return "failed";
  }
}

/**
 * Renews the session opened with `opened` whenever the person types or clicks and the token is
 * past half its life. Returns a function that stops watching.
 */
export function keepSessionAlive(opened: string, target: Window = window): () => void {
  let busy = false;
  let ended = false;
  let lastTry = 0;
  const onActivity = () => {
    const now = Date.now();
    if (busy || ended || now - lastTry < RETRY_AFTER_MS) return;
    const token = currentToken(opened);
    if (!token || !needsRenewal(token, now)) return;
    busy = true;
    lastTry = now;
    void renewSession(opened).then((outcome) => {
      ended = outcome === "ended";
      busy = false;
    });
  };
  target.addEventListener("keydown", onActivity, true);
  target.addEventListener("pointerdown", onActivity, true);
  return () => {
    target.removeEventListener("keydown", onActivity, true);
    target.removeEventListener("pointerdown", onActivity, true);
  };
}

/** Forgets any renewed token (sign-out, tests). */
export function resetSession(): void {
  live = null;
}
