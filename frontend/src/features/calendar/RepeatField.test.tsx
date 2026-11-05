import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KeptRule } from "./EventEditor";
import { RepeatField, type RepeatChange } from "./RepeatField";
import { repeatToRRule, type Repeat, type RepeatEnd } from "./repeat";

afterEach(cleanup);

const THURSDAY = "2026-10-08"; // the second Thursday of October 2026
const TODAY = "2026-10-07";

function Field({
  start = null,
  end = {},
  keep = null,
  weekStartsOn = 6,
  presetKeys,
  onRule,
}: {
  start?: Repeat | null;
  end?: RepeatEnd;
  keep?: KeptRule | null;
  weekStartsOn?: number;
  presetKeys?: readonly string[];
  onRule?: (rule: string | null, change: RepeatChange) => void;
}) {
  const [state, setState] = useState<{
    repeat: Repeat | null;
    repeatEnd: RepeatEnd;
    kept: KeptRule | null;
  }>({ repeat: start, repeatEnd: end, kept: keep });
  return (
    <RepeatField
      day={THURSDAY}
      today={TODAY}
      value={state.repeat}
      repeatEnd={state.repeatEnd}
      kept={state.kept}
      weekStartsOn={weekStartsOn}
      {...(presetKeys ? { presetKeys } : {})}
      onChange={(change) => {
        setState(change);
        onRule?.(
          change.repeat
            ? repeatToRRule(change.repeat, THURSDAY, change.repeatEnd, weekStartsOn)
            : null,
          change,
        );
      }}
    />
  );
}

/** The row's button, which says the rule in words: "Repeats: Every week on Thu". */
const row = () => screen.getByRole("button", { name: /^Repeats: / });
const said = () => (row().getAttribute("aria-label") ?? "").replace("Repeats: ", "");
const open = () => {
  if (row().getAttribute("aria-expanded") !== "true") fireEvent.click(row());
};
const checked = () =>
  within(screen.getByRole("radiogroup", { name: "Repeats" }))
    .getAllByRole("radio")
    .filter((choice) => choice.getAttribute("aria-checked") === "true")
    .map((choice) => choice.textContent);

describe("how something repeats (ADR 0029, 0030)", () => {
  it("is one row that says the rule, and opens the usual choices as a list", () => {
    const onRule = vi.fn();
    render(<Field onRule={onRule} />);
    expect(said()).toBe("Doesn't repeat");
    expect(row().getAttribute("aria-expanded")).toBe("false");
    // Closed, there is no wall of chips: just the one button.
    expect(screen.queryByRole("radiogroup")).toBeNull();
    open();
    const choices = within(screen.getByRole("radiogroup", { name: "Repeats" }))
      .getAllByRole("radio")
      .map((choice) => choice.textContent);
    expect(choices).toEqual([
      "Doesn't repeat",
      "Every day",
      "Every weekday",
      "Every week on Thu",
      "Every 2 weeks on Thu",
      "Every month on the 8th",
      "Every month on the second Thursday",
      "Every year on Oct 8",
      "Custom…",
    ]);
    expect(checked()).toEqual(["Doesn't repeat"]);
    // Nothing repeats, so there's nothing to end.
    expect(screen.queryByRole("group", { name: "Ends" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Every week on Thu" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=WEEKLY;BYDAY=TH");
    expect(said()).toBe("Every week on Thu");
    // It stays open: now that it repeats, Ends is there to set. Done closes it.
    expect(screen.getByRole("group", { name: "Ends" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("radiogroup")).toBeNull();
    // Back to not repeating closes it by itself: there's nothing more to say.
    open();
    fireEvent.click(screen.getByRole("radio", { name: "Doesn't repeat" }));
    expect(onRule.mock.lastCall?.[0]).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  it("builds a custom rule: every 2 weeks on Tuesday and Thursday", () => {
    const onRule = vi.fn();
    render(<Field onRule={onRule} />);
    open();
    expect(screen.queryByRole("group", { name: "Every" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Custom…" }));
    // It starts as every week on the start day.
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=WEEKLY;BYDAY=TH");
    expect(checked()).toEqual(["Custom…"]);
    // The weekdays are in the household's order: Sunday first here.
    const days = within(screen.getByRole("group", { name: "On" })).getAllByRole("button");
    expect(days.map((day) => day.getAttribute("aria-label"))[0]).toBe("Sun, Sunday");
    fireEvent.click(screen.getByRole("button", { name: "Every: more" }));
    fireEvent.click(screen.getByRole("button", { name: "Tue, Tuesday" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH");
    expect(said()).toBe("Every 2 weeks on Tue and Thu");
    // No preset says this, so only Custom is checked.
    expect(checked()).toEqual(["Custom…"]);
    // With two or more, the units read as plurals.
    expect(screen.getByRole("button", { name: "Weeks" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers a month by date or by weekday, and days and years", () => {
    const onRule = vi.fn();
    render(<Field onRule={onRule} />);
    open();
    fireEvent.click(screen.getByRole("radio", { name: "Custom…" }));
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=MONTHLY");
    fireEvent.click(screen.getByRole("button", { name: "On the second Thursday" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=MONTHLY;BYDAY=2TH");
    expect(screen.queryByRole("group", { name: "On" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Day" }));
    fireEvent.click(screen.getByRole("button", { name: "Every: more" }));
    fireEvent.click(screen.getByRole("button", { name: "Every: more" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY;INTERVAL=3");
    fireEvent.click(screen.getByRole("button", { name: "Years" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=YEARLY;INTERVAL=3");
  });

  it("ends never, on a date from a month grid, or after a number of times", () => {
    const onRule = vi.fn();
    render(<Field start={{ freq: "daily", interval: 1 }} onRule={onRule} />);
    expect(said()).toBe("Every day");
    open();
    const ends = screen.getByRole("group", { name: "Ends" });
    expect(within(ends).getByRole("button", { name: "Never" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    fireEvent.click(within(ends).getByRole("button", { name: "After 10 times" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY;COUNT=10");
    fireEvent.click(screen.getByRole("button", { name: "Times: less" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY;COUNT=9");
    // The row says the end too.
    expect(said()).toBe("Every day, 9 times");
    expect(within(ends).getByRole("button", { name: "After 9 times" })).toBeTruthy();
    fireEvent.click(within(ends).getByRole("button", { name: "On a date" }));
    // Seeded 90 days on: January 6, 2027.
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY;UNTIL=20270106");
    fireEvent.click(screen.getByRole("button", { name: "January 20" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY;UNTIL=20270120");
    fireEvent.click(within(ends).getByRole("button", { name: "Never" }));
    expect(onRule.mock.lastCall?.[0]).toBe("FREQ=DAILY");
  });

  it("says a rule no preset says, and opens on Custom for it", () => {
    render(<Field start={{ freq: "weekly", interval: 3, weekdays: [0, 2] }} weekStartsOn={0} />);
    expect(said()).toBe("Every 3 weeks on Mon and Wed");
    open();
    expect(checked()).toEqual(["Custom…"]);
    expect(screen.getByRole("status").textContent).toContain("3");
    expect(screen.getByRole("button", { name: "Mon, Monday" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("keeps a rule it can't read as it is, until something else is picked", () => {
    const onRule = vi.fn<(rule: string | null, change: RepeatChange) => void>();
    const kept = { rrule: "FREQ=MONTHLY;BYMONTHDAY=15", text: "Every month on the 15th" };
    render(<Field keep={kept} onRule={onRule} />);
    // The row says it in the server's words.
    expect(said()).toBe("Every month on the 15th");
    open();
    expect(checked()).toEqual(["As it is: every month on the 15th"]);
    // Tapping the kept rule itself changes nothing.
    fireEvent.click(screen.getByRole("radio", { name: /^As it is/ }));
    expect(onRule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "Every day" }));
    expect(onRule.mock.lastCall?.[1].kept).toBeNull();
    expect(screen.queryByRole("radio", { name: /^As it is/ })).toBeNull();
  });

  it("offers a task only the choices it's given, and Custom for the rest", () => {
    render(
      <Field
        start={{ freq: "yearly", interval: 1 }}
        presetKeys={["none", "daily", "weekdays", "weekly", "biweekly", "monthly-date"]}
      />,
    );
    open();
    expect(screen.queryByRole("radio", { name: "Every year on Oct 8" })).toBeNull();
    expect(checked()).toEqual(["Custom…"]);
    expect(screen.getByRole("button", { name: "Year" }).getAttribute("aria-pressed")).toBe("true");
  });
});
