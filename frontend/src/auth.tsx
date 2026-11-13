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
