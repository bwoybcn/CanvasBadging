// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from "@instructure/ui";
import type { ReactNode } from "react";
import { useHref, useNavigate } from "react-router";

/** An InstUI link that navigates inside the single-page app. */
export function AppLink({ to, children, margin }: { to: string; children: ReactNode; margin?: string }) {
  const href = useHref(to);
  const navigate = useNavigate();
  return (
    <Link
      href={href}
      margin={margin as never}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </Link>
  );
}
