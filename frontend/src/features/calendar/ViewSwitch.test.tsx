import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardView } from "../../lib/displayState";
import { ShellContext } from "../../ui/shell";
import { ViewSwitch } from "./ViewSwitch";

afterEach(cleanup);

function draw(view: BoardView = "week", onView = vi.fn()) {
  render(
    <ShellContext.Provider value="display">
      <ViewSwitch view={view} onView={onView} />
    </ShellContext.Provider>,
  );
  return onView;
}

/** What a screen reader reads after a row's name. */
function line(row: HTMLElement): string | null | undefined {
  const id = row.getAttribute("aria-describedby");
  return id === null ? null : document.getElementById(id)?.textContent;
}

const NAMES = ["Week", "Rolling Week", "Day", "Month", "People", "Today"];

describe("the board's View menu in the header (ADR 0042)", () => {
  it("is one button that says the view, on every view", () => {
    for (const [view, name] of [
      ["week", "Week"],
      ["rolling", "Rolling Week"],
      ["today", "Today"],
    ] as const) {
      draw(view);
      const button = screen.getByRole("button", { name: `View: ${name}` });
      expect(button.textContent).toBe(name);
      expect(button.getAttribute("aria-haspopup")).toBe("menu");
      expect(button.getAttribute("aria-expanded")).toBe("false");
      cleanup();
    }
  });

  it("opens on the six views, each with a drawing, its name and one line", () => {
    draw("rolling");
    const button = screen.getByRole("button", { name: "View: Rolling Week" });
    fireEvent.click(button);
    const menu = screen.getByRole("menu", { name: "View" });
    expect(button.getAttribute("aria-controls")).toBe(menu.id);
    const rows = screen.getAllByRole("menuitemradio");
    expect(NAMES.map((name) => rows.indexOf(screen.getByRole("menuitemradio", { name })))).toEqual([
      0, 1, 2, 3, 4, 5,
    ]);
    expect(rows.map(line)).toEqual([
      "The calendar week, a column for each day.",
      "Yesterday, today and the five days after.",
      "One day, hour by hour.",
      "The whole month. Tap a day to open it.",
      "A column for each person, one day at a time.",
      "Today at a glance, then the days ahead.",
    ]);
    for (const row of rows) expect(row.querySelector("[aria-hidden=true] svg")).not.toBeNull();
    expect(rows.map((row) => row.getAttribute("aria-checked"))).toEqual([
      "false",
      "true",
      "false",
      "false",
      "false",
      "false",
    ]);
  });

  it("lands on the view that's on, walks the rows, and a choice closes it", () => {
    const onView = draw("rolling");
    const button = screen.getByRole("button", { name: "View: Rolling Week" });
    fireEvent.click(button);
    const menu = screen.getByRole("menu");
    const rows = screen.getAllByRole("menuitemradio");
    expect(document.activeElement).toBe(rows[1]);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[2]);
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(rows[5]);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[0]);
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(rows[5]);
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(rows[0]);
    // Today is a view among the others, so a screen on Today leaves it from here too.
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Today" }));
    expect(onView).toHaveBeenCalledWith("today");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("closes on Escape and on a press anywhere else, choosing nothing", () => {
    const onView = draw();
    const button = screen.getByRole("button", { name: "View: Week" });
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(onView).not.toHaveBeenCalled();
  });
});
