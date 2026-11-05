/**
 * Dates and times as the household reads them (UX §2 "Time and date words"): in the household's
 * time zone and its 12- or 24-hour choice, written by Intl in the page's language (the registry's
 * locale, ADR 0043) with every digit Latin, as the digit boxes draw them (ADR 0021). English is
 * `en-US`; no date library needed.
 *
 * Calendar days are ISO strings ("2026-10-07") and day math happens on UTC midnights, so a
 * week never gains or loses an hour across a daylight-saving change.
 */
import { intlLocale } from "./lang";

let zone: string | undefined;
let hour12 = true;

export interface DatePreferences {
  timezone: string;
  timeFormat: "12h" | "24h";
}

export function setDatePreferences(preferences: DatePreferences): void {
  zone = preferences.timezone;
  hour12 = preferences.timeFormat === "12h";
}

export function householdZone(): string | undefined {
  return zone;
}

export interface ZonedParts {
  day: string; // ISO date in the household zone
  hour: number;
  minute: number;
  weekday: number; // 0 Monday … 6 Sunday, as the household setting counts
}

const partsFormat = new Map<string, Intl.DateTimeFormat>();

/** Reading a moment's parts, not writing them: always `en-US`, whose weekday `zonedParts` matches
 * against WEEKDAY_SHORT, whatever the page's language. */
function formatter(timeZone: string | undefined): Intl.DateTimeFormat {
  const key = timeZone ?? "";
  let format = partsFormat.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      weekday: "short",
    });
    partsFormat.set(key, format);
  }
  return format;
}

/** `en-US`'s weekdays, as `zonedParts` reads them: 0 Monday … 6 Sunday. Never shown: the page
 * names a weekday with `weekdayShort`. */
export const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** The seven weekdays in the household's order: Sunday first (6) gives [6, 0, 1, 2, 3, 4, 5]. */
export function orderedWeekdays(weekStartsOn: number): number[] {
  return Array.from({ length: 7 }, (_, index) => (weekStartsOn + index) % 7);
}

export function zonedParts(moment: Date, timeZone = zone): ZonedParts {
  const parts: Record<string, string> = {};
  for (const part of formatter(timeZone).formatToParts(moment)) parts[part.type] = part.value;
  const hour = Number(parts.hour) % 24;
  return {
    day: `${parts.year ?? "1970"}-${parts.month ?? "01"}-${parts.day ?? "01"}`,
    hour,
    minute: Number(parts.minute),
    weekday: Math.max(0, WEEKDAY_SHORT.indexOf((parts.weekday ?? "Mon") as "Mon")),
  };
}

function utcMidnight(day: string): Date {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1));
}

export function addDays(day: string, days: number): string {
  const moved = utcMidnight(day);
  moved.setUTCDate(moved.getUTCDate() + days);
  return moved.toISOString().slice(0, 10);
}

/** 0 Monday … 6 Sunday. */
export function weekdayOf(day: string): number {
  return (utcMidnight(day).getUTCDay() + 6) % 7;
}

/** The seven days of the week holding ``day``, starting on the household's chosen weekday. */
export function weekOf(day: string, weekStartsOn: number): string[] {
  const offset = (weekdayOf(day) - weekStartsOn + 7) % 7;
  const start = addDays(day, -offset);
  return Array.from({ length: 7 }, (_, index) => addDays(start, index));
}

/** A rolling week (Settings → Display, ADR 0033): seven days with `day` in a fixed column.
 * The split lives here: ROLLING_BEFORE days before it, the rest after. */
const ROLLING_BEFORE = 1;
export function rollingWeek(day: string): string[] {
  return Array.from({ length: 7 }, (_, index) => addDays(day, index - ROLLING_BEFORE));
}

export interface MonthGrid {
  first: string; // the month's first day
  days: string[]; // whole weeks covering the month
  weeks: string[][];
}

/** The month `offset` months from `today`'s, as whole weeks starting on the household's day. */
export function monthGrid(today: string, offset: number, weekStartsOn: number): MonthGrid {
  const [year = 1970, month = 1] = today.split("-").map(Number);
  const index = year * 12 + (month - 1) + offset;
  const first = `${String(Math.floor(index / 12))}-${String((index % 12) + 1).padStart(2, "0")}-01`;
  const start = weekOf(first, weekStartsOn)[0] ?? first;
  const weeks: string[][] = [];
  let day = start;
  do {
    weeks.push(Array.from({ length: 7 }, (_, n) => addDays(day, n)));
    day = addDays(day, 7);
  } while (day.slice(0, 7) === first.slice(0, 7));
  return { first, days: weeks.flat(), weeks };
}

/* Writing them: Intl, in the page's language */

const formats = new Map<string, Intl.DateTimeFormat>();

/** A formatter for the page's language (kept: making one is slow on a Pi). */
function format(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const locale = intlLocale();
  const id = `${locale}\u0000${JSON.stringify(options)}`;
  let found = formats.get(id);
  if (!found) {
    found = new Intl.DateTimeFormat(locale, options);
    formats.set(id, found);
  }
  return found;
}

/** Intl's thin and narrow spaces as plain ones, as Sunroom has always written a time ("4:00 PM"),
 * whichever version of Intl the browser has. */
function spaced(text: string): string {
  return text.replace(/[\u2009\u202f]/g, " ");
}

type Part = Intl.DateTimeRangeFormatPart;

/** A time's parts without its AM or PM: the rail clock's "9:41". */
function withoutPeriod(parts: readonly Intl.DateTimeFormatPart[]): string {
  return spaced(
    parts
      .filter((part) => part.type !== "dayPeriod")
      .map((part) => part.value)
      .join(""),
  ).trim();
}

/**
 * A range as Intl words it in the page's language ("Oct 4–10", "4–10 oct"), its dash as UX §2
 * writes one: closed between two plain values ("4–10", "4:00–5:00 PM"), spaced when either end
 * has a space in it ("Sep 27 – Oct 3", "11:30 AM – 12:30 PM"). A language whose range has no dash
 * keeps its own.
 */
function range(parts: readonly Part[]): string {
  const ends = (source: Part["source"]) =>
    parts
      .filter((part) => part.source === source)
      .map((part) => part.value)
      .join("");
  const wide = /\s/.test(spaced(ends("startRange") + ends("endRange")));
  const lastStart = parts.findLastIndex((part) => part.source === "startRange");
  const firstEnd = parts.findIndex((part) => part.source === "endRange");
  return spaced(
    parts
      .map((part, index) =>
        index > lastStart && index < firstEnd && /^\s*[-–—]\s*$/.test(part.value)
          ? wide
            ? " – "
            : "–"
          : part.value,
      )
      .join(""),
  );
}

function dayFormat(options: Intl.DateTimeFormatOptions): (day: string) => string {
  const whole = { ...options, timeZone: "UTC" };
  return (day) => format(whole).format(utcMidnight(day));
}

/** "Tue" */
export const shortWeekday = dayFormat({ weekday: "short" });
/** "Tuesday" */
export const longWeekday = dayFormat({ weekday: "long" });
/** "7" */
export const dayNumber = (day: string): string => String(Number(day.slice(8, 10)));
/** "Oct 7" */
export const monthDay = dayFormat({ month: "short", day: "numeric" });

/** "October 9", for what a screen reader says (UX §10). */
export const longMonthDay = dayFormat({ month: "long", day: "numeric" });
/** "October". */
export const longMonth = dayFormat({ month: "long" });
/** "Tue, Oct 7" */
export const shortDate = dayFormat({ weekday: "short", month: "short", day: "numeric" });
/** "Tuesday, October 7": the caption over the Day and People views, where a weekday is written out. */
export const longDate = dayFormat({ weekday: "long", month: "long", day: "numeric" });
/** "October 2026" */
export const monthYear = dayFormat({ month: "long", year: "numeric" });
/** "Oct" */
export const shortMonth = dayFormat({ month: "short" });
/** "Jan 15, 2027": a day in another year than the one around it. */
export const monthDayYear = dayFormat({ month: "short", day: "numeric", year: "numeric" });

/** A Monday, for naming the weekdays by number. */
const MONDAY = "2024-01-01";

/** "Mon" for 0 … "Sun" for 6. */
export function weekdayShort(weekday: number): string {
  return shortWeekday(addDays(MONDAY, ((weekday % 7) + 7) % 7));
}

/** "Monday" for 0 … "Sunday" for 6. */
export function weekdayLong(weekday: number): string {
  return longWeekday(addDays(MONDAY, ((weekday % 7) + 7) % 7));
}

/** "Oct 5–11", or "Sep 28 – Oct 4" across months (UX §3's board title). Within a month Intl
 * puts the month where the language does ("5–11 oct"); across two, each end is a `monthDay`
 * (Intl would add the years across a new year's). */
export function weekSpan(days: readonly string[]): string {
  const first = days[0];
  const last = days[days.length - 1];
  if (!first || !last) return "";
  if (first.slice(0, 7) !== last.slice(0, 7)) return `${monthDay(first)} – ${monthDay(last)}`;
  const span = format({ month: "short", day: "numeric", timeZone: "UTC" });
  return range(span.formatRangeToParts(utcMidnight(first), utcMidnight(last)));
}

function clockOptions(timeZone: string | undefined): Intl.DateTimeFormatOptions {
  return { timeZone, hour: "numeric", minute: "2-digit", hourCycle: hour12 ? "h12" : "h23" };
}

/** "4:00 PM" or "16:00" (minutes always shown). */
export function formatTime(moment: Date): string {
  return spaced(format(clockOptions(zone)).format(moment));
}

/** The rail clock: "9:41" (12-hour, no AM/PM) or "21:41". */
export function formatClock(moment: Date): string {
  return withoutPeriod(format(clockOptions(zone)).formatToParts(moment));
}

/** "AM" or "PM" beside the 12-hour clock, or nothing. */
export function clockSuffix(moment: Date): string {
  if (!hour12) return "";
  const period = format(clockOptions(zone))
    .formatToParts(moment)
    .find((part) => part.type === "dayPeriod");
  return spaced(period?.value ?? "");
}

const pad = (value: number): string => String(value).padStart(2, "0");

/** The household's wall time now, as the API writes it ("2026-10-07T09:41:00"). */
export function wallNow(moment: Date): string {
  const { day, hour, minute } = zonedParts(moment);
  return `${day}T${pad(hour)}:${pad(minute)}:00`;
}

/** A wall time's hour and minute on one day, for writing (its own date doesn't matter). */
function wallMoment(local: string): Date {
  const hour = Number(local.slice(11, 13)) || 0;
  const minute = Number(local.slice(14, 16)) || 0;
  return new Date(Date.UTC(2000, 0, 1, hour, minute));
}

/** A wall time from the API ("2026-10-08T14:30:00") as "2:30 PM" or "14:30"; `compact`
 * drops ":00" ("4 PM") for month cells and phone week strips (UX §2) on a 12-hour clock;
 * `period: false` drops AM and PM (the now line's "9:41"). */
export function formatWallTime(
  local: string,
  { compact = false, period = true }: { compact?: boolean; period?: boolean } = {},
): string {
  const moment = wallMoment(local);
  const hourOnly = compact && hour12 && moment.getUTCMinutes() === 0;
  const options = clockOptions("UTC");
  const wall = format(hourOnly ? { ...options, minute: undefined } : options);
  return period ? spaced(wall.format(moment)) : withoutPeriod(wall.formatToParts(moment));
}

/** "4:00–5:00 PM", "11:30 AM – 12:30 PM" or "16:00–17:00". */
export function formatWallRange(start: string, end: string): string {
  const from = wallMoment(start);
  const to = wallMoment(end);
  const wall = format(clockOptions("UTC"));
  if (to > from) return range(wall.formatRangeToParts(from, to));
  // It ends at or before its start time (the next day, or no length at all), which Intl writes
  // as one time or with both dates: say both times, sharing AM or PM as any range does.
  const first = wall.formatToParts(from);
  const second = wall.formatToParts(to);
  const periodOf = (parts: Intl.DateTimeFormatPart[]) =>
    parts.find((part) => part.type === "dayPeriod")?.value;
  const both = [spaced(wall.format(from)), spaced(wall.format(to))];
  if (periodOf(first) !== undefined && periodOf(first) === periodOf(second)) {
    const periodFirst =
      first.findIndex((part) => part.type === "dayPeriod") <
      first.findIndex((part) => part.type === "hour");
    return periodFirst
      ? `${both[0] ?? ""}–${withoutPeriod(second)}`
      : `${withoutPeriod(first)}–${both[1] ?? ""}`;
  }
  return both.join(/\s/.test(both.join("")) ? " – " : "–");
}
