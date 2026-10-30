import { addDays, formatWallTime, shortWeekday } from "../../lib/dates";
import type { Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { Avatar } from "../../ui/Avatar";
import { byDay, isOn, isPast } from "./layout";
import { coreOverlayOf } from "./overlays";
import type { Occurrence } from "./types";

/**
 * The Today view (UX §3, board B): today's events at glance size, every line readable from
 * across the room, then a strip of the next days with how much each holds. For small
 * households, grandparents and hallway screens; chosen in Settings → Display → Home view.
 * Until the events first arrive it says nothing, rather than "Nothing today."
 */
export function TodayView({
  today,
  now,
  occurrences,
  loading = false,
  members,
  onOpen,
}: {
  today: string;
  now: string;
  occurrences: Occurrence[];
  loading?: boolean;
  members: Member[];
  onOpen: (occurrence: Occurrence) => void;
}) {
  const t = useT();
  const days = Array.from({ length: 7 }, (_, n) => addDays(today, n));
  const columns = byDay(occurrences, days);
  const column = columns.get(today);
  const items = [...(column?.allDay ?? []), ...(column?.timed ?? [])].map((e) => e.occurrence);
  return (
    <div className="flex min-h-0 flex-1 flex-col border-t border-line">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-6 py-5" tabIndex={0}>
        {loading ? null : items.length === 0 ? (
          <p className="text-d-glance font-bold text-ink-soft">{t("calendar.today.empty")}</p>
        ) : (
          items.map((occurrence) => {
            const people = members.filter((m) => occurrence.member_ids.includes(m.id));
            const on = isOn(occurrence, now);
            const past = isPast(occurrence, now);
            const Mark = coreOverlayOf(occurrence)?.icon;
            return (
              <button
                key={occurrence.key}
                type="button"
                data-person={
                  occurrence.color ?? (people.length === 1 ? people[0]?.color : "everyone")
                }
                onClick={() => {
                  onOpen(occurrence);
                }}
                className={`press flex min-h-20 items-center gap-6 rounded-chip-d px-5 py-3 text-left ${
                  on ? "bg-p text-on-ink" : past ? "text-ink-soft" : "bg-p-tint"
                }`}
              >
                <span className="w-40 shrink-0 text-d-title font-bold">
                  {occurrence.all_day || !occurrence.start_local
                    ? t("calendar.today.all_day")
                    : formatWallTime(occurrence.start_local)}
                </span>
                {Mark ? (
                  <Mark aria-hidden="true" className="size-10 shrink-0" strokeWidth={2.25} />
                ) : null}
                <span className="min-w-0 flex-1 text-d-glance font-bold break-words">
                  {occurrence.title}
                </span>
                <span className="flex shrink-0 -space-x-3">
                  {people.map((member) => (
                    <Avatar key={member.id} member={member} size="lg" />
                  ))}
                </span>
              </button>
            );
          })
        )}
      </div>
      <ul
        aria-label={t("calendar.today.days.aria")}
        className="grid grid-cols-6 border-t border-line"
      >
        {days.slice(1).map((day) => {
          // Events only: a day's dinner or countdown isn't one.
          const count = [
            ...(columns.get(day)?.allDay ?? []),
            ...(columns.get(day)?.timed ?? []),
          ].filter((entry) => entry.occurrence.overlay === null).length;
          return (
            <li key={day} className="flex flex-col gap-1 border-r border-line px-4 py-3">
              <span className="text-d-body font-semibold">{shortWeekday(day)}</span>
              <span className={`text-d-secondary text-ink-soft ${loading ? "invisible" : ""}`}>
                {t("calendar.today.count", { n: count })}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
