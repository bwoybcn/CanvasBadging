// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError, problemText, SESSION_ENDED } from "./api";
import { currentToken, keepSessionAlive, needsRenewal, renewSession, resetSession, STORAGE_KEY, tokenTimes } from "./session";
import { json } from "./test/util";

const NOW = Date.UTC(2026, 10, 14, 12, 0, 0);

/** A token shaped like the server's (only the payload matters to the browser). */
function token(issuedMinutesAgo: number, lifetimeMinutes = 30, tag = "a"): string {
  const iat = Math.floor(NOW / 1000) - issuedMinutesAgo * 60;
  const payload = btoa(JSON.stringify({ sub: tag, iat, exp: iat + lifetimeMinutes * 60 }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `h.${payload}.sig-${tag}`;
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
});

afterEach(() => {
  resetSession();
  window.sessionStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("session token times", () => {
  it("reads issue and expiry from a token and ignores anything else", () => {
    const t = tokenTimes(token(10));
    expect(t).toEqual({ issuedAt: NOW - 10 * 60_000, expiresAt: NOW + 20 * 60_000 });
    expect(tokenTimes("not-a-token")).toBeNull();
    expect(tokenTimes("t0k")).toBeNull();
  });

  it("asks for renewal only in the second half of a token's life", () => {
    expect(needsRenewal(token(5), NOW)).toBe(false);
    expect(needsRenewal(token(16), NOW)).toBe(true);
    expect(needsRenewal(token(31), NOW)).toBe(false); // already expired: nothing to renew
    expect(needsRenewal("t0k", NOW)).toBe(false);
  });
});

describe("renewing a session", () => {
  it("sends the fresh token from then on, and keeps it for a reload", async () => {
    const opened = token(16);
    const fresh = token(0, 30, "b");
    const fetchMock = vi.fn(async (...[url]: [string, RequestInit?]) =>
      url === "/api/v1/session/renew" ? json({ token: fresh }) : json({ ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect(await renewSession(opened)).toBe("renewed");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("authorization")).toBe(`Bearer ${opened}`);
    expect(currentToken(opened)).toBe(fresh);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(fresh);

    // The rest of the app still holds the token it was opened with; requests carry the fresh one.
    await apiFetch("/api/v1/learners/me", opened);
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("authorization")).toBe(`Bearer ${fresh}`);
    // A different session is never mixed up with this one.
    expect(currentToken("another")).toBe("another");
  });

  it("stops when the server will not extend the session and retries after a network problem", async () => {
    const opened = token(16);
    vi.stubGlobal("fetch", vi.fn(async () => json({ status: 401, code: "SESSION_TOO_OLD", title: "x" }, 401)));
    expect(await renewSession(opened)).toBe("ended");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    expect(await renewSession(opened)).toBe("failed");
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 503)));
    expect(await renewSession(opened)).toBe("failed");
    expect(currentToken(opened)).toBe(opened);
  });
});

describe("keeping the session alive while someone works", () => {
  const flush = async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  };

  it("renews on typing or clicking once the token is past half its life, and not before", async () => {
    const opened = token(5);
    const fetchMock = vi.fn(async () => json({ token: token(0, 30, "b") }));
    vi.stubGlobal("fetch", fetchMock);
    const stop = keepSessionAlive(opened);

    window.dispatchEvent(new Event("keydown"));
    expect(fetchMock).not.toHaveBeenCalled();

    vi.setSystemTime(NOW + 11 * 60_000); // 16 minutes into a 30 minute token
    window.dispatchEvent(new Event("pointerdown"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flush();
    await vi.waitFor(() => expect(currentToken(opened)).not.toBe(opened));

    // The fresh token is new, so more activity does not ask again.
    vi.setSystemTime(NOW + 12 * 60_000);
    window.dispatchEvent(new Event("keydown"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    stop();
  });

  it("does nothing while the tab is idle, and stops listening when asked", async () => {
    const opened = token(20);
    const fetchMock = vi.fn(async () => json({ token: token(0, 30, "b") }));
    vi.stubGlobal("fetch", fetchMock);
    const stop = keepSessionAlive(opened);
    vi.setSystemTime(NOW + 5 * 60_000);
    expect(fetchMock).not.toHaveBeenCalled();
    stop();
    window.dispatchEvent(new Event("keydown"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asks at most once every 30 seconds after a failure and gives up once the session has ended", async () => {
    const opened = token(16);
    const failing = vi.fn(async () => json({}, 503));
    vi.stubGlobal("fetch", failing);
    const stop = keepSessionAlive(opened);
    window.dispatchEvent(new Event("keydown"));
    await flush();
    window.dispatchEvent(new Event("keydown"));
    expect(failing).toHaveBeenCalledTimes(1);

    vi.setSystemTime(NOW + 31_000);
    const refused = vi.fn(async () => json({ status: 401, code: "SESSION_TOO_OLD", title: "x" }, 401));
    vi.stubGlobal("fetch", refused);
    window.dispatchEvent(new Event("keydown"));
    await vi.waitFor(() => expect(refused).toHaveBeenCalledTimes(1));
    await flush();

    vi.setSystemTime(NOW + 120_000);
    window.dispatchEvent(new Event("keydown"));
    expect(refused).toHaveBeenCalledTimes(1);
    stop();
  });
});

describe("a session that has ended", () => {
  it("is explained in plain words, with what to do next", () => {
    const ended = new ApiError({ status: 401, code: "SESSION_INVALID", title: "Your session has expired or is invalid" });
    expect(problemText(ended)).toBe(SESSION_ENDED);
    expect(SESSION_ENDED).toMatch(/Open Micro-Credentials from the Canvas course menu again/);
  });
});
