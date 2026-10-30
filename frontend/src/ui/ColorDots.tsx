import { UserRound } from "lucide-react";

import { COLORS } from "../lib/colors";
import type { components } from "../api/schema";
import { useT } from "../lib/lang";
import { useShell } from "./shell";

type PersonColor = components["schemas"]["MemberOut"]["color"];

/**
 * A color for an event or a countdown, as a row of dots (ADR 0030): "no color of its own"
 * first (the person's color shows instead), then the twelve, each a tap-sized cell named by its
 * word ("Red") for a screen reader. No words on the row: nine chips with words were three lines
 * of the Add panel. The chosen one is ringed. Thirteen cells wrap onto a second line in the
 * wall's Add panel; dots aren't chips, so that's allowed (ADR 0034).
 */
export function ColorDots({
  label: given,
  value,
  noneLabel,
  onChange,
}: {
  label?: string;
  value: PersonColor | null;
  /** What the first cell means: "The person's color", "No color". */
  noneLabel: string;
  onChange: (color: PersonColor | null) => void;
}) {
  const t = useT();
  const label = given ?? t("ui.color.label");
  const display = useShell() === "display";
  const cell = `press flex shrink-0 items-center justify-center rounded-full ring-inset aria-checked:ring-4 aria-checked:ring-ink ${
    display ? "size-tap" : "size-11"
  }`;
  const dot = display ? "size-9" : "size-7";
  return (
    <div role="radiogroup" aria-label={label} data-segmented="" className="flex flex-wrap gap-2">
      <button
        type="button"
        role="radio"
        aria-checked={value === null}
        aria-label={noneLabel}
        onClick={() => {
          onChange(null);
        }}
        className={cell}
      >
        <span
          className={`flex ${dot} items-center justify-center rounded-full border-2 border-ink-soft text-ink-soft`}
        >
          <UserRound aria-hidden="true" className="size-2/3" />
        </span>
      </button>
      {COLORS.map((color) => (
        <button
          key={color.value}
          type="button"
          role="radio"
          aria-checked={value === color.value}
          aria-label={t(color.word)}
          data-person={color.value}
          onClick={() => {
            onChange(color.value);
          }}
          className={cell}
        >
          <span className={`${dot} rounded-full bg-p`} />
        </button>
      ))}
    </div>
  );
}
