import { formatWallTime } from "../../lib/dates";
import type { Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useChangeCount } from "../../lib/motion";
import { useShell } from "../../ui/shell";
import { DayCaption } from "./DayCaption";
import { EventChip } from "./EventChip";
import { byDay, clusters, isPast, shownFor, type Cluster } from "./layout";
import type { Occurrence } from "./types";

const SIDE_BY_SIDE = 3; // at least half the width each, so two to a row

const hourOf = (local: string) => Number(local.slice(11, 13));
const minutesBetween = (a: string, b: string) =>
  (Date.parse(`${b}Z`) - Date.parse(`${a}Z`)) / 60_000;

/**
 * The Day view (UX §4), the only timeline: on the wall the day's name over it (`DayCaption`, as
 * the People view has), then every event a full chip beside its hour, overlapping
 * ones side by side (three at most, then "+N more"), and empty stretches folded into one line
 * ("free until 4:00 PM") that adds an event at that time when tapped. The now line sits where
 * now is. Tap a time to add.
 */
export function DayView({
  day,
  now,
  occurrences,
  members,
  dimPast,
  people,
  onOpen,
  onAdd,
}: {
  day: string;
  now: string;
  occurrences: Occurrence[];
  members: Member[];
  dimPast: boolean;
  people: string[];
  onOpen: (occurrence: Occurrence) => void;
  onAdd: (hour: number) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const soft = display ? "text-d-secondary" : "text-secondary";
  const hours = display ? "grid-cols-[6rem_1fr]" : "grid-cols-[4.5rem_1fr]";
  const column = byDay(occurrences, [day]).get(day);
  const filter = new Set(people);
  const allDay = (column?.allDay ?? []).map((e) => e.occurrence);
  const timed = (column?.timed ?? []).map((e) => e.occurrence);
  const groups = clusters(timed);
  const isToday = now.slice(0, 10) === day;
  const dayStart = `${day}T00:00:00`;

  type Row =
    | { kind: "cluster"; cluster: Cluster<Occurrence> }
    | { kind: "free"; from: string; until: string | null }
    | { kind: "now" };
  const rows: Row[] = [];
  let cursor = dayStart;
  for (const cluster of groups) {
    if (minutesBetween(cursor, cluster.start) >= 60) {
      rows.push({ kind: "free", from: cursor, until: cluster.start });
    }
    rows.push({ kind: "cluster", cluster });
    if (cluster.end > cursor) cursor = cluster.end;
  }
  rows.push({ kind: "free", from: cursor, until: null });
  if (isToday) {
    const index = rows.findIndex(
      (row) =>
        (row.kind === "cluster" && row.cluster.end > now) ||
        (row.kind === "free" && (row.until === null || row.until > now)),
    );
    rows.splice(index === -1 ? rows.length : index, 0, { kind: "now" });
  }
  // Where the now line sits among today's rows; no line on another day.
  const nowAt = rows.findIndex((row) => row.kind === "now");
  const drops = useChangeCount(nowAt === -1 ? null : nowAt, day);

  const chip = (occurrence: Occurrence) => (
    <div key={occurrence.key} className={shownFor(occurrence, filter) ? "" : "opacity-30"}>
      <EventChip
        occurrence={occurrence}
        members={members}
        now={now}
        dimPast={dimPast && isToday}
        day={day}
        onOpen={() => {
          onOpen(occurrence);
        }}
      />
    </div>
  );

  return (
    <div
      tabIndex={display ? 0 : undefined}
      className={`flex min-h-0 flex-1 flex-col gap-3 ${
        display ? "overflow-y-auto border-t border-line px-6 py-4" : "py-2"
      }`}
    >
      {/* The room's h1 says it to a screen reader (shell/Header). */}
      {display ? <DayCaption day={day} today={isToday} /> : null}
      {allDay.length ? (
        <div className={`grid ${hours} items-start gap-4`}>
          <span className={`pt-4 ${soft} font-semibold text-ink-soft`}>
            {t("calendar.board.all_day")}
          </span>
          <div className="flex flex-col gap-2">{allDay.map(chip)}</div>
        </div>
      ) : null}
      {rows.map((row, index) => {
        if (row.kind === "now") {
          return (
            // Re-keyed by where it sits: it drops into its new place when what's on ends.
            <div
              key={`now-${String(drops)}`}
              aria-hidden="true"
              className={`grid ${hours} items-center gap-4 ${drops ? "now-drop" : ""}`}
            >
              <span />
              <div className="flex items-center gap-3">
                <span className="now-label font-semibold whitespace-nowrap text-sun-ink">
                  {t("calendar.board.now", { time: formatWallTime(now, { period: false }) })}
                </span>
                <span className="now-glow h-0.5 flex-1 rounded-full bg-sun-ink" />
              </div>
            </div>
          );
        }
        if (row.kind === "free") {
          const from = row.from === dayStart ? null : row.from;
          const startHour = from ? hourOf(from) + (from.slice(14, 16) === "00" ? 0 : 1) : 8;
          const label = row.until
            ? t("calendar.day.free_until", { time: formatWallTime(row.until) })
            : groups.length
              ? t("calendar.day.add.hint")
              : t("calendar.day.empty");
          return (
            <div key={`free-${String(index)}`} className={`grid ${hours} items-center gap-4`}>
              <span />
              <button
                type="button"
                onClick={() => {
                  onAdd(Math.min(23, startHour));
                }}
                className={`press border-2 border-dashed border-line px-4 text-left ${soft} font-semibold text-ink-soft ${
                  display ? "min-h-tap rounded-chip-d" : "min-h-11 rounded-chip"
                }`}
              >
                {label}
              </button>
            </div>
          );
        }
        const { cluster } = row;
        const shown = cluster.items.slice(0, SIDE_BY_SIDE);
        const hidden = cluster.items.length - shown.length;
        return (
          <div key={cluster.items[0]?.key ?? index} className={`grid ${hours} items-start gap-4`}>
            <span
              className={`pt-4 ${soft} font-semibold ${
                dimPast && isToday && cluster.items.every((o) => isPast(o, now))
                  ? "text-ink-soft"
                  : ""
              }`}
            >
              {formatWallTime(cluster.start, { compact: true })}
            </span>
            <div className={`grid gap-2 ${shown.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
              {shown.map(chip)}
              {hidden ? (
                <span
                  className={`flex min-h-14 items-center px-3 ${soft} font-semibold text-ink-soft`}
                >
                  {t("dates.more", { n: hidden })}
                </span>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
