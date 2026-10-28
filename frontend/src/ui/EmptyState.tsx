import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useShell } from "./shell";

/**
 * An empty room teaches (UX §8, ADR 0032): an icon in a soft circle, a short line saying
 * nothing's here yet, a note on what goes here, and the one big button that starts it, all
 * centred. On the wall it fills the room's height and sits in its middle; on a phone it starts a
 * third of the way down, and the screen's bottom bar already holds the button, so phone screens
 * pass no action.
 */
export function EmptyState({
  icon: Icon,
  line,
  note,
  action,
}: {
  icon: LucideIcon;
  /** "No lists yet": empty-state copy, so sentence case (UX §2). */
  line: string;
  note?: string;
  /** The one button: a primary `Button`, or what stands in for it (the wall screen's QR). */
  action?: ReactNode;
}) {
  const display = useShell() === "display";
  return (
    <section
      data-empty=""
      className={`flex flex-col items-center text-center ${
        display ? "min-h-full flex-1 justify-center gap-5 py-12" : "gap-3 pt-12 pb-6"
      }`}
    >
      <span
        className={`grid shrink-0 place-items-center rounded-full bg-lit text-ink-soft ${
          display ? "size-28" : "size-20"
        }`}
      >
        <Icon aria-hidden="true" className={display ? "size-14" : "size-10"} />
      </span>
      <p className={display ? "text-d-title font-bold" : "text-row font-bold"}>{line}</p>
      {note ? (
        <p
          className={`max-w-prose text-ink-soft ${display ? "text-d-secondary" : "text-secondary"}`}
        >
          {note}
        </p>
      ) : null}
      {action ? <div className={display ? "pt-3" : "pt-1"}>{action}</div> : null}
    </section>
  );
}

/** A quiet line where something is empty but isn't a room: a list with no items yet. */
export function QuietLine({ children }: { children: ReactNode }) {
  const display = useShell() === "display";
  return (
    <p className={display ? "py-6 text-d-body font-semibold" : "py-4 text-row font-semibold"}>
      {children}
    </p>
  );
}
