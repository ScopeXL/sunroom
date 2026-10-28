import type { LucideIcon } from "lucide-react";

import { useOverflow } from "./ScrollRow";
import { useShell } from "./shell";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** Drawn before the word, or over it when the group is `stacked`. */
  icon?: LucideIcon | undefined;
}

/**
 * A few short choices side by side, one chosen (Light, Dark, Auto). Each option is a button with
 * aria-pressed; the chosen one fills with ink. 56 px on the display, 44 on phones (UX §1), with
 * room around each word. Each takes its own width and an even share of the rest. When the
 * options can't fit one line (five time words on a phone) the group wraps onto a second row
 * instead of spilling past the edge; its corners are a fixed radius, so two rows still read as
 * one control.
 *
 * `stacked` is the form for a row of kinds (the Add panel's Event, Item, Task…): each cell's
 * icon over a short word, always one line; where the row is too narrow (a phone) it scrolls
 * sideways with a fade at the edge instead of wrapping.
 */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  stacked = false,
}: {
  label: string;
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  stacked?: boolean;
}) {
  const display = useShell() === "display";
  const [ref, overflow] = useOverflow<HTMLDivElement>(options, stacked);
  const group = stacked
    ? // scroll-px-1: the snap point is inside the padding, or the row rests 4 px scrolled.
      `fade-x flex-nowrap snap-x scroll-px-1 overflow-x-auto [scrollbar-width:none] rounded-panel ${
        display ? "text-d-secondary" : "text-caption"
      }`
    : // A cell's own radius plus the padding and the border around it.
      `flex-wrap ${
        display
          ? "rounded-[calc(var(--tap)/2+6px)] text-d-body"
          : "rounded-[1.75rem] text-secondary"
      }`;
  const cell = stacked
    ? `shrink-0 snap-start flex-col gap-1 rounded-[1.25rem] ${
        display ? "min-h-[4.5rem] min-w-[6.5rem] px-3" : "min-h-14 min-w-[4.75rem] px-2"
      }`
    : `rounded-full ${display ? "min-h-tap min-w-tap gap-2 px-5" : "min-h-11 min-w-11 gap-2 px-4"}`;
  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      data-segmented=""
      data-overflow={stacked ? overflow : undefined}
      className={`flex gap-1 border-2 border-line bg-surface p-1 ${group}`}
    >
      {options.map(({ value: option, label: word, icon: Icon }) => (
        <button
          key={option}
          type="button"
          aria-pressed={option === value}
          onClick={() => {
            onChange(option);
          }}
          className={`press select-fill flex flex-auto items-center justify-center font-semibold whitespace-nowrap aria-pressed:bg-ink aria-pressed:text-on-ink ${cell}`}
        >
          {Icon ? (
            <Icon
              aria-hidden="true"
              className={`shrink-0 ${display ? (stacked ? "size-8" : "size-7") : "size-5"}`}
            />
          ) : null}
          {word}
        </button>
      ))}
    </div>
  );
}

export interface IconSegmentOption<T extends string> extends SegmentOption<T> {
  icon: LucideIcon;
}

/**
 * The same choice as icons, where words won't fit (the board's views in the header, the Week's
 * layout): round cells at the shell's tap size with no border around the group, so it lines up
 * with the icon buttons beside it. Each cell is named by its label. `showChosen` writes the
 * chosen option's word beside its icon, so the current choice is always readable.
 */
export function IconSegmented<T extends string>({
  label,
  options,
  value,
  onChange,
  showChosen = false,
}: {
  label: string;
  options: readonly IconSegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  showChosen?: boolean;
}) {
  const display = useShell() === "display";
  return (
    <div role="group" aria-label={label} data-segmented="" className="flex gap-2">
      {options.map(({ value: option, label: name, icon: Icon }) => {
        const chosen = option === value;
        const worded = showChosen && chosen;
        return (
          <button
            key={option}
            type="button"
            aria-label={name}
            aria-pressed={chosen}
            onClick={() => {
              onChange(option);
            }}
            className={`press select-fill flex shrink-0 items-center justify-center gap-2 rounded-full font-semibold whitespace-nowrap aria-pressed:bg-ink aria-pressed:text-on-ink ${
              display ? "h-tap min-w-tap text-d-body" : "h-11 min-w-11 text-secondary"
            } ${worded ? (display ? "px-5" : "px-4") : ""}`}
          >
            <Icon aria-hidden="true" className={display ? "size-8" : "size-6"} />
            {worded ? <span aria-hidden="true">{name}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
