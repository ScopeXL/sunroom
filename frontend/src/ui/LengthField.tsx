import { useState } from "react";

import { t, useT } from "../lib/lang";
import { Chip } from "./Chip";
import { useFieldLabel } from "./Field";
import { useShell } from "./shell";
import { Stepper } from "./Stepper";
import { ChoiceList, ValueRow } from "./ValueRow";

const LENGTHS = [30, 60, 90, 120, 180];

/** "30 min", "1 hour", "1½ hours", "2 hours", "2 h 15 min" (UX §2), in the page's language. */
export function lengthWords(minutes: number): string {
  if (minutes < 60) return t("dates.length.minutes", { n: minutes });
  if (minutes === 90) return t("dates.length.hour_and_a_half");
  return minutes % 60 === 0
    ? t("dates.length.hours", { n: minutes / 60 })
    : t("dates.length.hours_minutes", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}

/**
 * How long something lasts (UX §4, ADR 0030): one row whose button says the length and opens
 * the usual ones as a list, with Other for anything else in quarter hours. A length that isn't
 * one of the usual ones (45 minutes typed into quick add) shows on the button as it is.
 */
export function LengthField({
  label: given,
  value,
  onChange,
}: {
  /** How long, unless it's said otherwise. */
  label?: string;
  /** Minutes. */
  value: number;
  onChange: (minutes: number) => void;
}) {
  const t = useT();
  const label = given ?? t("ui.length.label");
  const display = useShell() === "display";
  const soft = useFieldLabel();
  const [open, setOpen] = useState(false);
  return (
    <ValueRow
      label={label}
      value={lengthWords(value)}
      expanded={open}
      onToggle={() => {
        setOpen(!open);
      }}
    >
      <ChoiceList
        label={label}
        choices={LENGTHS.map((minutes) => ({ value: minutes, label: lengthWords(minutes) }))}
        value={LENGTHS.includes(value) ? value : undefined}
        onChange={(minutes) => {
          onChange(minutes);
          setOpen(false);
        }}
      />
      <div
        className={`flex flex-wrap items-center justify-between gap-3 ${display ? "pl-4" : "pl-3"}`}
      >
        <span className={soft}>{t("ui.length.other.label")}</span>
        <Stepper
          label={t("ui.length.other.aria", { label })}
          value={value}
          min={15}
          max={24 * 60}
          step={15}
          words={lengthWords}
          onChange={onChange}
        />
      </div>
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
