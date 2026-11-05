import { Fragment } from "react";

import { useArrived } from "../../lib/arrivals";
import {
  dayNumber,
  formatWallTime,
  monthYear,
  shortWeekday,
  type MonthGrid,
} from "../../lib/dates";
import type { Member } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { arrivalKey, PeopleEdge } from "./EventChip";
import { byDay, shownFor } from "./layout";
import { coreOverlayOf, useOverlayOf } from "./overlays";
import type { Occurrence } from "./types";

const SHOWN = 3;

/**
 * Month (UX §4): the month's name over the weekdays (the header doesn't say it: ADR 0030, and
 * the cells alone are bare numbers), then cells with the day number, up to three one-line
 * entries with a color bar and the person's initial, then "+N more". This week is lit a step and today two. A cell is one
 * button that opens its Day view, where every event is a full chip: three tappable entries
 * wouldn't fit a cell at the wall's tap-target size.
 */
export function MonthView({
  grid,
  today,
  occurrences,
  members,
  people,
  onDay,
}: {
  grid: MonthGrid;
  today: string;
  occurrences: Occurrence[];
  members: Member[];
  people: string[];
  onDay: (day: string) => void;
}) {
  const t = useT();
  const columns = byDay(occurrences, grid.days);
  const filter = new Set(people);
  const month = grid.first.slice(0, 7);
  return (
    <div className="flex min-h-0 flex-1 flex-col border-t border-line px-2 pb-2">
      {/* The room's h1 says it to a screen reader (shell/Header). */}
      <p aria-hidden="true" className="px-3 pt-3 pb-1 text-d-title leading-tight font-bold">
        {monthYear(grid.first)}
      </p>
      <div className="grid grid-cols-7 border-b border-line" aria-hidden="true">
        {(grid.weeks[0] ?? []).map((day) => (
          <span key={day} className="px-3 py-2 text-d-secondary font-semibold text-ink-soft">
            {shortWeekday(day)}
          </span>
        ))}
      </div>
      {/* The cells read as one control: neighbours touch, like a tab bar's. */}
      <div data-segmented="" className="grid min-h-0 flex-1 auto-rows-fr grid-cols-7">
        {grid.weeks.map((week) => {
          const thisWeek = week.includes(today);
          return week.map((day) => {
            const column = columns.get(day);
            const entries = [...(column?.allDay ?? []), ...(column?.timed ?? [])]
              .map((entry) => entry.occurrence)
              .filter((o) => shownFor(o, filter));
            const isToday = day === today;
            const inMonth = day.slice(0, 7) === month;
            const titles = cellWords(entries);
            return (
              <button
                key={day}
                type="button"
                onClick={() => {
                  onDay(day);
                }}
                aria-label={t("calendar.month.day.aria", {
                  weekday: shortWeekday(day),
                  day: dayNumber(day),
                  today: isToday ? "yes" : "no",
                  events: entries.length ? "yes" : "no",
                  titles,
                })}
                className={`press-row flex min-h-0 min-w-0 flex-col items-stretch gap-1 overflow-hidden border-r border-b border-line p-1.5 text-left ${
                  isToday ? "bg-lit" : thisWeek ? "bg-surface/50" : ""
                }`}
              >
                <span className={`px-1 text-d-title font-bold ${inMonth ? "" : "text-ink-soft"}`}>
                  <span
                    className={
                      isToday
                        ? "inline-flex size-[1.5em] items-center justify-center rounded-full bg-sun text-on-sun"
                        : ""
                    }
                  >
                    {dayNumber(day)}
                  </span>
                </span>{" "}
                {entries.slice(0, SHOWN).map((occurrence) => (
                  <Fragment key={occurrence.key}>
                    <MonthEntry occurrence={occurrence} members={members} />{" "}
                  </Fragment>
                ))}
                {entries.length > SHOWN ? (
                  <span className="px-1 text-d-caption font-semibold text-ink-soft">
                    {t("dates.more", { n: entries.length - SHOWN })}
                  </span>
                ) : null}
              </button>
            );
          });
        })}
      </div>
    </div>
  );
}

/** The time a month cell shows for an event: "8 AM", or none for an all-day one. */
function entryTime(occurrence: Occurrence): string | null {
  return !occurrence.all_day && occurrence.start_local
    ? formatWallTime(occurrence.start_local, { compact: true })
    : null;
}

/**
 * What a month cell's name lists: what it shows, in that order ("8 AM Vet, +2 more", for voice
 * control: WCAG 2.5.3), then the events it had no room for, which only the ear gets.
 */
function cellWords(entries: Occurrence[]): string {
  const shown = entries
    .slice(0, SHOWN)
    .map((o) => [entryTime(o), o.title].filter(Boolean).join(" "));
  const rest = entries.slice(SHOWN).map((o) => o.title);
  if (rest.length === 0) return shown.join(", ");
  return `${[...shown, t("dates.more", { n: rest.length })].join(", ")}: ${rest.join(", ")}`;
}

function MonthEntry({ occurrence, members }: { occurrence: Occurrence; members: Member[] }) {
  const overlay = useOverlayOf(occurrence);
  const arrive = useArrived(arrivalKey(occurrence)) ? "" : undefined;
  if (overlay) {
    const Icon = overlay.icon;
    return (
      <span
        aria-hidden="true"
        data-arrive={arrive}
        data-overlay={occurrence.overlay ?? undefined}
        className="flex min-w-0 items-center gap-1.5 px-1.5 text-d-caption text-ink-soft"
      >
        <Icon className="size-4 shrink-0" strokeWidth={2.25} />
        <span className="min-w-0 truncate">{occurrence.title}</span>
      </span>
    );
  }
  const people = members.filter((m) => occurrence.member_ids.includes(m.id));
  const color = occurrence.color ?? (people.length === 1 ? people[0]?.color : null) ?? "everyone";
  const time = entryTime(occurrence);
  const initial = people.length === 1 ? (people[0]?.name.charAt(0) ?? "") : "";
  const Mark = coreOverlayOf(occurrence)?.icon;
  // Several people and no color of its own: the 4 px bar in each of their colors (ADR 0034).
  const several = !occurrence.color && people.length > 1;
  return (
    <span
      aria-hidden="true"
      data-person={color}
      data-arrive={arrive}
      data-overlay={occurrence.overlay ?? undefined}
      className={`flex min-w-0 items-center gap-1.5 rounded-sm bg-p-tint pr-1.5 text-d-caption ${
        several ? "relative overflow-hidden pl-2.5" : "border-l-4 border-p pl-1.5"
      }`}
    >
      {several ? (
        <PeopleEdge colors={people.map((person) => person.color)} className="w-1 rounded-sm" />
      ) : null}
      {/* CSS content, as on an avatar: decoration beside the words, not part of them. */}
      {initial ? (
        <span
          data-initial={initial}
          className="font-bold text-p-text before:content-[attr(data-initial)]"
        />
      ) : null}
      {time ? <span className="font-semibold whitespace-nowrap">{time}</span> : null}{" "}
      {Mark ? <Mark className="size-4 shrink-0" strokeWidth={2.25} /> : null}
      <span className="min-w-0 truncate">{occurrence.title}</span>
    </span>
  );
}
