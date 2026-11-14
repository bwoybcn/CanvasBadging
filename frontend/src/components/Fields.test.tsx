// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ColourField, countText, LimitedTextArea, matching, readColour, SearchSelect } from "./Fields";

function Box({ max, start = "" }: { max: number; start?: string }) {
  const [v, setV] = useState(start);
  return <LimitedTextArea label="Short description" maxLength={max} value={v} onChange={(e) => setV(e.target.value)} />;
}

describe("a text box with a limit", () => {
  it("counts from the start on a short field and only near the limit on a long one", () => {
    expect(countText(0, 280)).toBe("0 of 280 characters.");
    expect(countText(1000, 4000)).toBeNull();
    expect(countText(3600, 4000)).toBe("3600 of 4000 characters.");
    expect(countText(4000, 4000)).toBe("4000 of 4000 characters: that is the most this can hold.");
  });

  it("stops typing at the limit and says so", async () => {
    render(<Box max={10} start="12345678" />);
    const box = screen.getByLabelText(/Short description/);
    expect(box).toHaveAttribute("maxlength", "10");
    expect(screen.getByText("8 of 10 characters.")).toBeInTheDocument();
    await userEvent.type(box, "9012");
    expect(box).toHaveValue("1234567890");
    expect(screen.getByText("10 of 10 characters: that is the most this can hold.")).toBeInTheDocument();
  });
});

function Colour({ start = "#1f4e79", optional = false, seen }: { start?: string; optional?: boolean; seen: (v: string) => void }) {
  const [v, setV] = useState(start);
  return (
    <ColourField
      label="Main colour"
      optional={optional}
      value={v}
      onChange={(x) => {
        seen(x);
        setV(x);
      }}
    />
  );
}

describe("choosing a colour", () => {
  it("reads codes however they are typed", () => {
    expect(readColour("#1F4E79")).toBe("#1f4e79");
    expect(readColour(" 1f4e79 ")).toBe("#1f4e79");
    expect(readColour("#abc")).toBe("#aabbcc");
    expect(readColour("#abc", false)).toBeNull(); // still being typed: it may become #abc123
    expect(readColour("navy")).toBeNull();
    expect(readColour("#12345")).toBeNull();
    expect(readColour("")).toBeNull();
  });

  it("is picked from a swatch, with no code to type", () => {
    const seen = vi.fn();
    render(<Colour seen={seen} />);
    const swatch = screen.getByLabelText("Main colour");
    expect(swatch).toHaveAttribute("type", "color");
    expect(swatch).toHaveValue("#1f4e79");
    fireEvent.change(swatch, { target: { value: "#00AA55" } });
    expect(seen).toHaveBeenLastCalledWith("#00aa55");
    expect(screen.getByText(/Chosen: #00aa55/)).toBeInTheDocument();
    expect(screen.getByLabelText("Main colour: or paste a colour code")).toHaveValue("#00aa55");
  });

  it("accepts a pasted brand code and never hands back a broken one", async () => {
    const seen = vi.fn();
    render(<Colour seen={seen} />);
    const code = screen.getByLabelText("Main colour: or paste a colour code");
    await userEvent.clear(code);
    await userEvent.type(code, "212b5");
    expect(screen.getByText(/Use a code such as #1f4e79/)).toBeInTheDocument();
    expect(seen).not.toHaveBeenCalled();
    await userEvent.type(code, "8");
    expect(seen).toHaveBeenLastCalledWith("#212b58");
    expect(screen.queryByText(/Use a code such as/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Main colour")).toHaveValue("#212b58");
    // Leaving a half-typed code puts the last good colour back.
    await userEvent.clear(code);
    await userEvent.type(code, "#zz");
    await userEvent.tab();
    expect(code).toHaveValue("#212b58");
    expect(seen).toHaveBeenCalledTimes(1);
    // A short code counts once the person has finished typing it.
    await userEvent.clear(code);
    await userEvent.type(code, "#abc");
    expect(seen).toHaveBeenCalledTimes(1);
    await userEvent.tab();
    expect(seen).toHaveBeenLastCalledWith("#aabbcc");
    expect(code).toHaveValue("#aabbcc");
  });

  it("can be left unset where a colour is optional", async () => {
    const seen = vi.fn();
    render(<Colour seen={seen} optional start="" />);
    expect(screen.getByText(/No colour chosen/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear main colour" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Main colour"), { target: { value: "#336699" } });
    expect(seen).toHaveBeenLastCalledWith("#336699");
    await userEvent.click(screen.getByRole("button", { name: "Clear main colour" }));
    expect(seen).toHaveBeenLastCalledWith("");
    expect(screen.getByText(/No colour chosen/)).toBeInTheDocument();
  });
});

function Picker({ names, onPick }: { names: string[]; onPick?: (id: string) => void }) {
  const [v, setV] = useState("");
  return (
    <SearchSelect
      label="Student"
      things="students"
      options={names.map((n, i) => ({ id: `u-${i}`, label: n }))}
      value={v}
      onChange={(id) => {
        setV(id);
        onPick?.(id);
      }}
    />
  );
}

describe("a picker you can type into", () => {
  it("matches any part of the name, whatever the capitals", () => {
    const people = [{ label: "Sam Student" }, { label: "Priya Patel" }, { label: "Samira Khan" }];
    expect(matching(people, " SAM ").map((p) => p.label)).toEqual(["Sam Student", "Samira Khan"]);
    expect(matching(people, "patel")).toHaveLength(1);
    expect(matching(people, "")).toHaveLength(3);
  });

  it("narrows as you type, picks with a click, and a new search clears the choice", async () => {
    const onPick = vi.fn();
    render(<Picker names={["Sam Student", "Priya Patel", "Samira Khan"]} onPick={onPick} />);
    const box = screen.getByLabelText("Student");
    await userEvent.type(box, "pri");
    expect(screen.queryByRole("option", { name: "Sam Student" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Priya Patel" }));
    expect(onPick).toHaveBeenLastCalledWith("u-1");
    expect(box).toHaveValue("Priya Patel");
    await userEvent.type(box, "x");
    expect(onPick).toHaveBeenLastCalledWith("");
    expect(await screen.findByRole("option", { name: /No students match/ })).toBeInTheDocument();
  });

  it("shows the first fifty of a long list and asks for more of the name", async () => {
    render(<Picker names={Array.from({ length: 120 }, (_, i) => `Student ${i + 1}`)} />);
    await userEvent.click(screen.getByLabelText("Student"));
    expect(await screen.findByRole("option", { name: "And 70 more: type more of the name" })).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(51);
  });
});
