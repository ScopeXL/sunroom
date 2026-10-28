import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { addDays, weekOf, weekSpan } from "../lib/dates";
import { useReveal } from "../lib/reveal";
import { Button } from "./Button";
import { Chip } from "./Chip";
import { useFieldLabel } from "./Field";
import { MonthGrid } from "./MonthGrid";
import { useShell } from "./shell";
import { WeekStrip } from "./WeekStrip";

/**
 * A day, picked by touch (UX §4, ADR 0029): the week as seven cells in the household's order,
 * then Previous week, Today and Next week to move it, and Pick a date for any other day, which
 * opens a month grid in place. Neither the wall nor a phone meets the native date input: one
 * code path, one set of names, and nothing the wall screen can't work without a keyboard.
 * The strip follows the chosen day when it leaves the week on show (a tap on the board, a day
 * word typed into quick add).
 */
export function DayField({
  label = "Day",
  value,
  onChange,
  today,
  weekStartsOn,
  min,
  optional,
  grid = "closed",
  anchor,
  hint,
  inRow = false,
}: {
  label?: string;
  /** The chosen day; null only with `optional`. */
  value: string | null;
  onChange: (day: string) => void;
  today: string;
  /** 0 Monday … 6 Sunday, as the household counts. */
  weekStartsOn: number;
  /** No earlier day can be picked. */
  min?: string | undefined;
  /** A chip for "no day at all" (a list item's "No day"), first in the row. */
  optional?: { label: string; onChoose: () => void } | undefined;
  /** Whether the month grid starts open (a countdown's day is rarely this week). */
  grid?: "closed" | "open";
  /** A day in the week to show when no day is chosen (a meal: the week on the board). */
  anchor?: string | undefined;
  hint?: string | undefined;
  /** Inside a ValueRow that already says the label: don't write it twice. */
  inRow?: boolean;
}) {
  const display = useShell() === "display";
  const labelClass = useFieldLabel();
  const [open, setOpen] = useState(grid === "open");
  const month = useReveal<HTMLDivElement>(open);
  const [shown, setShown] = useState(value ?? anchor ?? today);
  // The week on show follows the chosen day when it changes to one outside it.
  const [followed, setFollowed] = useState(value);
  if (followed !== value) {
    setFollowed(value);
    if (value && !weekOf(shown, weekStartsOn).includes(value)) setShown(value);
  }
  const week = weekOf(shown, weekStartsOn);
  const firstAllowed = min === undefined || (week[0] ?? "") > min;
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const icon = display ? "size-8" : "size-6";
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-2">
      <p className={`flex items-baseline gap-3 ${inRow ? "justify-end" : "justify-between"}`}>
        <span className={inRow ? "sr-only" : labelClass}>{label}</span>
        <span aria-live="polite" className={soft}>
          {weekSpan(week)}
        </span>
      </p>
      <WeekStrip
        label={`${label}, this week's days`}
        days={week}
        value={value}
        today={today}
        min={min}
        onChange={onChange}
      />
      <div className={`flex flex-wrap items-center ${display ? "gap-3" : "gap-2"}`}>
        {optional ? (
          <Chip on={value === null} onClick={optional.onChoose}>
            {optional.label}
          </Chip>
        ) : null}
        <Button
          variant="secondary"
          icon
          aria-label="Previous week"
          disabled={!firstAllowed}
          onClick={() => {
            setShown(addDays(shown, -7));
          }}
        >
          <ChevronLeft aria-hidden="true" className={icon} />
        </Button>
        <Chip
          on={value === today}
          disabled={min !== undefined && today < min}
          onClick={() => {
            setShown(today);
            onChange(today);
          }}
        >
          Today
        </Chip>
        <Button
          variant="secondary"
          icon
          aria-label="Next week"
          onClick={() => {
            setShown(addDays(shown, 7));
          }}
        >
          <ChevronRight aria-hidden="true" className={icon} />
        </Button>
        <Chip
          opener
          expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          Pick a date
        </Chip>
      </div>
      {open ? (
        <div ref={month}>
          <MonthGrid
            label={`${label}, by month`}
            value={value}
            today={today}
            weekStartsOn={weekStartsOn}
            min={min}
            onChange={onChange}
          />
        </div>
      ) : null}
      {hint ? <p className={soft}>{hint}</p> : null}
    </div>
  );
}
