// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmButton } from "./ConfirmButton";

function setup() {
  const onConfirm = vi.fn();
  render(
    <ConfirmButton
      label="Archive"
      consequence="Archive this badge? No new awards will be made."
      confirmLabel="Archive this badge"
      cancelLabel="Keep it live"
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

describe("a button that asks before it acts", () => {
  it("does nothing on the first press except say what will happen", async () => {
    const onConfirm = setup();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Archive this badge? No new awards will be made.");
    expect(screen.getByRole("group", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("puts focus on the way out, so Enter twice does not go through with it", async () => {
    const onConfirm = setup();
    screen.getByRole("button", { name: "Archive" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Keep it live" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    // Backing out puts things as they were, with focus back where the person started.
    expect(screen.getByRole("button", { name: "Archive" })).toHaveFocus();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("acts once when the person confirms", async () => {
    const onConfirm = setup();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    await userEvent.click(screen.getByRole("button", { name: "Archive this badge" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
  });
});
