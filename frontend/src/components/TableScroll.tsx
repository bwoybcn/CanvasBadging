// SPDX-License-Identifier: AGPL-3.0-or-later
import { Children, isValidElement, type ReactNode } from "react";

/**
 * Lets a wide data table scroll sideways inside its own box instead of making the whole page
 * scroll (WCAG 1.4.10 Reflow at 320 CSS pixels / 400% zoom; data tables are the permitted
 * two-dimensional exception, the page around them is not). The box is a labelled, focusable
 * region so keyboard users can scroll it too (axe "scrollable-region-focusable").
 */
export function TableScroll({ children }: { children: ReactNode }) {
  const only = Children.only(children);
  const caption = isValidElement<{ caption?: ReactNode }>(only)
    ? only.props.caption
    : undefined;
  const label = typeof caption === "string" ? caption : "Table";
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      style={{ overflowX: "auto", maxWidth: "calc(100vw - 2rem)", minWidth: 0 }}
    >
      {children}
    </div>
  );
}
