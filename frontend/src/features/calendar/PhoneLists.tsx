import { useArrived } from "../../lib/arrivals";
import { useState } from "react";

import {
  addDays,
  dayNumber,
  formatWallTime,
  shortDate,
  shortWeekday,
  wallNow,
  type MonthGrid,
} from "../../lib/dates";
import type { Member } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { cellDate } from "../../ui/WeekStrip";
import { arrivalKey, occurrenceLabel, PeopleEdge, peopleOf } from "./EventChip";
import { coreOverlayOf, useOverlayOf } from "./overlays";
import { byDay, isPast, shownFor } from "./layout";
import type { Occurrence } from "./types";

const DOTS = 4;

function dayTitle(day: string, today: string): string {
  if (day === today) return t("calendar.phone.day.today", { date: shortDate(day) });
  if (day === addDays(today, 1)) return t("calendar.phone.day.tomorrow", { date: shortDate(day) });
  return shortDate(day);
}

/** A day cell's name: "Thu 8, October, today, 2 events". */
function dayCellLabel(day: string, today: string, count: number): string {
  return t("calendar.phone.day.aria", {
    date: cellDate(day),
    today: day === today ? "yes" : "no",
    n: count,
  });
}

/** One event in a phone list (UX §5): time, title and people, the place underneath. */
export function PhoneRow({
  occurrence,
  members,
  dim,
  day,
  when,
  onOpen,
}: {
  occurrence: Occurrence;
  members: Member[];
  dim: boolean;
  /** The day it's listed under (a span shows on each of its days). */
  day?: string;
  /** In place of the start time ("until 4:15 PM" for what's on now). */
  when?: string;
  onOpen: () => void;
}) {
  const t = useT();
  const people = peopleOf(occurrence, members);
  const overlay = useOverlayOf(occurrence);
  const arrived = useArrived(arrivalKey(occurrence));
  const Mark = overlay?.icon;
  // A birthday keeps its person's bar, with a cake before its title (ADR 0028).
  const TitleMark = coreOverlayOf(occurrence)?.icon;
  const color = occurrence.color ?? (people.length === 1 ? people[0]?.color : null) ?? "everyone";
  const time =
    when ??
    (occurrence.all_day || !occurrence.start_local
      ? t("calendar.board.all_day")
      : formatWallTime(occurrence.start_local));
  return (
    <button
      type="button"
      data-person={color}
      data-arrive={arrived ? "" : undefined}
      aria-label={occurrenceLabel(occurrence, people, day, { when, location: true })}
      onClick={onOpen}
      className={`press-row flex min-h-14 w-full items-start gap-3 rounded-chip px-2 py-2 text-left ${
        dim ? "text-ink-soft" : ""
      }`}
    >
      <span className="w-[4.75rem] shrink-0 pt-0.5 text-secondary font-semibold">{time}</span>{" "}
      {Mark ? (
        <Mark aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ink-soft" />
      ) : !occurrence.color && people.length > 1 ? (
        // Several people: the bar in each of their colors (ADR 0034).
        <PeopleEdge
          colors={people.map((person) => person.color)}
          className="static w-1 shrink-0 self-stretch rounded-full"
        />
      ) : (
        <span aria-hidden="true" className="w-1 shrink-0 self-stretch rounded-full bg-p" />
      )}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-body font-semibold break-words">
          {TitleMark ? (
            <TitleMark
              aria-hidden="true"
              className="mr-1.5 inline size-5 align-[-0.2em]"
              strokeWidth={2.25}
            />
          ) : null}
          {occurrence.title}
          {people.length ? (
            <span className="font-normal text-ink-soft">
              {" · "}
              {people.map((p) => p.name).join(", ")}
            </span>
          ) : null}
        </span>{" "}
        {occurrence.location ? (
          <span className="text-secondary text-ink-soft">{occurrence.location}</span>
        ) : null}
      </span>
    </button>
  );
}

/** "─── now 9:41 AM ───" between what's over and what's to come. */
function NowLine() {
  const t = useT();
  const now = useMinute();
  return (
    <div aria-hidden="true" className="flex items-center gap-2 py-1">
      <span className="h-0.5 flex-1 rounded-full bg-sun-ink" />
      <span className="text-secondary font-semibold text-sun-ink">
        {t("calendar.board.now", { time: formatWallTime(wallNow(now)) })}
      </span>
      <span className="h-0.5 flex-1 rounded-full bg-sun-ink" />
    </div>
  );
}

/**
 * Events grouped by day (UX §5 Week and Agenda): "Tue, Oct 7 · today", then its events, with the
 * now line in today's group. Days without events are left out unless `keepEmpty`.
 */
export function DayGroups({
  days,
  today,
  now,
  occurrences,
  members,
  people,
  dimPast,
  keepEmpty = false,
  onOpen,
}: {
  days: readonly string[];
  today: string;
  now: string;
  occurrences: readonly Occurrence[];
  members: Member[];
  people: readonly string[];
  dimPast: boolean;
  keepEmpty?: boolean;
  onOpen: (occurrence: Occurrence) => void;
}) {
  const t = useT();
  const filter = new Set(people);
  const columns = byDay(
    occurrences.filter((o) => shownFor(o, filter)),
    days,
  );
  return (
    <div className="flex flex-col gap-5">
      {days.map((day) => {
        const column = columns.get(day);
        const items = [...(column?.allDay ?? []), ...(column?.timed ?? [])].map(
          (e) => e.occurrence,
        );
        if (!items.length && !keepEmpty && day !== today) return null;
        const isToday = day === today;
        let nowAt = -1;
        if (isToday) {
          nowAt = items.findIndex((o) => !o.all_day && !isPast(o, now));
          if (nowAt === -1) nowAt = items.length;
        }
        return (
          <section key={day} aria-label={dayTitle(day, today)} className="flex flex-col gap-1">
            <h2 className={`text-row font-bold ${isToday ? "" : "text-ink"}`}>
              {dayTitle(day, today)}
            </h2>
            <ul className="flex flex-col">
              {items.map((occurrence, index) => (
                <li key={occurrence.key}>
                  {index === nowAt ? <NowLine /> : null}
                  <PhoneRow
                    occurrence={occurrence}
                    members={members}
                    day={day}
                    dim={dimPast && isToday && isPast(occurrence, now)}
                    onOpen={() => {
                      onOpen(occurrence);
                    }}
                  />
                </li>
              ))}
              {nowAt === items.length ? (
                <li aria-hidden="true">
                  <NowLine />
                </li>
              ) : null}
              {!items.length ? (
                <li className="px-2 py-2 text-secondary text-ink-soft">
                  {t("calendar.phone.day.empty")}
                </li>
              ) : null}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** An event's dot color: its own, its one person's, or the neutral one ("everyone"). */
function dotColor(occurrence: Occurrence, members: Member[]): string {
  const people = peopleOf(occurrence, members);
  return occurrence.color ?? (people.length === 1 ? people[0]?.color : null) ?? "everyone";
}

/** Up to four person-colored dots for a day's events. */
function Dots({ items, members }: { items: Occurrence[]; members: Member[] }) {
  return (
    <span aria-hidden="true" className="flex h-2 items-center gap-0.5">
      {items.slice(0, DOTS).map((occurrence) => (
        <span
          key={occurrence.key}
          data-person={dotColor(occurrence, members)}
          className="size-1.5 rounded-full bg-p"
        />
      ))}
    </span>
  );
}

/** The Week strip (UX §5): seven 44 px day cells with person-colored dots; one is chosen. */
export function WeekStrip({
  days,
  today,
  selected,
  occurrences,
  members,
  people,
  onSelect,
}: {
  days: readonly string[];
  today: string;
  selected: string;
  occurrences: readonly Occurrence[];
  members: Member[];
  people: readonly string[];
  onSelect: (day: string) => void;
}) {
  const t = useT();
  const filter = new Set(people);
  const columns = byDay(
    occurrences.filter((o) => shownFor(o, filter)),
    days,
  );
  return (
    <div
      role="group"
      aria-label={t("calendar.phone.days.aria")}
      data-segmented=""
      className="grid grid-cols-7 gap-1"
    >
      {days.map((day) => {
        const column = columns.get(day);
        const items = [...(column?.allDay ?? []), ...(column?.timed ?? [])].map(
          (e) => e.occurrence,
        );
        const isToday = day === today;
        return (
          <button
            key={day}
            type="button"
            aria-pressed={day === selected}
            aria-label={dayCellLabel(day, today, items.length)}
            onClick={() => {
              onSelect(day);
            }}
            className="press flex min-h-16 flex-col items-center justify-center gap-0.5 rounded-chip border-2 border-transparent aria-pressed:border-ink"
          >
            <span className="text-caption text-ink-soft">{shortWeekday(day)}</span>{" "}
            <span
              className={`flex size-7 items-center justify-center rounded-full text-secondary font-bold ${
                isToday ? "bg-sun text-on-sun" : ""
              }`}
            >
              {dayNumber(day)}
            </span>
            <Dots items={items} members={members} />
          </button>
        );
      })}
    </div>
  );
}

/** Month on a phone (UX §5): a grid with dots; the chosen day's list sits under it. */
export function PhoneMonth({
  grid,
  today,
  selected,
  occurrences,
  members,
  people,
  onSelect,
}: {
  grid: MonthGrid;
  today: string;
  selected: string;
  occurrences: readonly Occurrence[];
  members: Member[];
  people: readonly string[];
  onSelect: (day: string) => void;
}) {
  const t = useT();
  const filter = new Set(people);
  const columns = byDay(
    occurrences.filter((o) => shownFor(o, filter)),
    grid.days,
  );
  const month = grid.first.slice(0, 7);
  return (
    <div className="flex flex-col gap-1">
      <div aria-hidden="true" className="grid grid-cols-7">
        {(grid.weeks[0] ?? []).map((day) => (
          <span key={day} className="text-center text-caption text-ink-soft">
            {shortWeekday(day)}
          </span>
        ))}
      </div>
      <div
        role="group"
        aria-label={t("calendar.phone.days.aria")}
        data-segmented=""
        className="grid grid-cols-7 gap-1"
      >
        {grid.days.map((day) => {
          const column = columns.get(day);
          const items = [...(column?.allDay ?? []), ...(column?.timed ?? [])].map(
            (e) => e.occurrence,
          );
          const isToday = day === today;
          return (
            <button
              key={day}
              type="button"
              aria-pressed={day === selected}
              aria-label={dayCellLabel(day, today, items.length)}
              onClick={() => {
                onSelect(day);
              }}
              className={`press flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-chip border-2 border-transparent aria-pressed:border-ink ${
                day.slice(0, 7) === month ? "" : "text-ink-soft"
              }`}
            >
              <span
                className={`flex size-7 items-center justify-center rounded-full text-secondary font-semibold ${
                  isToday ? "bg-sun font-bold text-on-sun" : ""
                }`}
              >
                {dayNumber(day)}
              </span>
              <Dots items={items} members={members} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Agenda (UX §5): the list grouped by day from today on; the past days of the range fold into
 * "Earlier".
 */
export function Agenda({
  days,
  today,
  now,
  occurrences,
  members,
  people,
  dimPast,
  onOpen,
}: {
  days: readonly string[];
  today: string;
  now: string;
  occurrences: readonly Occurrence[];
  members: Member[];
  people: readonly string[];
  dimPast: boolean;
  onOpen: (occurrence: Occurrence) => void;
}) {
  const t = useT();
  const [earlier, setEarlier] = useState(false);
  const past = days.filter((day) => day < today);
  const coming = days.filter((day) => day >= today);
  return (
    <div className="flex flex-col gap-5">
      {past.length ? (
        <div className="flex flex-col gap-4">
          <button
            type="button"
            aria-expanded={earlier}
            onClick={() => {
              setEarlier(!earlier);
            }}
            className="press-row flex min-h-11 items-center rounded-chip px-2 text-left text-secondary font-semibold text-ink-soft"
          >
            {earlier ? t("calendar.phone.earlier.hide") : t("calendar.phone.earlier.show")}
          </button>
          {earlier ? (
            <DayGroups
              days={past}
              today={today}
              now={now}
              occurrences={occurrences}
              members={members}
              people={people}
              dimPast={dimPast}
              onOpen={onOpen}
            />
          ) : null}
        </div>
      ) : null}
      <DayGroups
        days={coming}
        today={today}
        now={now}
        occurrences={occurrences}
        members={members}
        people={people}
        dimPast={dimPast}
        onOpen={onOpen}
      />
    </div>
  );
}
