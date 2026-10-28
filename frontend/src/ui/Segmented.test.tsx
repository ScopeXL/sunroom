import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Clock3, List } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IconSegmented, Segmented } from "./Segmented";
import { ShellContext } from "./shell";

afterEach(cleanup);

const TIMES = ["Never", "5 min", "15 min", "30 min", "1 hour"].map((label) => ({
  value: label,
  label,
}));

describe("a segmented choice", () => {
  it("wraps onto a second row instead of spilling, and stays one control", () => {
    render(<Segmented label="Start after" options={TIMES} value="15 min" onChange={vi.fn()} />);
    const group = screen.getByRole("group", { name: "Start after" });
    expect(group.className).toContain("flex-wrap");
    expect(group.hasAttribute("data-segmented")).toBe(true);
    // A fixed radius: a wrapped group must not turn into a capsule two rows tall.
    expect(group.className).not.toContain("rounded-full");
    const cells = screen.getAllByRole("button");
    expect(cells.map((cell) => cell.getAttribute("aria-pressed"))).toEqual([
      "false",
      "false",
      "true",
      "false",
      "false",
    ]);
    for (const cell of cells) expect(cell.className).toContain("flex-auto");
  });

  it("gives each word more room on the wall than on a phone", () => {
    const onChange = vi.fn();
    render(
      <ShellContext.Provider value="display">
        <Segmented label="Theme" options={TIMES.slice(0, 2)} value="Never" onChange={onChange} />
      </ShellContext.Provider>,
    );
    const cell = screen.getByRole("button", { name: "5 min" });
    expect(cell.className).toContain("px-5");
    expect(cell.className).toContain("min-h-tap");
    fireEvent.click(cell);
    expect(onChange).toHaveBeenCalledWith("5 min");
  });
});

describe("a stacked row of kinds (the Add panel's types)", () => {
  const KINDS = [
    { value: "event", label: "Event", icon: Clock3 },
    { value: "item", label: "Item", icon: List },
  ] as const;

  it("is one line that scrolls sideways, each cell an icon over its word", () => {
    const onChange = vi.fn();
    render(
      <ShellContext.Provider value="display">
        <Segmented label="What to add" options={KINDS} value="item" onChange={onChange} stacked />
      </ShellContext.Provider>,
    );
    const group = screen.getByRole("group", { name: "What to add" });
    expect(group.className).toContain("flex-nowrap");
    expect(group.className).toContain("overflow-x-auto");
    expect(group.className).not.toContain("flex-wrap");
    expect(group.hasAttribute("data-segmented")).toBe(true);
    expect(group.getAttribute("data-overflow")).toBe("none");
    const event = screen.getByRole("button", { name: "Event" });
    const item = screen.getByRole("button", { name: "Item" });
    expect([event, item].map((cell) => cell.getAttribute("aria-pressed"))).toEqual([
      "false",
      "true",
    ]);
    for (const cell of [event, item]) {
      expect(cell.className).toContain("flex-col");
      expect(cell.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    }
    fireEvent.click(event);
    expect(onChange).toHaveBeenCalledWith("event");
  });
});

describe("an icon group", () => {
  const LAYOUTS = [
    { value: "agenda", label: "Agenda", icon: List },
    { value: "hours", label: "Hours", icon: Clock3 },
  ] as const;

  it("names each round, tap-sized cell and marks the chosen one", () => {
    const onChange = vi.fn();
    render(
      <ShellContext.Provider value="display">
        <IconSegmented label="Week layout" options={LAYOUTS} value="hours" onChange={onChange} />
      </ShellContext.Provider>,
    );
    const group = screen.getByRole("group", { name: "Week layout" });
    expect(group.hasAttribute("data-segmented")).toBe(true);
    const agenda = screen.getByRole("button", { name: "Agenda" });
    const hours = screen.getByRole("button", { name: "Hours" });
    expect([agenda, hours].map((cell) => cell.getAttribute("aria-pressed"))).toEqual([
      "false",
      "true",
    ]);
    for (const cell of [agenda, hours]) {
      expect(cell.className).toContain("h-tap");
      expect(cell.className).toContain("min-w-tap");
      expect(cell.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    }
    fireEvent.click(agenda);
    expect(onChange).toHaveBeenCalledWith("agenda");
  });

  it("writes the chosen option's word beside its icon when asked", () => {
    render(
      <IconSegmented
        label="Week layout"
        options={LAYOUTS}
        value="hours"
        onChange={vi.fn()}
        showChosen
      />,
    );
    expect(screen.getByRole("button", { name: "Hours" }).textContent).toBe("Hours");
    expect(screen.getByRole("button", { name: "Agenda" }).textContent).toBe("");
  });
});
