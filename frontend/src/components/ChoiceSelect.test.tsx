// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ChoiceSelect, type Choice } from "./ChoiceSelect";

const CATEGORIES: Choice[] = [
  { value: "Participation", label: "Participation" },
  { value: "Completion", label: "Completion" },
];

describe("a drop-down list that shows only a real choice", () => {
  it("shows the placeholder, not the first option, when nothing is chosen", () => {
    render(<ChoiceSelect label="Category" value="" options={CATEGORIES} placeholder="Choose a category" onChange={vi.fn()} />);
    const box = screen.getByLabelText("Category") as HTMLInputElement;
    expect(box.value).toBe("");
    expect(box).toHaveAttribute("placeholder", "Choose a category");
  });

  it("shows a value that was set before its options loaded", () => {
    const { rerender } = render(<ChoiceSelect label="Template" value="shield" options={[]} onChange={vi.fn()} />);
    expect((screen.getByLabelText("Template") as HTMLInputElement).value).toBe("");
    rerender(
      <ChoiceSelect
        label="Template"
        value="shield"
        options={[
          { value: "roundel", label: "Roundel" },
          { value: "shield", label: "Shield" },
        ]}
        onChange={vi.fn()}
      />,
    );
    expect((screen.getByLabelText("Template") as HTMLInputElement).value).toBe("Shield");
  });

  it("reports the option picked and then shows it", async () => {
    function Form() {
      const [v, setV] = useState("");
      return (
        <>
          <ChoiceSelect label="Category" value={v} options={CATEGORIES} onChange={setV} />
          <p>chosen: {v || "nothing"}</p>
        </>
      );
    }
    render(<Form />);
    expect(screen.getByText("chosen: nothing")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(await screen.findByRole("option", { name: "Completion" }));
    expect(screen.getByText("chosen: Completion")).toBeInTheDocument();
    expect((screen.getByLabelText("Category") as HTMLInputElement).value).toBe("Completion");
  });
});
