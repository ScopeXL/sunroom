import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { t } from "../lib/lang";
import { ColorPicker, colorOrder, usedBy } from "./ColorPicker";

const FAMILY = [
  { id: "a", name: "Ana", color: "clay" },
  { id: "s", name: "Sam", color: "sky" },
  { id: "m", name: "Mia", color: "rose" },
  { id: "l", name: "Leo", color: "moss" },
] as const;

function words(): string[] {
  return screen.getAllByRole("radio").map((radio) => {
    const label = (radio as HTMLInputElement).labels?.[0];
    return [...(label?.querySelectorAll("span span") ?? [])]
      .map((part) => part.textContent)
      .join(" · ");
  });
}

afterEach(cleanup);

describe("the color picker (UX §4 Settings)", () => {
  it("names whose each taken color is, leaving one person's own out", () => {
    expect(usedBy(FAMILY)).toEqual({ clay: "Ana", sky: "Sam", rose: "Mia", moss: "Leo" });
    expect(usedBy(FAMILY, "m")).toEqual({ clay: "Ana", sky: "Sam", moss: "Leo" });
    // Two people with one color: the first is named.
    expect(usedBy([...FAMILY, { id: "z", name: "Zoe", color: "clay" }]).clay).toBe("Ana");
  });

  it("puts the colors nobody uses first, each part in the list's order", () => {
    expect(colorOrder({}).map((color) => t(color.word))).toEqual([
      "Red",
      "Olive",
      "Green",
      "Teal",
      "Blue",
      "Purple",
      "Plum",
      "Pink",
      "Orange",
      "Brown",
      "Gray",
      "Lime",
    ]);
    expect(colorOrder(usedBy(FAMILY)).map((color) => t(color.word))).toEqual([
      "Olive",
      "Teal",
      "Purple",
      "Plum",
      "Orange",
      "Brown",
      "Gray",
      "Lime",
      "Red",
      "Green",
      "Blue",
      "Pink",
    ]);
  });

  it("shows free colors first, then the taken ones with whose they are", () => {
    render(<ColorPicker name="color" value="sea" used={usedBy(FAMILY)} onChange={vi.fn()} />);
    expect(screen.getByRole("group", { name: "Color" })).toBeTruthy();
    expect(words()).toEqual([
      "Olive",
      "Teal",
      "Purple",
      "Plum",
      "Orange",
      "Brown",
      "Gray",
      "Lime",
      "Red · Ana's",
      "Green · Leo's",
      "Blue · Sam's",
      "Pink · Mia's",
    ]);
    expect(screen.getByRole<HTMLInputElement>("radio", { name: "Teal" }).checked).toBe(true);
  });

  it("picks a color, a taken one included", () => {
    const onChange = vi.fn();
    render(<ColorPicker name="color" value="sea" used={usedBy(FAMILY)} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: /^Pink/ }));
    expect(onChange).toHaveBeenCalledWith("rose");
  });

  it("draws the person's initial in each swatch when given one", () => {
    const { container } = render(
      <ColorPicker name="color" value="rose" initial="M" onChange={vi.fn()} />,
    );
    const swatches = [...container.querySelectorAll("label > span[aria-hidden]")];
    expect(swatches).toHaveLength(12);
    expect(swatches.every((swatch) => swatch.textContent === "M")).toBe(true);
  });
});
