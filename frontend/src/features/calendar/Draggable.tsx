import { useDraggable } from "@dnd-kit/core";
import type { CSSProperties, ReactNode } from "react";

import { useT } from "../../lib/lang";
import type { DayEntry } from "./layout";
import type { Occurrence } from "./types";

/**
 * A chip that a long press lifts to drag to another day (UX §6), in either Week layout. What
 * can't move (a read-only calendar's event, a plugin's or a birthday's chip) stays put. The Hours
 * grid passes `className` and `style` to make it the chip's positioned box.
 */
export function Draggable({
  entry,
  day,
  faded,
  lifted,
  className = "",
  style,
  children,
}: {
  entry: DayEntry<Occurrence>;
  day: string;
  faded: boolean;
  lifted: Occurrence | null;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const fixed = entry.occurrence.read_only || entry.occurrence.overlay !== null;
  const { setNodeRef, listeners, attributes } = useDraggable({
    id: `${entry.occurrence.key}|${day}`,
    data: { occurrence: entry.occurrence, day },
    disabled: fixed,
  });
  const origin = lifted?.key === entry.occurrence.key;
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      // The chip inside is the control: dnd-kit's attributes would make this box a second one,
      // and its aria-disabled (on what can't move) would mark the chip itself unavailable.
      role={undefined}
      tabIndex={undefined}
      aria-roledescription={undefined}
      aria-describedby={undefined}
      aria-disabled={undefined}
      style={style}
      className={`rounded-chip-d ${faded ? "opacity-30" : ""} ${
        origin ? "opacity-50 outline-2 outline-ink-soft outline-dashed" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

/** "+3 more": the day's chips that don't fit, a tap away in the Day view. */
export function MoreButton({
  count,
  day,
  onMore,
}: {
  count: number;
  day: string;
  onMore: (day: string) => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() => {
        onMore(day);
      }}
      // In portrait's rows it's only as wide as its words, so another chip fits on its line.
      className="press min-h-tap w-full rounded-chip-d px-3 text-left text-d-secondary font-semibold whitespace-nowrap text-ink-soft portrait:w-auto portrait:px-5"
    >
      {t("dates.more", { n: count })}
    </button>
  );
}
