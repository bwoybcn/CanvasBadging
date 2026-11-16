// SPDX-License-Identifier: AGPL-3.0-or-later
import { Alert, Flex, Heading, List, Spinner, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect } from "react";

import { ApiError, apiFetch, problemLines, SESSION_ENDED, type Me } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "./AppLink";

/** The signed-in user's profile, shared by every page through the query cache. */
export function useMe() {
  const { token } = useAuth();
  return useQuery({ queryKey: ["me", token], queryFn: () => apiFetch<Me>("/api/v1/learners/me", token) });
}

/** What the signed-in person may see. The server works each answer out from the person's
 * roles and the institution's policy (authz/roles.py); the screens keep no role list of their
 * own, and until the profile has loaded they show nothing that needs a role. */
export function roleFlags(me: Me | undefined) {
  return {
    isStudent: me?.is_student ?? false,
    isStaff: me?.is_staff ?? false,
    isReviewer: me?.may_review ?? false,
    isInstAdmin: me?.is_inst_admin ?? false,
    isAdmin: me?.is_admin ?? false,
  };
}

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  // Padding keeps each target at least 24 by 24 CSS pixels when the bar wraps on a phone
  // (WCAG 2.2 SC 2.5.8, found by the W8 axe run on the mobile viewport).
  return (
    <span style={{ display: "inline-block", padding: "0.25rem 0", minHeight: "24px" }}>
      <AppLink to={to} margin="0 medium 0 0" current>
        {children}
      </AppLink>
    </span>
  );
}

export function Nav() {
  const me = useMe();
  const f = roleFlags(me.data);
  return (
    <View as="nav" aria-label="OpenCredential" display="block" padding="small 0" borderWidth="0 0 small 0" margin="0 0 medium">
      <Flex wrap="wrap">
        <NavLink to="/">Home</NavLink>
        {f.isStudent && <NavLink to="/me/progress">Badges in my courses</NavLink>}
        {f.isStudent && <NavLink to="/me/credentials">My badges</NavLink>}
        {f.isStaff && <NavLink to="/badges">Badges</NavLink>}
        {f.isStaff && <NavLink to="/awards">Award badges</NavLink>}
        {f.isReviewer && <NavLink to="/reviews">Review queue</NavLink>}
        {f.isAdmin && <NavLink to="/admin">Administration</NavLink>}
        <NavLink to="/help">Help</NavLink>
      </Flex>
    </View>
  );
}

/** Standard page frame: navigation, a single h1 and the content. */
export function Page({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  const me = useMe();
  useEffect(() => {
    document.title = `${title} · Badges`;
  }, [title]);
  // Once the session has ended nothing on the page works, so show only how to carry on, not
  // menus and buttons (such as "Create a badge") that would each fail.
  if (me.error instanceof ApiError && me.error.problem.status === 401) {
    return (
      <View as="main" padding="medium" maxWidth="72rem" margin="0 auto" display="block">
        <Heading level="h1" margin="0 0 small">
          Your session has ended
        </Heading>
        <Text as="p">{SESSION_ENDED}</Text>
      </View>
    );
  }
  return (
    // The navigation sits outside <main>, and a skip link (visible when focused) jumps straight
    // to the content, so keyboard and screen-reader users need not pass the menu on every page.
    <View as="div" padding="medium" maxWidth="72rem" margin="0 auto" display="block">
      <a href="#main-content" className="oc-skip-link">
        Skip to main content
      </a>
      <Nav />
      <main id="main-content" tabIndex={-1} style={{ outline: "none" }}>
        <Flex justifyItems="space-between" alignItems="center" wrap="wrap" margin="0 0 medium">
          <Heading level="h1">{title}</Heading>
          {actions}
        </Flex>
        {children}
      </main>
    </View>
  );
}

/**
 * A page for course staff or administrators, reached by someone who is neither (a student who
 * typed the address). The server refuses every action anyway; this says so plainly instead of
 * drawing forms and menus that cannot work for them.
 */
export function NotForYou({ who }: { who: "staff" | "admins" }) {
  const title = who === "staff" ? "This page is for course staff" : "This page is for administrators";
  return (
    <Page title={title}>
      <Text as="p">
        {who === "staff"
          ? "Creating, reviewing and awarding badges is done by the staff who teach a course."
          : "Only Badges administrators can use the administration pages."}{" "}
        Your own badges and your progress are on <AppLink to="/me/credentials">My badges</AppLink> and{" "}
        <AppLink to="/me/progress">Badges in my courses</AppLink>.
      </Text>
    </Page>
  );
}

/**
 * Shows ``children`` only to course staff (lecturers, TAs, course and other admins). With
 * ``orReviewers`` it also lets in people who can review badges, who may hold no staff role at
 * all (a named Badge reviewer for a faculty).
 */
export function StaffOnly({ children, orReviewers = false }: { children: ReactNode; orReviewers?: boolean }) {
  const me = useMe();
  if (me.isPending) return <Loading what="your roles" />;
  const f = roleFlags(me.data);
  // If the profile cannot be read, let the page show its own error rather than guess.
  if (me.isError || f.isStaff || (orReviewers && f.isReviewer)) return <>{children}</>;
  return <NotForYou who="staff" />;
}

export function Loading({ what }: { what: string }) {
  return <Spinner renderTitle={`Loading ${what}`} margin="large" />;
}

/** Says what went wrong. Several refused fields are listed one per line. */
export function ErrorAlert({ error }: { error: unknown }) {
  const lines = problemLines(error);
  // role="alert" makes screen readers read the problem out as soon as it appears.
  return (
    <div role="alert">
      <Alert variant="error" margin="small 0">
        {lines.length === 1 ? (
          lines[0]
        ) : (
          <>
            <Text weight="bold">Please fix the following:</Text>
            <List margin="x-small 0 0">
              {lines.map((line) => (
                <List.Item key={line}>{line}</List.Item>
              ))}
            </List>
          </>
        )}
      </Alert>
    </div>
  );
}
