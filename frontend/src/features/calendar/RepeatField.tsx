import { useState } from "react";

import { addDays } from "../../lib/dates";
import { useT } from "../../lib/lang";
import { useReveal } from "../../lib/reveal";
import { Chip } from "../../ui/Chip";
import { useFieldLabel } from "../../ui/Field";
import { MonthGrid } from "../../ui/MonthGrid";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { Stepper } from "../../ui/Stepper";
import { ChoiceList, ValueRow } from "../../ui/ValueRow";
import { WeekdayPicker } from "../../ui/WeekStrip";
import type { KeptRule } from "./EventEditor";
import {
  customToRepeat,
  describeRepeat,
  monthDateChoice,
  monthWeekdayChoice,
  repeatPresets,
  repeatToCustom,
  sameRepeat,
  type CustomRepeat,
  type Repeat,
  type RepeatEnd,
} from "./repeat";

export interface RepeatChange {
  repeat: Repeat | null;
  repeatEnd: RepeatEnd;
  /** Picking anything lets go of a rule that was being kept as it is. */
  kept: null;
}

type EndKind = "never" | "until" | "count";
// Two rows of the list that aren't presets: a rule kept as it is, and Custom….
const KEPT = "as-it-is";
const CUSTOM = "custom";
const DEFAULT_COUNT = 10;
const DEFAULT_UNTIL_DAYS = 90;

/**
 * How something repeats (UX §4 "Repeats", ADR 0029, 0030): one row whose button says the rule in
 * words ("Every week on Thu", "Doesn't repeat") and opens the usual choices as a list, a row
 * each, easier to scan than nine chips. Custom… is the last row: every N days, weeks, months or
 * years, on the weekdays picked (in the household's order), by date or by weekday in a month.
 * Whenever it repeats, Ends: never, on a date, or after a number of times. A rule these shapes
 * can't hold is the first row, "As it is", with the server's words, and stays untouched until
 * another choice is made.
 */
export function RepeatField({
  label: given,
  day,
  today,
  value,
  repeatEnd,
  kept,
  weekStartsOn,
  presetKeys,
  onChange,
}: {
  /** Repeats, unless it's said otherwise. */
  label?: string;
  /** The day it starts on: the presets and the month choices are worded from it. */
  day: string;
  today: string;
  value: Repeat | null;
  repeatEnd: RepeatEnd;
  kept: KeptRule | null;
  /** 0 Monday … 6 Sunday, as the household counts. */
  weekStartsOn: number;
  /** Which presets to offer, by key; all of them when left out. */
  presetKeys?: readonly string[];
  onChange: (change: RepeatChange) => void;
}) {
  const t = useT();
  const label = given ?? t("calendar.repeat.label");
  const display = useShell() === "display";
  const presets = repeatPresets(day).filter(
    (preset) => !presetKeys || presetKeys.includes(preset.key),
  );
  const preset = presets.find((candidate) => sameRepeat(candidate.repeat, value));
  const [open, setOpen] = useState(false);
  // Custom shows for a rule no preset says, and from the moment Custom… is tapped.
  const [customPicked, setCustomPicked] = useState(false);
  const isCustom = customPicked || (!kept && value !== null && !preset);
  const custom = repeatToCustom(value, day);
  const customPanel = useReveal<HTMLDivElement>(isCustom);
  const endKind: EndKind =
    repeatEnd.until !== undefined ? "until" : repeatEnd.count !== undefined ? "count" : "never";

  const set = (repeat: Repeat | null, end: RepeatEnd = repeatEnd) => {
    onChange({ repeat, repeatEnd: repeat ? end : {}, kept: null });
  };
  const setCustom = (change: Partial<CustomRepeat>) => {
    set(customToRepeat({ ...custom, ...change }, day));
  };
  const heading = useFieldLabel();
  const body = display ? "text-d-body font-semibold" : "text-body font-semibold";
  const n = custom.interval;
  const keptWords = kept ? `${kept.text.charAt(0).toLowerCase()}${kept.text.slice(1)}` : "";
  const summary = value
    ? describeRepeat(value, day, repeatEnd, weekStartsOn)
    : kept
      ? kept.text
      : t("calendar.repeat.none");
  const count = repeatEnd.count ?? DEFAULT_COUNT;
  return (
    <ValueRow
      label={label}
      value={summary}
      expanded={open}
      onToggle={() => {
        setOpen(!open);
      }}
    >
      <ChoiceList
        label={label}
        choices={[
          ...(kept ? [{ value: KEPT, label: t("calendar.repeat.kept", { rule: keptWords }) }] : []),
          ...presets.map((candidate) => ({ value: candidate.key, label: candidate.label })),
          { value: CUSTOM, label: t("calendar.repeat.custom") },
        ]}
        value={kept ? KEPT : isCustom ? CUSTOM : preset?.key}
        onChange={(key) => {
          if (key === KEPT) return;
          if (key === CUSTOM) {
            setCustomPicked(true);
            if (kept || value === null) set(customToRepeat(custom, day));
            return;
          }
          const picked = presets.find((candidate) => candidate.key === key);
          setCustomPicked(false);
          set(picked?.repeat ?? null);
          // Nothing more to say about something that doesn't repeat.
          if (!picked?.repeat) setOpen(false);
        }}
      />
      {isCustom ? (
        <div
          ref={customPanel}
          className={`flex flex-col gap-4 border-t-2 border-line pt-4 ${display ? "px-4" : "px-3"}`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className={body}>{t("calendar.repeat.every.label")}</span>
            <Stepper
              label={t("calendar.repeat.every.label")}
              value={custom.interval}
              onChange={(interval) => {
                setCustom({ interval });
              }}
            />
            <Segmented
              label={t("calendar.repeat.every.unit.aria")}
              value={custom.freq}
              options={[
                { value: "daily", label: t("calendar.repeat.unit.daily", { n }) },
                { value: "weekly", label: t("calendar.repeat.unit.weekly", { n }) },
                { value: "monthly", label: t("calendar.repeat.unit.monthly", { n }) },
                { value: "yearly", label: t("calendar.repeat.unit.yearly", { n }) },
              ]}
              onChange={(freq) => {
                setCustom({ freq });
              }}
            />
          </div>
          {custom.freq === "weekly" ? (
            <div className="flex flex-col gap-2">
              <span className={heading}>{t("calendar.repeat.on.label")}</span>
              <WeekdayPicker
                label={t("calendar.repeat.on.label")}
                weekStartsOn={weekStartsOn}
                value={custom.weekdays}
                onChange={(weekdays) => {
                  setCustom({ weekdays });
                }}
              />
            </div>
          ) : null}
          {custom.freq === "monthly" ? (
            <Segmented
              label={t("calendar.repeat.month_by.aria")}
              value={custom.monthlyBy}
              options={[
                { value: "date", label: monthDateChoice(day) },
                { value: "weekday", label: monthWeekdayChoice(day) },
              ]}
              onChange={(monthlyBy) => {
                setCustom({ monthlyBy });
              }}
            />
          ) : null}
        </div>
      ) : null}
      {value ? (
        <div
          className={`flex flex-col gap-2 border-t-2 border-line pt-4 ${display ? "px-4" : "px-3"}`}
        >
          <p className={heading}>{t("calendar.repeat.ends.label")}</p>
          <Segmented<EndKind>
            label={t("calendar.repeat.ends.label")}
            value={endKind}
            options={[
              { value: "never", label: t("calendar.repeat.ends.never") },
              { value: "until", label: t("calendar.repeat.ends.on_date") },
              { value: "count", label: t("calendar.repeat.ends.after", { n: count }) },
            ]}
            onChange={(kind) => {
              set(
                value,
                kind === "until"
                  ? { until: repeatEnd.until ?? addDays(day, DEFAULT_UNTIL_DAYS) }
                  : kind === "count"
                    ? { count: repeatEnd.count ?? DEFAULT_COUNT }
                    : {},
              );
            }}
          />
          {endKind === "until" ? (
            <MonthGrid
              label={t("calendar.repeat.ends.last_day.aria")}
              value={repeatEnd.until ?? null}
              today={today}
              weekStartsOn={weekStartsOn}
              min={day}
              onChange={(until) => {
                set(value, { until });
              }}
            />
          ) : null}
          {endKind === "count" ? (
            <div className="flex items-center gap-3">
              <Stepper
                label={t("calendar.repeat.ends.times.aria")}
                value={count}
                onChange={(times) => {
                  set(value, { count: times });
                }}
              />
              <span className={body}>{t("calendar.repeat.ends.times.label", { n: count })}</span>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="flex justify-end">
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
