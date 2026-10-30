import { useState } from "react";

import { formatWallTime } from "../lib/dates";
import { useT } from "../lib/lang";
import { atHour, atMinute } from "../lib/times";
import { Chip } from "./Chip";
import { useFieldLabel } from "./Field";
import { useShell } from "./shell";
import { ValueRow } from "./ValueRow";

const LATER = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23];
const EARLIER = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const MINUTES = ["00", "15", "30", "45"];

const clock = (time: string) => formatWallTime(`2000-01-01T${time}:00`);

/**
 * A time of day, picked by touch (UX §4, ADR 0030): one row. A chip for no time at all ("All
 * day", "Any time"), then one button that says the time and opens the hours (6 AM to 11 PM,
 * with Earlier hours) and the minutes in place; Done closes them. Two taps for any time, and
 * the row never shows more than the one that's chosen: the chips of likely times it used to
 * offer are gone. `words` says the time its own way ("by 5:00 PM").
 */
export function TimeField({
  label,
  value,
  onChange,
  none,
  words = clock,
}: {
  label: string;
  /** "HH:MM", or null for no time. */
  value: string | null;
  onChange: (time: string | null) => void;
  /** The chip for no time, or null when a time is required. */
  none: { label: string } | null;
  words?: (time: string) => string;
}) {
  const t = useT();
  const display = useShell() === "display";
  const [open, setOpen] = useState(false);
  const [early, setEarly] = useState(false);
  const soft = useFieldLabel();
  const hour = value ? Number(value.slice(0, 2)) : null;
  const minute = value ? value.slice(3, 5) : null;
  const grid = `grid grid-cols-4 ${display ? "gap-2" : "gap-1.5"}`;
  return (
    <ValueRow
      label={label}
      value={value ? words(value) : t("ui.time.pick")}
      expanded={open}
      onToggle={() => {
        setOpen(!open);
      }}
      before={
        none ? (
          <Chip
            on={value === null}
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
          >
            {none.label}
          </Chip>
        ) : null
      }
    >
      <p className={soft}>{t("ui.time.hour.label")}</p>
      <div role="group" aria-label={t("ui.time.hour.aria", { label })} className={grid}>
        {(early ? EARLIER : LATER).map((h) => (
          <Chip
            key={h}
            block
            on={hour === h}
            onClick={() => {
              onChange(atHour(h, value));
            }}
          >
            {formatWallTime(`2000-01-01T${atHour(h, null)}:00`, { compact: true })}
          </Chip>
        ))}
      </div>
      <p className={soft}>{t("ui.time.minutes.label")}</p>
      <div role="group" aria-label={t("ui.time.minutes.aria", { label })} className={grid}>
        {MINUTES.map((m) => (
          <Chip
            key={m}
            block
            on={minute === m}
            onClick={() => {
              onChange(atMinute(m, value));
            }}
          >
            {`:${m}`}
          </Chip>
        ))}
      </div>
      <div className={`flex flex-wrap justify-between ${display ? "gap-3" : "gap-2"}`}>
        <Chip
          onClick={() => {
            setEarly(!early);
          }}
        >
          {early ? t("ui.time.later") : t("ui.time.earlier")}
        </Chip>
        <Chip
          onClick={() => {
            setOpen(false);
          }}
        >
          {t("app.action.done")}
        </Chip>
      </div>
    </ValueRow>
  );
}
