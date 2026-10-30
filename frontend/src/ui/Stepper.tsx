import { Minus, Plus } from "lucide-react";

import { useT } from "../lib/lang";
import { Button } from "./Button";
import { Digits } from "./Digits";
import { useShell } from "./shell";

/**
 * A small whole number changed with two buttons (every 2 weeks, 10 times): no keyboard, and a
 * finger can't type a wrong value. The buttons are named for the row ("Every: less", "Every:
 * more") and stop at the ends. With `step` it moves between that step's multiples (a length in
 * quarter hours), and `words` says the value its own way ("45 min").
 */
export function Stepper({
  label,
  value,
  min = 1,
  max = 99,
  step = 1,
  words,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  words?: (value: number) => string;
  onChange: (value: number) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const icon = display ? "size-8" : "size-6";
  return (
    <div role="group" aria-label={label} className="flex items-center gap-2">
      <Button
        variant="secondary"
        icon
        aria-label={t("ui.stepper.less.aria", { label })}
        disabled={value <= min}
        onClick={() => {
          onChange(Math.max(min, Math.ceil(value / step) * step - step));
        }}
      >
        <Minus aria-hidden="true" className={icon} />
      </Button>
      <output
        aria-live="polite"
        className={`text-center font-bold ${
          words
            ? display
              ? "min-w-36 text-d-body"
              : "min-w-24 text-body"
            : display
              ? "min-w-14 text-d-title"
              : "min-w-10 text-title"
        }`}
      >
        {words ? words(value) : <Digits value={String(value)} />}
      </output>
      <Button
        variant="secondary"
        icon
        aria-label={t("ui.stepper.more.aria", { label })}
        disabled={value >= max}
        onClick={() => {
          onChange(Math.min(max, Math.floor(value / step) * step + step));
        }}
      >
        <Plus aria-hidden="true" className={icon} />
      </Button>
    </div>
  );
}
