/**
 * Reminders on paired screens (UX §4 "More…"): a toast when one is due, once per occurrence and
 * reminder. A screen that was off or asleep at that minute still shows it for the next few
 * minutes, and never after the event has begun. All-day events remind at 8:00 AM, on the day or
 * the days before. An event with no reminder of its own takes the household's Default reminder,
 * resolved here rather than on the server, so a changed default never leaves the cached week
 * stale (ADR 0034).
 */
import { useEffect, useRef } from "react";

import { addDays, formatWallTime, wallNow, zonedParts } from "../../lib/dates";
import { useSettings } from "../../lib/household";
import { t } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { showToast } from "../../lib/toast";
import { useOccurrences } from "./data";
import type { Occurrence } from "./types";

const GRACE_MINUTES = 10;
const ALL_DAY_AT = "08:00:00";
const DAY = 24 * 60;

/** A wall time `minutes` earlier ("2026-10-08T16:00:00" less 30 is "…T15:30:00"). */
function minus(local: string, minutes: number): string {
  const moment = new Date(Date.parse(`${local}Z`) - minutes * 60_000);
  return moment.toISOString().slice(0, 19);
}

export interface Due {
  key: string; // the occurrence's key and the minutes
  occurrence: string;
  at: string; // the wall time it's due
  message: string;
}

/** The parts of an occurrence a reminder reads. */
export type Remindable = Pick<
  Occurrence,
  | "key"
  | "title"
  | "status"
  | "all_day"
  | "start_local"
  | "start_date"
  | "reminders"
  | "reminders_off"
  | "read_only"
>;

/**
 * When an occurrence reminds (ADR 0034): at its own reminders; never when it says none; else
 * the household's Default reminder, except on a calendar that only shows events (holidays, a
 * calendar address, birthdays and the other overlays).
 */
export function effectiveReminders(
  occurrence: Remindable,
  defaultMinutes: number | null,
): number[] {
  if (occurrence.reminders.length) return occurrence.reminders;
  if (occurrence.reminders_off || occurrence.read_only || defaultMinutes === null) return [];
  return [defaultMinutes];
}

/** Each reminder of these occurrences, when it's due and what it says. */
export function remindersOf(
  occurrences: readonly Remindable[],
  defaultMinutes: number | null = null,
): Due[] {
  const due: Due[] = [];
  for (const occurrence of occurrences) {
    if (occurrence.status === "cancelled") continue;
    const { title } = occurrence;
    for (const minutes of effectiveReminders(occurrence, defaultMinutes)) {
      const key = `${occurrence.key}@${String(minutes)}`;
      if (occurrence.all_day) {
        if (!occurrence.start_date) continue;
        const days = Math.floor(minutes / DAY); // under a day: on the day itself
        due.push({
          key,
          occurrence: occurrence.key,
          at: `${addDays(occurrence.start_date, -days)}T${ALL_DAY_AT}`,
          message: t(
            days === 0 ? "calendar.reminder.today.toast" : "calendar.reminder.tomorrow.toast",
            { title },
          ),
        });
        continue;
      }
      if (!occurrence.start_local) continue;
      const at = minus(occurrence.start_local, minutes);
      const message =
        minutes >= DAY
          ? t("calendar.reminder.tomorrow_at.toast", {
              title,
              time: formatWallTime(occurrence.start_local),
            })
          : minutes >= 60
            ? t("calendar.reminder.hours.toast", { title, n: minutes / 60 })
            : t("calendar.reminder.minutes.toast", { title, n: minutes });
      due.push({ key, occurrence: occurrence.key, at, message });
    }
  }
  return due;
}

/** The reminders to show at `now`: due, not yet shown, and still ahead of their event. */
export function dueNow(
  occurrences: readonly Remindable[],
  now: string,
  shown: ReadonlySet<string>,
  defaultMinutes: number | null = null,
): Due[] {
  const starts = new Map(
    occurrences.map((o) => [
      o.key,
      o.all_day ? `${o.start_date ?? ""}T23:59:59` : (o.start_local ?? ""),
    ]),
  );
  const graceStart = minus(now, GRACE_MINUTES);
  return remindersOf(occurrences, defaultMinutes).filter(
    (reminder) =>
      !shown.has(reminder.key) &&
      reminder.at <= now &&
      reminder.at > graceStart &&
      now < (starts.get(reminder.occurrence) ?? ""),
  );
}

/** Shows due reminders as toasts on the display (shell/DisplayShell). */
export function useReminders(): void {
  const minute = useMinute();
  const today = zonedParts(minute).day;
  const { data } = useOccurrences(today, addDays(today, 2));
  const defaultMinutes = useSettings().data?.default_reminder_minutes ?? null;
  const shown = useRef(new Set<string>());
  const now = wallNow(minute);
  useEffect(() => {
    if (!data) return;
    for (const reminder of dueNow(data.occurrences, now, shown.current, defaultMinutes)) {
      shown.current.add(reminder.key);
      showToast(reminder.message);
    }
  }, [data, now, defaultMinutes]);
}
