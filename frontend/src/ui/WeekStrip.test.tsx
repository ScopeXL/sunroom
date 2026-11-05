import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { weekOf } from "../lib/dates";
import { WeekdayPicker, WeekStrip } from "./WeekStrip";

afterEach(cleanup);

const TODAY = "2026-10-07"; // a Wednesday

describe("a week of days to pick from", () => {
  it("shows the household's week in its order, with today and the chosen day marked", () => {
    const onChange = vi.fn();
    render(
      <WeekStrip
        label="Day"
        days={weekOf(TODAY, 6)}
        value="2026-10-08"
        today={TODAY}
        onChange={onChange}
      />,
    );
    const cells = screen.getAllByRole("button");
    expect(cells.map((cell) => cell.getAttribute("aria-label"))).toEqual([
      "Sun 4, October",
      "Mon 5, October",
      "Tue 6, October",
      "Wed 7, October, today",
      "Thu 8, October",
      "Fri 9, October",
      "Sat 10, October",
    ]);
    expect(cells.map((cell) => cell.getAttribute("aria-pressed"))).toEqual([
      "false",
      "false",
      "false",
      "false",
      "true",
      "false",
      "false",
    ]);
    expect(cells[3]?.textContent).toBe("Wed 7");
    fireEvent.click(screen.getByRole("button", { name: "Fri 9, October" }));
    expect(onChange).toHaveBeenCalledWith("2026-10-09");
  });

  it("starts on Monday for a Monday household, and can't pick before the earliest day", () => {
    const onChange = vi.fn();
    render(
      <WeekStrip
        label="Day"
        days={weekOf(TODAY, 0)}
        value={null}
        today={TODAY}
        min={TODAY}
        onChange={onChange}
      />,
    );
    const cells = screen.getAllByRole<HTMLButtonElement>("button");
    expect(cells[0]?.getAttribute("aria-label")).toBe("Mon 5, October");
    expect(cells.map((cell) => cell.disabled)).toEqual([
      true,
      true,
      false,
      false,
      false,
      false,
      false,
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Mon 5, October" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("walks its cells with the arrow keys", () => {
    render(
      <WeekStrip
        label="Day"
        days={weekOf(TODAY, 6)}
        value={TODAY}
        today={TODAY}
        onChange={vi.fn()}
      />,
    );
    const cells = screen.getAllByRole("button");
    cells[3]?.focus();
    fireEvent.keyDown(screen.getByRole("group", { name: "Day" }), { key: "ArrowRight" });
    expect(document.activeElement).toBe(cells[4]);
    fireEvent.keyDown(screen.getByRole("group", { name: "Day" }), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("group", { name: "Day" }), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(cells[2]);
  });
});

describe("which weekdays", () => {
  it("lists them in the household's order, several at once", () => {
    const onChange = vi.fn();
    render(<WeekdayPicker label="On" weekStartsOn={6} value={[1, 3]} onChange={onChange} />);
    const cells = screen.getAllByRole("button");
    expect(cells.map((cell) => cell.getAttribute("aria-label"))).toEqual([
      "Sun, Sunday",
      "Mon, Monday",
      "Tue, Tuesday",
      "Wed, Wednesday",
      "Thu, Thursday",
      "Fri, Friday",
      "Sat, Saturday",
    ]);
    expect(cells.map((cell) => cell.textContent)).toEqual([
      "Sun",
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
    ]);
    expect(screen.getByRole("button", { name: "Tue, Tuesday" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    // Sunday is weekday 6: the value stays sorted Monday first, whatever the order on screen.
    fireEvent.click(screen.getByRole("button", { name: "Sun, Sunday" }));
    expect(onChange).toHaveBeenLastCalledWith([1, 3, 6]);
    fireEvent.click(screen.getByRole("button", { name: "Thu, Thursday" }));
    expect(onChange).toHaveBeenLastCalledWith([1]);
  });

  it("keeps its last day, unless none is allowed", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <WeekdayPicker label="On" weekStartsOn={0} value={[2]} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Wed, Wednesday" }));
    expect(onChange).not.toHaveBeenCalled();
    rerender(
      <WeekdayPicker label="On" weekStartsOn={0} value={[2]} onChange={onChange} minOne={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Wed, Wednesday" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
