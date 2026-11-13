// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface AuthState {
  token: string | null;
  setToken: (token: string | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children, initialToken = null }: { children: ReactNode; initialToken?: string | null }) {
  const [token, setToken] = useState<string | null>(initialToken);
  const value = useMemo(() => ({ token, setToken }), [token]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

const STORAGE_KEY = "oc.session";

/**
 * Session handed over by the LTI launch in the URL fragment (``/app/launch#session=…``).
 *
 * The fragment never reaches a server or a log. We read it once, remove it from the address bar
 * and keep the token in sessionStorage (per tab, and partitioned inside the Canvas iframe), so a
 * reload inside Canvas keeps working. No cookies are involved, which is what lets the tool run
 * when third-party cookies are blocked.
 */
export function readLaunchSession(loc: Location = window.location): string | null {
  const params = new URLSearchParams(loc.hash.replace(/^#/, ""));
  const fromLaunch = params.get("session");
  if (fromLaunch) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, fromLaunch);
    } catch {
      /* storage blocked: the in-memory token still works for this page */
    }
    window.history.replaceState(null, "", loc.pathname.replace(/\/launch\/?$/, "/") + loc.search);
    return fromLaunch;
  }
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function forgetSession(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

