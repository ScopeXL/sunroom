import type { KeyboardEvent } from "react";

import {
  dayNumber,
  longMonth,
  orderedWeekdays,
  shortWeekday,
  weekdayLong,
  weekdayShort,
} from "../lib/dates";
import { t, useT } from "../lib/lang";
import { useShell } from "./shell";

/** A day cell's name, in the order it shows: "Thu 8, October" (voice control, WCAG 2.5.3). */
export function cellDate(day: string): string {
  return t("ui.week.day.aria", {
    weekday: shortWeekday(day),
    day: dayNumber(day),
    month: longMonth(day),
  });
}

/** Left and right arrows walk a row of cells, for laptops (a finger just taps). */
function walkCells(event: KeyboardEvent<HTMLDivElement>): void {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const cells = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:enabled"));
  const at = cells.findIndex((cell) => cell === document.activeElement);
  if (at < 0) return;
  event.preventDefault();
  cells[(at + (event.key === "ArrowRight" ? 1 : -1) + cells.length) % cells.length]?.focus();
}

const CELL =
  "press select-fill flex min-w-0 flex-col items-center justify-center gap-0.5 border-2 border-line bg-surface font-semibold aria-pressed:border-ink aria-pressed:bg-ink aria-pressed:text-on-ink disabled:opacity-40";

/**
 * One week of days to pick from, in the order it's given (the household's, from `weekOf`): the
 * weekday's name over the day's number, today's number on a sun disc. Seven equal cells across
 * the panel, so the row never wraps or scrolls. Each cell is named like a date in a sentence
 * ("Thu 8, October", with ", today" where it is).
 */
export function WeekStrip({
  label,
  days,
  value,
  today,
  min,
  onChange,
}: {
  label: string;
  days: readonly string[];
  /** The chosen day, when it's in this week. */
  value: string | null;
  today: string;
  /** No earlier day can be picked. */
  min?: string | undefined;
  onChange: (day: string) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  return (
    <div
      role="group"
      aria-label={label}
      data-segmented=""
      className="grid grid-cols-7 gap-1"
      onKeyDown={walkCells}
    >
      {days.map((day) => (
        <button
          key={day}
          type="button"
          aria-pressed={day === value}
          aria-label={
            day === today ? t("ui.week.today.aria", { day: cellDate(day) }) : cellDate(day)
          }
          disabled={min !== undefined && day < min}
          onClick={() => {
            onChange(day);
          }}
          className={`${CELL} ${
            display
              ? "min-h-[4.5rem] rounded-button-d text-d-caption"
              : "min-h-14 rounded-button text-caption"
          }`}
        >
          <span>{shortWeekday(day)}</span>{" "}
          <span
            className={`flex items-center justify-center rounded-full font-bold ${
              display ? "size-9 text-d-body" : "size-7 text-body"
            } ${day === today ? "bg-sun text-on-sun" : ""}`}
          >
            {dayNumber(day)}
          </span>
        </button>
      ))}
    </div>
  );
}

/**
 * Which weekdays (a custom repeat's, a routine's): the seven days in the household's order,
 * Sunday or Monday first, any number chosen. Each cell says what it shows, then its full name ("Mon, Monday").
 * With `minOne` the last chosen day can't be taken off: a weekly rule needs one.
 */
export function WeekdayPicker({
  label,
  weekStartsOn,
  value,
  onChange,
  minOne = true,
}: {
  label: string;
  /** 0 Monday … 6 Sunday, as the household counts. */
  weekStartsOn: number;
  /** The chosen weekdays, 0 Monday … 6 Sunday. */
  value: readonly number[];
  onChange: (weekdays: number[]) => void;
  minOne?: boolean;
}) {
  const display = useShell() === "display";
  return (
    <div
      role="group"
      aria-label={label}
      data-segmented=""
      className="grid grid-cols-7 gap-1"
      onKeyDown={walkCells}
    >
      {orderedWeekdays(weekStartsOn).map((weekday) => {
        const on = value.includes(weekday);
        return (
          <button
            key={weekday}
            type="button"
            aria-pressed={on}
            aria-label={t("ui.week.weekday.aria", {
              short: weekdayShort(weekday),
              long: weekdayLong(weekday),
            })}
            onClick={() => {
              if (on && minOne && value.length <= 1) return;
              const next = on ? value.filter((day) => day !== weekday) : [...value, weekday];
              onChange([...next].sort((a, b) => a - b));
            }}
            className={`${CELL} ${
              display
                ? "min-h-tap rounded-button-d text-d-secondary"
                : "min-h-11 rounded-button text-secondary"
            }`}
          >
            {weekdayShort(weekday)}
          </button>
        );
      })}
    </div>
  );
}
