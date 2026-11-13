// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from "@instructure/ui";
import type { ReactNode } from "react";
import { Link as RouterLink, useMatch, useResolvedPath } from "react-router";

/**
 * An InstUI-styled link that navigates inside the single-page app.
 *
 * Rendered through react-router's <Link> so it stays a plain <a href> with no click handler of
 * InstUI's own: InstUI gives a link that has an onClick role="button", which made screen readers
 * announce every navigation item as a button (W6 finding, fixed in W8). Modifier-clicks open a
 * new tab as usual. ``current`` marks the link for the page you are on with aria-current="page".
 */
export function AppLink({
  to,
  children,
  margin,
  current = false,
}: {
  to: string;
  children: ReactNode;
  margin?: string;
  current?: boolean;
}) {
  const resolved = useResolvedPath(to);
  const match = useMatch({ path: resolved.pathname, end: to === "/" });
  const isCurrent = current && match !== null;
  return (
    <Link
      as={RouterLink as never}
      {...({ to } as object)}
      margin={margin as never}
      aria-current={isCurrent ? "page" : undefined}
      themeOverride={isCurrent ? { fontWeight: 700 } : undefined}
    >
      {children}
    </Link>
  );
}
