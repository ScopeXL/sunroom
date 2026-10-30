import { ArrowRight } from "lucide-react";
import type { CSSProperties } from "react";

import { useArrived } from "../../lib/arrivals";
import { formatWallRange, formatWallTime, longMonthDay, longWeekday } from "../../lib/dates";
import type { Member } from "../../lib/household";
import { t } from "../../lib/lang";
import { Avatar } from "../../ui/Avatar";
import { useShell } from "../../ui/shell";
import { isOn, isPast } from "./layout";
import { coreOverlayOf, useOverlayOf } from "./overlays";
import type { Occurrence, PersonColor } from "./types";

/** "4:00 to 5:00 PM": a range as a screen reader says it, the dash in words. */
function spokenRange(range: string): string {
  const dash = range.indexOf("–");
  if (dash === -1) return range;
  return t("calendar.chip.range.aria", { start: range.slice(0, dash), end: range.slice(dash + 1) });
}

/** "Soccer practice, 4:00 to 5:00 PM, Mia, Thursday October 9" (UX §10). */
export function occurrenceLabel(occurrence: Occurrence, people: Member[], day?: string): string {
  const when = occurrence.all_day
    ? t("calendar.board.all_day")
    : occurrence.start_local && occurrence.end_local
      ? spokenRange(formatWallRange(occurrence.start_local, occurrence.end_local))
      : "";
  const who = people.length ? people.map((p) => p.name).join(", ") : t("calendar.everyone");
  const onDay = day ?? occurrence.start_date ?? occurrence.start_local?.slice(0, 10) ?? "";
  const date = onDay ? `${longWeekday(onDay)} ${longMonthDay(onDay)}` : "";
  return [occurrence.title, when, who, date].filter(Boolean).join(", ");
}

/** What makes a chip a newcomer (lib/arrivals): the event, where it now starts. Moved to
 * another day or time, it arrives there. */
export function arrivalKey(occurrence: Occurrence): string {
  return `${occurrence.key}@${occurrence.start_local ?? occurrence.start_date ?? ""}`;
}

export function peopleOf(occurrence: Occurrence, members: Member[]): Member[] {
  return members.filter((member) => occurrence.member_ids.includes(member.id));
}

/** How many people's colors one bar holds; the rest still have their avatars and names. */
const EDGE_MAX = 4;

/**
 * How an event's chip is painted (UX §4 "Week board"), in either Week layout: one person's light
 * tint and a 6 px bar at the left; a neutral tint for several people, with the bar in equal
 * segments of their colors (`edge`, up to four, in household order: ADR 0034), and for
 * Everyone; filled solid while it's on; no tint and quiet text once it's over today (when the
 * household dims the past). An event with a color of its own keeps that color.
 */
export function chipTone(
  occurrence: Occurrence,
  people: Member[],
  now: string,
  dimPast: boolean,
  /** A past chip's fill: none on the Agenda (its text shows it); the Hours grid's thin blocks
   * need a faint one to show at all. */
  pastFill = "bg-transparent",
): { person: string; className: string; edge: PersonColor[] | null } {
  const one = people.length === 1 ? people[0] : undefined;
  const on = isOn(occurrence, now);
  const past = dimPast && !on && isPast(occurrence, now);
  const color = occurrence.color ?? one?.color ?? null;
  const fill = on
    ? color
      ? "bg-p text-on-ink"
      : "bg-ink text-on-ink"
    : past
      ? `${pastFill} text-ink-soft`
      : color
        ? "bg-p-tint text-ink"
        : "bg-line/60 text-ink";
  const edge =
    !color && !on && !past && people.length > 1
      ? people.slice(0, EDGE_MAX).map((person) => person.color)
      : null;
  return {
    person: on && !color ? "everyone" : (color ?? "everyone"),
    className: `${fill} ${color && !past ? "border-l-[6px] border-p pl-3" : edge ? "pl-[18px]" : "pl-3"}`,
    edge,
  };
}

/**
 * Several people's colors as one bar (UX §4, ADR 0034): equal segments of their solids, top to
 * bottom in household order, where one person's chip has its 6 px edge. The tint stays neutral
 * (two tints mixed read as mud) and the names are on the chip anyway: color is never the only
 * signal (UX §10). Placed at the left of a `relative` box unless `className` says otherwise.
 */
export function PeopleEdge({
  colors,
  className = "w-[6px]",
}: {
  colors: readonly PersonColor[];
  className?: string;
}) {
  const shown = colors.slice(0, EDGE_MAX);
  const style = Object.fromEntries(
    shown.map((color, index) => [
      `--seg-${String(index + 1)}`,
      `light-dark(var(--${color}-l), var(--${color}-d))`,
    ]),
  ) as CSSProperties;
  return (
    <span
      aria-hidden="true"
      data-edge={shown.length}
      className={`edge edge-${String(shown.length)} ${className}`}
      style={style}
    />
  );
}

/**
 * An event on the board (UX §4 "Week board"). One person: a light tint of their color and a
 * 6 px bar at the left; several: a neutral tint, the bar in each of their colors and up to three
 * avatars; Everyone: neutral. On now: filled solid. Past (today): no tint, quiet text, when the
 * household dims past events.
 */
export function EventChip({
  occurrence,
  members,
  now,
  dimPast,
  continues = false,
  compact = false,
  day,
  measuring = false,
  onOpen,
}: {
  occurrence: Occurrence;
  members: Member[];
  now: string;
  dimPast: boolean;
  continues?: boolean;
  /** Time and title on one row, the title on up to two lines (the all-day band, Who's doing
   * what). */
  compact?: boolean;
  day?: string;
  /** An invisible copy for measuring: not focusable. */
  measuring?: boolean;
  onOpen: () => void;
}) {
  const display = useShell() === "display";
  const people = peopleOf(occurrence, members);
  const overlay = useOverlayOf(occurrence);
  const arrive = useArrived(arrivalKey(occurrence)) && !measuring ? "" : undefined;
  if (overlay) {
    // A plugin's (a day's dinner, a countdown): quiet, with its mark; a tap opens its room.
    const Icon = overlay.icon;
    return (
      <button
        type="button"
        data-chip=""
        data-arrive={arrive}
        data-overlay={occurrence.overlay ?? undefined}
        data-key={occurrence.key}
        aria-label={occurrenceLabel(occurrence, people, day)}
        tabIndex={measuring ? -1 : undefined}
        onClick={onOpen}
        className={`press flex w-full min-w-0 items-center gap-2 border border-line bg-surface/50 px-3 py-1.5 text-left text-ink ${
          display ? "min-h-tap rounded-chip-d" : "min-h-11 rounded-chip"
        }`}
      >
        <Icon aria-hidden="true" className="size-5 shrink-0 text-ink-soft" strokeWidth={2.25} />
        <span
          className={`line-clamp-2 min-w-0 flex-1 break-words ${display ? "text-d-secondary" : "text-secondary"} font-semibold`}
        >
          {occurrence.title}
        </span>
        <PeopleMarks people={people} />
      </button>
    );
  }
  const tone = chipTone(occurrence, people, now, dimPast);
  const time =
    !occurrence.all_day && occurrence.start_local ? formatWallTime(occurrence.start_local) : null;
  // A core overlay's mark before the title: a birthday's cake (ADR 0028).
  const Mark = coreOverlayOf(occurrence)?.icon;
  return (
    <button
      type="button"
      data-person={tone.person}
      data-chip=""
      data-arrive={arrive}
      data-overlay={occurrence.overlay ?? undefined}
      data-key={occurrence.key}
      aria-label={occurrenceLabel(occurrence, people, day)}
      tabIndex={measuring ? -1 : undefined}
      onClick={onOpen}
      className={`press relative flex w-full min-w-0 flex-col gap-0.5 overflow-hidden py-2 pr-2 text-left ${
        display ? "rounded-chip-d" : "rounded-chip"
      } ${tone.className} ${compact ? `${display ? "min-h-tap" : "min-h-11"} justify-center` : display ? "min-h-16" : "min-h-14"}`}
    >
      {compact || !time ? (
        <span className="flex min-w-0 items-center gap-2">
          {time ? (
            <span
              className={`${display ? "text-d-secondary" : "text-secondary"} font-semibold whitespace-nowrap`}
            >
              {time}
            </span>
          ) : null}
          {Mark ? (
            <Mark
              aria-hidden="true"
              className={`${display ? "size-6" : "size-5"} shrink-0`}
              strokeWidth={2.25}
            />
          ) : null}
          <span
            className={`line-clamp-2 min-w-0 flex-1 break-words ${display ? "text-d-body" : "text-body"} font-semibold`}
          >
            {occurrence.title}
          </span>
          {continues ? <ArrowRight aria-hidden="true" className="size-6 shrink-0" /> : null}
          {/* A birthday's title names its person ("Mia's birthday"): no avatar, so it fits. */}
          {Mark ? null : <PeopleMarks people={people} />}
        </span>
      ) : (
        <>
          <span className="flex items-center justify-between gap-2">
            <span
              className={`${display ? "text-d-secondary" : "text-secondary"} font-semibold whitespace-nowrap`}
            >
              {time}
            </span>
            <PeopleMarks people={people} />
          </span>
          <span
            className={`line-clamp-2 ${display ? "text-d-body" : "text-body"} font-semibold break-words`}
          >
            {occurrence.title}
            {continues ? " →" : ""}
          </span>
        </>
      )}
      {tone.edge ? <PeopleEdge colors={tone.edge} /> : null}
      {occurrence.is_override ? (
        <span
          aria-hidden="true"
          className="absolute top-1.5 right-1.5 size-2.5 rounded-full bg-sun-ink"
        />
      ) : null}
    </button>
  );
}

/** Up to three avatars, overlapping: who an event is for. */
export function PeopleMarks({ people }: { people: Member[] }) {
  if (people.length === 0) return null;
  return (
    <span className="flex shrink-0 -space-x-2">
      {people.slice(0, 3).map((member) => (
        <Avatar key={member.id} member={member} size="xs" />
      ))}
    </span>
  );
}
