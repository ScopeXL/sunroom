import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";

import { qk } from "../../api/keys";
import { addDays, formatWallTime, shortDate, wallNow, zonedParts } from "../../lib/dates";
import type { BoardPanel } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { fetchSession } from "../../lib/session";
import { useMinute } from "../../lib/time";
import { ActionBar } from "../../ui/ActionBar";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { AddPanel } from "../calendar/AddPanel";
import { useOccurrences } from "../calendar/data";
import { peopleOf } from "../calendar/EventChip";
import { EventSheet } from "../calendar/EventSheet";
import { useRailBlocks, useTodayBlocks } from "../usePluginModules";
import { byDay, isPast, todayParts } from "../calendar/layout";
import { PhoneRow } from "../calendar/PhoneLists";
import type { Occurrence } from "../calendar/types";
import { AttentionPill } from "../problems/AttentionPill";

/**
 * A phone's Today (UX §5): the date and who's using it, Up next large, then the rest of today;
 * after 6 PM, or once today is done, tomorrow. Sections follow the display's Today panel.
 */
export function TodayScreen() {
  const minute = useMinute();
  const now = wallNow(minute);
  const { day: today, hour } = zonedParts(minute);
  const tomorrow = addDays(today, 1);
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const { data } = useOccurrences(today, addDays(today, 2));
  const [panel, setPanel] = useState<BoardPanel>(null);
  const blocks = useTodayBlocks();
  const railBlocks = useRailBlocks();
  const occurrences = data?.occurrences ?? [];
  const parts = todayParts(occurrences, now);
  const columns = byDay(occurrences, [today, tomorrow]);
  const onNow = [...parts.now, ...parts.allDay];
  const shown = new Set([...onNow.map((o) => o.key), parts.upNext?.key]);
  const todays = [...(columns.get(today)?.allDay ?? []), ...(columns.get(today)?.timed ?? [])]
    .map((e) => e.occurrence)
    .filter((o) => !shown.has(o.key));
  const hadToday =
    (columns.get(today)?.allDay.length ?? 0) + (columns.get(today)?.timed.length ?? 0) > 0;
  const tomorrows = [
    ...(columns.get(tomorrow)?.allDay ?? []),
    ...(columns.get(tomorrow)?.timed ?? []),
  ].map((e) => e.occurrence);
  const dimPast = settings?.display_dim_past ?? true;
  const todayDone = !parts.upNext && !parts.later.length;
  const showTomorrow = (hour >= 18 || todayDone) && tomorrows.length > 0;

  const open = (occurrence: Occurrence) => {
    if (!occurrence.event_id) return;
    setPanel({
      kind: "event",
      eventId: occurrence.event_id,
      recurrenceId: occurrence.recurrence_id ?? null,
      key: occurrence.key,
    });
  };
  const upNext = parts.upNext;
  const upNextPeople = upNext ? peopleOf(upNext, members) : [];

  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-8 px-4 pt-[calc(env(safe-area-inset-top)+16px)] pb-40">
      <header className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-title font-bold">{shortDate(today)}</h1>
          <Link
            to="/who"
            search={{ from: "more" }}
            aria-label={
              session?.member
                ? `Using this device: ${session.member.name}`
                : "Who's using this device?"
            }
            className="press flex size-11 shrink-0 items-center justify-center rounded-full"
          >
            <Avatar member={session?.member ?? null} size="sm" />
          </Link>
        </div>
        {railBlocks.map((Block, index) => (
          <Block key={index} place="phone" />
        ))}
        <AttentionPill />
      </header>
      {onNow.length ? (
        <section aria-labelledby="today-now" className="flex flex-col gap-1">
          <h2 id="today-now" className="text-row font-bold text-ink-soft">
            Now
          </h2>
          <ul className="flex flex-col">
            {onNow.map((occurrence) => (
              <li key={occurrence.key}>
                <PhoneRow
                  occurrence={occurrence}
                  members={members}
                  day={today}
                  dim={false}
                  {...(!occurrence.all_day && occurrence.end_local
                    ? // The time stays whole when the narrow column wraps: "until / 4:15 PM".
                      {
                        when: `until ${formatWallTime(occurrence.end_local).replace(" ", "\u00a0")}`,
                      }
                    : {})}
                  onOpen={() => {
                    open(occurrence);
                  }}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-labelledby="up-next" className="flex flex-col gap-1">
        <h2 id="up-next" className="text-row font-bold text-ink-soft">
          Up Next
        </h2>
        {upNext ? (
          <button
            type="button"
            data-person={
              upNext.color ?? (upNextPeople.length === 1 ? upNextPeople[0]?.color : "everyone")
            }
            onClick={() => {
              open(upNext);
            }}
            className="press-row -mx-2 flex flex-col items-start rounded-chip px-2 py-1 text-left"
          >
            <span className="text-row font-semibold">
              {upNext.start_local ? formatWallTime(upNext.start_local) : ""}
            </span>
            <span className="text-big font-bold break-words">{upNext.title}</span>
            <span className="text-body text-ink-soft">
              {[
                upNextPeople.length ? upNextPeople.map((p) => p.name).join(", ") : "Everyone",
                upNext.location,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </button>
        ) : (
          <p className="text-big font-bold">
            {hadToday ? "Nothing else today." : "Nothing today."}
          </p>
        )}
      </section>
      {todays.length ? (
        <section aria-labelledby="today-rest" className="flex flex-col gap-1">
          <h2 id="today-rest" className="text-row font-bold text-ink-soft">
            Today
          </h2>
          <ul className="flex flex-col">
            {todays.map((occurrence) => (
              <li key={occurrence.key}>
                <PhoneRow
                  occurrence={occurrence}
                  members={members}
                  day={today}
                  dim={dimPast && isPast(occurrence, now)}
                  onOpen={() => {
                    open(occurrence);
                  }}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {showTomorrow ? (
        <section aria-labelledby="today-tomorrow" className="flex flex-col gap-1">
          <h2 id="today-tomorrow" className="text-row font-bold text-ink-soft">
            Tomorrow
          </h2>
          <ul className="flex flex-col">
            {tomorrows.map((occurrence) => (
              <li key={occurrence.key}>
                <PhoneRow
                  occurrence={occurrence}
                  members={members}
                  day={tomorrow}
                  dim={false}
                  onOpen={() => {
                    open(occurrence);
                  }}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {blocks.map(({ key, Phone }) => (Phone ? <Phone key={key} /> : null))}
      <ActionBar>
        <Button
          block
          onClick={() => {
            setPanel({ kind: "add", day: null, hour: null });
          }}
        >
          <Plus aria-hidden="true" className="size-5" />
          Add
        </Button>
      </ActionBar>
      <EventSheet
        panel={panel?.kind === "event" ? panel : null}
        onClose={() => {
          setPanel(null);
        }}
        onChange={(eventId, recurrenceId) => {
          setPanel({ kind: "edit", eventId, recurrenceId });
        }}
      />
      <AddPanel
        panel={panel?.kind === "add" || panel?.kind === "edit" ? panel : null}
        today={today}
        onClose={() => {
          setPanel(null);
        }}
        onType={(type) => {
          setPanel((open) => (open?.kind === "add" ? { ...open, type } : open));
        }}
      />
    </main>
  );
}
