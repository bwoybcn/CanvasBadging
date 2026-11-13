// SPDX-License-Identifier: AGPL-3.0-or-later
import { Alert, Flex, Heading, Spinner, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { apiFetch, problemText, type Me } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "./AppLink";

const STAFF = new Set(["lecturer", "course_admin", "dept_admin", "inst_admin", "issuer_manager"]);
const REVIEWERS = new Set(["dept_admin", "inst_admin"]);

/** The signed-in user's profile, shared by every page through the query cache. */
export function useMe() {
  const { token } = useAuth();
  return useQuery({ queryKey: ["me", token], queryFn: () => apiFetch<Me>("/api/v1/learners/me", token) });
}

export function roleFlags(me: Me | undefined) {
  const roles = new Set(me?.memberships.map((m) => m.role) ?? []);
  return {
    isStudent: roles.has("student"),
    isStaff: [...roles].some((r) => STAFF.has(r)),
    isReviewer: [...roles].some((r) => REVIEWERS.has(r)),
    isInstAdmin: roles.has("inst_admin"),
    isAdmin: roles.has("inst_admin") || roles.has("dept_admin"),
  };
}

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <AppLink to={to} margin="0 medium 0 0">
      {children}
    </AppLink>
  );
}

export function Nav() {
  const me = useMe();
  const f = roleFlags(me.data);
  return (
    <View as="nav" aria-label="OpenCredential" display="block" padding="small 0" borderWidth="0 0 small 0" margin="0 0 medium">
      <Flex wrap="wrap">
        <NavLink to="/">Home</NavLink>
        {f.isStudent && <NavLink to="/me/progress">My badges</NavLink>}
        {f.isStudent && <NavLink to="/me/credentials">My credentials</NavLink>}
        {f.isStaff && <NavLink to="/badges">Badges</NavLink>}
        {f.isStaff && <NavLink to="/awards">Awards to confirm</NavLink>}
        {f.isReviewer && <NavLink to="/reviews">Review queue</NavLink>}
        {f.isAdmin && <NavLink to="/admin">Administration</NavLink>}
      </Flex>
    </View>
  );
}

/** Standard page frame: navigation, a single h1 and the content. */
export function Page({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <View as="main" padding="medium large" maxWidth="72rem" margin="0 auto" display="block">
      <Nav />
      <Flex justifyItems="space-between" alignItems="center" wrap="wrap" margin="0 0 medium">
        <Heading level="h1">{title}</Heading>
        {actions}
      </Flex>
      {children}
    </View>
  );
}

export function Loading({ what }: { what: string }) {
  return <Spinner renderTitle={`Loading ${what}`} margin="large" />;
}

export function ErrorAlert({ error }: { error: unknown }) {
  return (
    <Alert variant="error" margin="small 0">
      {problemText(error)}
    </Alert>
  );
}
