import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DayField } from "./DayField";

afterEach(cleanup);

const TODAY = "2026-10-07"; // a Wednesday

function Field({
  start,
  onDay,
  ...props
}: { start: string | null; onDay?: (day: string | null) => void } & Partial<
  Parameters<typeof DayField>[0]
>) {
  const [day, setDay] = useState(start);
  const change = (next: string | null) => {
    setDay(next);
    onDay?.(next);
  };
  return <DayField value={day} onChange={change} today={TODAY} weekStartsOn={6} {...props} />;
}

describe("a day, picked by touch (ADR 0029)", () => {
  it("shows the chosen day's week, and moves by a week without changing the day", () => {
    const onDay = vi.fn();
    render(<Field start={TODAY} onDay={onDay} />);
    expect(screen.getByText("Oct 4–10")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Wed 7, October, today" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Next week" }));
    expect(screen.getByText("Oct 11–17")).toBeTruthy();
    expect(onDay).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tue 13, October" }));
    expect(onDay).toHaveBeenLastCalledWith("2026-10-13");
    // Today comes back to this week and picks today.
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(screen.getByText("Oct 4–10")).toBeTruthy();
    expect(onDay).toHaveBeenLastCalledWith(TODAY);
  });

  it("opens a month grid in place for any other day, and the strip follows", () => {
    const onDay = vi.fn();
    render(<Field start={TODAY} onDay={onDay} />);
    const pick = screen.getByRole("button", { name: "Pick a date" });
    expect(pick.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("October 2026")).toBeNull();
    fireEvent.click(pick);
    expect(pick.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    fireEvent.click(screen.getByRole("button", { name: "November 20" }));
    expect(onDay).toHaveBeenLastCalledWith("2026-11-20");
    expect(screen.getByText("Nov 15–21")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Fri 20, November" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("offers no day at all when the day is optional", () => {
    const onDay = vi.fn();
    function Optional() {
      const [day, setDay] = useState<string | null>("2026-10-09");
      return (
        <DayField
          value={day}
          today={TODAY}
          weekStartsOn={6}
          onChange={(next) => {
            setDay(next);
            onDay(next);
          }}
          optional={{
            label: "No day",
            onChoose: () => {
              setDay(null);
              onDay(null);
            },
          }}
        />
      );
    }
    render(<Optional />);
    const none = screen.getByRole("button", { name: "No day" });
    expect(none.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(none);
    expect(onDay).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole("button", { name: "No day" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(
      screen.getAllByRole("button").filter((cell) => cell.getAttribute("aria-pressed") === "true"),
    ).toHaveLength(1);
  });

  it("starts with the month open for a day that's rarely this week, on the week it's given", () => {
    render(<Field start={null} grid="open" anchor="2026-10-20" />);
    expect(screen.getByText("Oct 18–24")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pick a date" }).getAttribute("aria-expanded")).toBe(
      "true",
    );
    expect(screen.getByText("October 2026")).toBeTruthy();
  });

  it("can't go back past the earliest day", () => {
    render(<Field start={TODAY} min={TODAY} />);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Previous week" }).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Next week" }));
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Previous week" }).disabled).toBe(
      false,
    );
  });
});
