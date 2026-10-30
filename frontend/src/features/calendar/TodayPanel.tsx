import { useNavigate, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { addDays, formatWallTime, wallNow, zonedParts } from "../../lib/dates";
import { updateDisplay } from "../../lib/displayState";
import { useMembers, type Member } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Avatar } from "../../ui/Avatar";
import { useTodayBlocks } from "../usePluginModules";
import { PeopleEdge, peopleOf } from "./EventChip";
import { useOccurrences } from "./data";
import { byDay, todayParts } from "./layout";
import type { Occurrence } from "./types";

const TOMORROW_FROM_HOUR = 18;

/** An event's sheet opens on the board: from another room, go there first. */
function useOpenEvent(home: "/display" | "/") {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return (occurrence: Occurrence) => {
    if (!occurrence.event_id) return;
    updateDisplay({
      panel: {
        kind: "event",
        eventId: occurrence.event_id,
        recurrenceId: occurrence.recurrence_id ?? null,
        key: occurrence.key,
      },
    });
    if (pathname !== home) void navigate({ to: home });
  };
}

const startText = (occurrence: Occurrence) =>
  occurrence.all_day || !occurrence.start_local
    ? t("calendar.today.all_day")
    : formatWallTime(occurrence.start_local);

/**
 * The display's Today panel (UX §3): Now, Up next, Later today and, after 6 PM, Tomorrow, each
 * only with something in it, then each enabled plugin's blocks (Chores today, To do…) in their
 * order. Now and Up next are glance-sized. Tapping a line opens its event on the board.
 */
export function TodayPanel({
  home,
  band = false,
}: {
  home: "/display" | "/";
  /** Portrait's band across the top: the blocks flow into three columns (UX §3). */
  band?: boolean;
}) {
  const t = useT();
  const open = useOpenEvent(home);
  const blocks = useTodayBlocks();
  const minute = useMinute();
  const now = wallNow(minute);
  const { day: today, hour } = zonedParts(minute);
  const tomorrow = addDays(today, 1);
  const { data } = useOccurrences(today, addDays(today, 2));
  const { data: members = [] } = useMembers();
  const occurrences = data?.occurrences ?? [];
  const parts = todayParts(occurrences, now);
  const next = byDay(occurrences, [tomorrow]).get(tomorrow);
  const tomorrows = [...(next?.allDay ?? []), ...(next?.timed ?? [])].map((e) => e.occurrence);
  const todays = byDay(occurrences, [today]).get(today);
  const hadToday = (todays?.allDay.length ?? 0) + (todays?.timed.length ?? 0) > 0;
  const nothingLeft = !parts.upNext && !parts.later.length;
  const onNow = parts.now.length > 0 || parts.allDay.length > 0;
  const showTomorrow = hour >= TOMORROW_FROM_HOUR && tomorrows.length > 0;
  const firstTomorrow = next?.timed[0]?.occurrence ?? next?.allDay[0]?.occurrence;

  return (
    <aside
      aria-label={t("calendar.today.panel.aria")}
      className={
        band
          ? "grid min-h-0 flex-1 grid-cols-3 gap-x-10 overflow-hidden px-6 pt-3 pb-4"
          : "flex min-h-0 flex-1 flex-col gap-8 overflow-y-auto px-6 py-6"
      }
    >
      {/* Portrait's band: the calendar's lines in the first column, the plugins' blocks flowing
          through the other two. On the side panel both are simply one column. */}
      <div className={band ? "flex min-h-0 flex-col gap-5 overflow-hidden" : "contents"}>
        {parts.now.length || parts.allDay.length ? (
          <Section id="today-now" title={t("calendar.today.now.title")}>
            {parts.now.map((occurrence) => (
              <Line
                onOpen={open}
                key={occurrence.key}
                occurrence={occurrence}
                members={members}
                when={
                  occurrence.end_local
                    ? t("calendar.today.until", { time: formatWallTime(occurrence.end_local) })
                    : ""
                }
                glance
              />
            ))}
            {parts.allDay.map((occurrence) => (
              <Line
                key={occurrence.key}
                onOpen={open}
                occurrence={occurrence}
                members={members}
                when={t("calendar.today.all_day")}
              />
            ))}
          </Section>
        ) : null}
        {parts.upNext ? (
          <Section id="today-up-next" title={t("calendar.today.up_next.title")}>
            <Line
              onOpen={open}
              occurrence={parts.upNext}
              members={members}
              when={startText(parts.upNext)}
              glance
              detail
            />
          </Section>
        ) : null}
        {parts.later.length ? (
          <Section id="today-later" title={t("calendar.today.later.title")}>
            {parts.later.map((occurrence) => (
              <Line
                onOpen={open}
                key={occurrence.key}
                occurrence={occurrence}
                members={members}
                when={startText(occurrence)}
              />
            ))}
          </Section>
        ) : null}
        {nothingLeft ? (
          <div className="flex flex-col gap-2">
            {/* Glance-sized when it's all there is; quieter under what's on now. */}
            <p
              className={
                onNow ? "text-d-body font-semibold text-ink-soft" : "text-d-glance font-bold"
              }
            >
              {hadToday ? t("calendar.today.nothing_else") : t("calendar.today.empty")}
            </p>
            {!showTomorrow && firstTomorrow ? (
              <p className="text-d-secondary text-ink-soft">
                {t("calendar.today.tomorrow_first", {
                  time: startText(firstTomorrow),
                  title: firstTomorrow.title,
                })}
              </p>
            ) : null}
          </div>
        ) : null}
        {showTomorrow ? (
          <Section id="today-tomorrow" title={t("calendar.today.tomorrow.title")}>
            {tomorrows.map((occurrence) => (
              <Line
                onOpen={open}
                key={occurrence.key}
                occurrence={occurrence}
                members={members}
                when={startText(occurrence)}
              />
            ))}
          </Section>
        ) : null}
      </div>
      <div
        className={
          band
            ? "col-span-2 h-full columns-2 gap-x-10 overflow-hidden [column-fill:auto] *:mb-2 *:break-inside-avoid"
            : "contents"
        }
      >
        {blocks.map(({ key, Display }) => (Display ? <Display key={key} band={band} /> : null))}
      </div>
    </aside>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h2 id={id} className="text-d-body font-bold text-ink-soft">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * One event in the panel. Glance lines (Now, Up next) put the title at 40 px on its own line,
 * never truncated (UX §1); the others read time and title on one row.
 */
function Line({
  occurrence,
  members,
  when,
  glance = false,
  detail = false,
  onOpen,
}: {
  onOpen: (occurrence: Occurrence) => void;
  occurrence: Occurrence;
  members: Member[];
  when: string;
  glance?: boolean;
  detail?: boolean;
}) {
  const t = useT();
  const people = peopleOf(occurrence, members);
  const who = people.length ? people.map((p) => p.name).join(", ") : t("calendar.everyone");
  const extra = detail ? [who, occurrence.location].filter(Boolean).join(" · ") : "";
  return (
    <button
      type="button"
      data-person={occurrence.color ?? (people.length === 1 ? people[0]?.color : "everyone")}
      onClick={() => {
        onOpen(occurrence);
      }}
      className="press-row -mx-3 flex min-h-16 items-start gap-3 rounded-chip-d px-3 py-2 text-left"
    >
      {/* Several people, and no color of its own: the pill in each of their colors (ADR 0034). */}
      {!occurrence.color && people.length > 1 ? (
        <PeopleEdge
          colors={people.map((person) => person.color)}
          className="static mt-1.5 h-[1.25em] w-1.5 shrink-0 rounded-full"
        />
      ) : (
        <span aria-hidden="true" className="mt-1.5 h-[1.25em] w-1.5 shrink-0 rounded-full bg-p" />
      )}
      {glance ? (
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-d-body font-semibold">{when}</span>
          <span className="text-d-glance font-bold break-words">{occurrence.title}</span>
          {extra ? <span className="text-d-secondary text-ink-soft">{extra}</span> : null}
        </span>
      ) : (
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-d-secondary font-semibold text-ink-soft">{when}</span>
          <span className="text-d-body font-semibold break-words">{occurrence.title}</span>
        </span>
      )}
      {people.length && !detail ? (
        <span className="flex shrink-0 -space-x-2 pt-1">
          {people.slice(0, 3).map((member) => (
            <Avatar key={member.id} member={member} size="sm" />
          ))}
        </span>
      ) : null}
    </button>
  );
}
