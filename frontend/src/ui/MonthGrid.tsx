import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import {
  dayNumber,
  longMonthDay,
  monthGrid,
  monthYear,
  orderedWeekdays,
  weekdayShort,
} from "../lib/dates";
import { Button } from "./Button";
import { useShell } from "./shell";

/**
 * A month to pick a day from (UX §4): whole weeks starting on the household's day, with
 * Previous month and Next month. It stands in for the native date input everywhere, the wall
 * and phones alike: one look, tap-sized cells, and no system dialog the wall screen can't
 * work. Each cell is named as a date read aloud ("October 8"), which no other button on a form
 * is called; today is marked, days of the neighbouring months are quieter, and days before
 * `min` can't be picked.
 */
export function MonthGrid({
  label,
  value,
  today,
  weekStartsOn,
  min,
  onChange,
}: {
  label: string;
  value: string | null;
  today: string;
  /** 0 Monday … 6 Sunday, as the household counts. */
  weekStartsOn: number;
  min?: string | undefined;
  onChange: (day: string) => void;
}) {
  const display = useShell() === "display";
  const anchor = value ?? (min !== undefined && min > today ? min : today);
  // The month on show follows the chosen day when it changes from outside (the week strip, the
  // quick-add field), and the arrows move it from there.
  const [month, setMonth] = useState(anchor.slice(0, 7));
  const [followed, setFollowed] = useState(anchor);
  if (followed !== anchor) {
    setFollowed(anchor);
    setMonth(anchor.slice(0, 7));
  }
  const grid = monthGrid(`${month}-01`, 0, weekStartsOn);
  const page = (step: -1 | 1) => {
    setMonth(monthGrid(`${month}-01`, step, weekStartsOn).first.slice(0, 7));
  };
  const earliest = min !== undefined && grid.first <= min;
  const icon = display ? "size-8" : "size-6";
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Button
          variant="secondary"
          icon
          aria-label="Previous month"
          disabled={earliest}
          onClick={() => {
            page(-1);
          }}
        >
          <ChevronLeft aria-hidden="true" className={icon} />
        </Button>
        <p aria-live="polite" className={`font-bold ${display ? "text-d-body" : "text-row"}`}>
          {monthYear(grid.first)}
        </p>
        <Button
          variant="secondary"
          icon
          aria-label="Next month"
          onClick={() => {
            page(1);
          }}
        >
          <ChevronRight aria-hidden="true" className={icon} />
        </Button>
      </div>
      <div
        aria-hidden="true"
        className={`grid grid-cols-7 gap-1 text-center font-semibold text-ink-soft ${
          display ? "text-d-caption" : "text-caption"
        }`}
      >
        {orderedWeekdays(weekStartsOn).map((weekday) => (
          <span key={weekday}>{weekdayShort(weekday)}</span>
        ))}
      </div>
      <div data-segmented="" className="grid grid-cols-7 gap-1">
        {grid.days.map((day) => {
          const inMonth = day.slice(0, 7) === month;
          return (
            <button
              key={day}
              type="button"
              aria-pressed={day === value}
              aria-current={day === today ? "date" : undefined}
              aria-label={longMonthDay(day)}
              disabled={min !== undefined && day < min}
              onClick={() => {
                onChange(day);
              }}
              className={`press select-fill flex min-w-0 items-center justify-center rounded-button font-semibold aria-pressed:bg-ink aria-pressed:text-on-ink disabled:opacity-40 ${
                display ? "min-h-tap text-d-body" : "min-h-11 text-body"
              } ${inMonth ? "" : "text-ink-soft"}`}
            >
              <span
                className={`flex items-center justify-center rounded-full ${
                  display ? "size-10" : "size-8"
                } ${day === today ? "bg-sun text-on-sun" : ""}`}
              >
                {dayNumber(day)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
