import { createLink } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ComponentPropsWithRef, ReactNode } from "react";

import { useShell } from "./shell";

interface RowParts {
  /** What a tap does, for screen readers: "Edit Mia". */
  label: string;
  /** An avatar, a color dot or an icon at the left. */
  leading?: ReactNode;
  title: ReactNode;
  subtitle?: string | null | undefined;
  /** The same line when it's more than words (trouble in its color): this shows, `subtitle` names. */
  subtitleShown?: ReactNode;
  /** A quiet word at the right, before the chevron: "On", "3 calendars". */
  value?: string | null | undefined;
}

/**
 * A row's name: what a tap does, then what else it shows ("Edit Mia, Child, Pink"). Voice control
 * goes by what's on the screen, so those are in the name, not only read after it (WCAG 2.5.3).
 */
function rowName({ label, subtitle, value }: Pick<RowParts, "label" | "subtitle" | "value">) {
  return [label, subtitle, value].filter(Boolean).join(", ");
}

function rowClass(display: boolean): string {
  return `press-row flex w-full items-center gap-4 text-left ${
    display ? "min-h-tap-primary py-2" : "min-h-14 py-2"
  }`;
}

function RowBody({ leading, title, subtitle, subtitleShown, value }: Omit<RowParts, "label">) {
  const display = useShell() === "display";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  return (
    <>
      {leading}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={`truncate font-semibold ${display ? "text-d-body" : "text-row"}`}>
          {title}
        </span>{" "}
        {subtitle ? <span className={soft}>{subtitleShown ?? subtitle}</span> : null}
      </span>{" "}
      {value ? <span className={`shrink-0 ${soft}`}>{value}</span> : null}
      <ChevronRight
        aria-hidden="true"
        className={`shrink-0 text-ink-soft ${display ? "size-8" : "size-5"}`}
      />
    </>
  );
}

/**
 * A row you tap to open what it names (UX §4 Settings): the whole row is the button, 64 px on
 * the wall and 56 on phones, with a chevron at its right. Its name says what the tap does ("Edit
 * Mia"), then what else it shows.
 */
export function ListRow({
  label,
  leading,
  title,
  subtitle,
  subtitleShown,
  value,
  ...props
}: RowParts & Omit<ComponentPropsWithRef<"button">, "title" | "children" | "className">) {
  const display = useShell() === "display";
  return (
    <button
      type="button"
      aria-label={rowName({ label, subtitle, value })}
      className={rowClass(display)}
      {...props}
    >
      <RowBody
        leading={leading}
        title={title}
        subtitle={subtitle}
        subtitleShown={subtitleShown}
        value={value}
      />
    </button>
  );
}

function RowAnchor({
  label,
  leading,
  title,
  subtitle,
  subtitleShown,
  value,
  className,
  ...props
}: RowParts & Omit<ComponentPropsWithRef<"a">, "title" | "children">) {
  const display = useShell() === "display";
  return (
    // The router's Link hands its own className down: merged after the spread, not replaced.
    <a
      {...props}
      aria-label={rowName({ label, subtitle, value })}
      className={`${rowClass(display)} ${className ?? ""}`}
    >
      <RowBody
        leading={leading}
        title={title}
        subtitle={subtitle}
        subtitleShown={subtitleShown}
        value={value}
      />
    </a>
  );
}

/** The same row as a link to another page (`to`, `params`, as the router's own Link). */
export const ListRowLink = createLink(RowAnchor);

/** The same row as a plain link to another website (`href`; Support Sunroom's Patreon). */
export const ListRowAnchor = RowAnchor;
