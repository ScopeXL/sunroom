/**
 * Repeats as the editor offers them (UX §4 "Repeats", PLAN §7): a few shapes that compile to an
 * RFC 5545 RRULE and back, the presets for a start day, the Custom form's fields (every N days,
 * weeks, months or years, on chosen weekdays), and the sentence that names a repeat. A rule
 * these shapes can't hold is left alone: the editor keeps it as it is and shows the server's
 * description of it.
 *
 * Days are ISO dates; weekdays count 0 Monday … 6 Sunday, like the household's week_starts_on.
 * Monthly-by-date and yearly rules name no day of their own (they follow the start day), so the
 * server can still move them to another day.
 *
 * The words are `calendar.repeat.*` in lang/, each sentence whole: the interval and the count are
 * plurals, the date an ordinal, the weekday's place in its month a select.
 */
import {
  monthDay,
  orderedWeekdays,
  weekdayLong,
  weekdayOf,
  weekdayShort,
  zonedParts,
} from "../../lib/dates";
import { t } from "../../lib/lang";

export type Repeat =
  | { freq: "daily"; interval: number }
  | { freq: "weekly"; interval: number; weekdays: number[] } // 0 Monday … 6 Sunday, sorted, at least one
  | { freq: "monthly"; interval: number; by: "date" } // on the start day's date
  | { freq: "monthly"; interval: number; by: "weekday" } // on the start day's nth (or last) weekday
  | { freq: "yearly"; interval: number };

export interface RepeatEnd {
  until?: string; // ISO date (inclusive)
  count?: number; // 1–1000
}

export interface RepeatPreset {
  key: string;
  label: string;
  repeat: Repeat | null; // null = "Doesn't repeat"
}

const CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
// A weekday's place in its month, as the messages' select names it (not words the family reads).
const NTH = ["first", "second", "third", "fourth"];
const WORKWEEK = [0, 1, 2, 3, 4];
const MAX_COUNT = 1000;

const pick = (list: readonly string[], index: number): string => list[index] ?? "";

function parts(day: string): { year: number; month: number; date: number } {
  return {
    year: Number(day.slice(0, 4)),
    month: Number(day.slice(5, 7)),
    date: Number(day.slice(8, 10)),
  };
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Which of its weekday the day is in its month: 1–4, or -1 when it's the month's last one. */
function weekdayPosition(day: string): number {
  const { year, month, date } = parts(day);
  return date + 7 > daysInMonth(year, month) ? -1 : Math.ceil(date / 7);
}

function cleanInterval(interval: number): number {
  return Number.isFinite(interval) ? Math.max(1, Math.trunc(interval)) : 1;
}

function sortedWeekdays(weekdays: readonly number[]): number[] {
  return [...new Set(weekdays)]
    .filter((day) => Number.isInteger(day) && day >= 0 && day < 7)
    .sort((a, b) => a - b);
}

/** Sorted, without repeats; the start day's weekday when none are left. */
function cleanWeekdays(weekdays: readonly number[], startDay: string): number[] {
  const kept = sortedWeekdays(weekdays);
  return kept.length ? kept : [weekdayOf(startDay)];
}

/** "Mon", "Mon and Wed", "Mon, Wed and Fri". */
function listed(words: readonly string[]): string {
  if (words.length < 2) return words.join("");
  return t("calendar.repeat.day_list", {
    list: words.slice(0, -1).join(", "),
    last: pick(words, words.length - 1),
  });
}

/**
 * Whether the day a week starts on changes which days a weekly rule falls on, compared with a
 * Monday start (the RRULE default). Only every few weeks, and only when its weekdays sit on both
 * sides of that first day: "every 2 weeks on Sun and Mon" is one week's Sunday and Monday in a
 * Sunday-first household, and two different weeks' in a Monday-first one.
 */
export function weekStartMatters(
  interval: number,
  weekdays: readonly number[],
  weekStartsOn: number,
): boolean {
  if (cleanInterval(interval) < 2 || weekStartsOn === 0) return false;
  return weekdays.some((day) => day >= weekStartsOn) && weekdays.some((day) => day < weekStartsOn);
}

/** `weekStartsOn` is the household's (0 Monday … 6 Sunday): written as WKST only when it
 * changes the rule's days, so most rules stay as short as other calendars write them. */
export function repeatToRRule(
  repeat: Repeat,
  startDay: string,
  end?: RepeatEnd,
  weekStartsOn = 0,
): string {
  const rule = [`FREQ=${repeat.freq.toUpperCase()}`];
  const interval = cleanInterval(repeat.interval);
  if (interval > 1) rule.push(`INTERVAL=${interval}`);
  if (repeat.freq === "weekly") {
    const days = cleanWeekdays(repeat.weekdays, startDay);
    rule.push(`BYDAY=${days.map((day) => pick(CODES, day)).join(",")}`);
    if (weekStartMatters(interval, days, weekStartsOn)) {
      rule.push(`WKST=${pick(CODES, weekStartsOn)}`);
    }
  } else if (repeat.freq === "monthly" && repeat.by === "weekday") {
    rule.push(`BYDAY=${weekdayPosition(startDay)}${pick(CODES, weekdayOf(startDay))}`);
  }
  // A rule may not have both; the date wins.
  if (end?.until) {
    rule.push(`UNTIL=${end.until.replaceAll("-", "")}`);
  } else if (end?.count !== undefined) {
    const count = Math.min(MAX_COUNT, Math.max(1, Math.trunc(end.count)));
    rule.push(`COUNT=${count}`);
  }
  return rule.join(";");
}

function validDay(year: number, month: number, date: number): boolean {
  return month >= 1 && month <= 12 && date >= 1 && date <= daysInMonth(year, month);
}

/**
 * UNTIL as a household day: a DATE as written, a UTC time on the household's clock (the zone
 * `setDatePreferences` was given), so "11:59 PM in New York" stays Dec 31.
 */
function untilDay(value: string): string | null {
  const match = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?$/.exec(value);
  if (!match) return null;
  const [year, month, date, hour, minute, second] = match.slice(1, 7).map(Number);
  if (year === undefined || month === undefined || date === undefined) return null;
  if (!validDay(year, month, date)) return null;
  if (match[7] === "Z") {
    const moment = new Date(Date.UTC(year, month - 1, date, hour ?? 0, minute ?? 0, second ?? 0));
    return zonedParts(moment).day;
  }
  return `${match[1] ?? ""}-${match[2] ?? ""}-${match[3] ?? ""}`;
}

function whole(value: string | undefined, min: number, max: number): number | null {
  if (value === undefined || !/^[+-]?\d{1,4}$/.test(value)) return null;
  const number = Number(value);
  return number >= min && number <= max ? number : null;
}

/** Plain weekday codes ("MO,WE") as weekdays, or null when one carries a position ("2TH"). */
function codesToWeekdays(value: string): number[] | null {
  const days = value.split(",").map((code) => CODES.indexOf(code));
  return days.length && days.every((day) => day >= 0) ? days : null;
}

/** The rule as one of the editor's shapes, or null when it doesn't fit one. `weekStartsOn` is
 * the household's: a rule whose days depend on another first day of the week isn't read (saving
 * it back would move its days), and is kept as it is instead. */
export function rruleToRepeat(
  rrule: string,
  startDay: string,
  weekStartsOn = 0,
): { repeat: Repeat; end: RepeatEnd } | null {
  const fields = new Map<string, string>();
  for (const piece of rrule
    .trim()
    .replace(/^RRULE:/i, "")
    .split(";")) {
    if (!piece.trim()) continue;
    const [key, value, extra] = piece.split("=").map((text) => text.trim().toUpperCase());
    if (!key || value === undefined || extra !== undefined || fields.has(key)) return null;
    fields.set(key, value);
  }
  const take = (key: string): string | undefined => {
    const value = fields.get(key);
    fields.delete(key);
    return value;
  };

  const freq = take("FREQ");
  const intervalText = take("INTERVAL");
  const interval = intervalText === undefined ? 1 : whole(intervalText, 1, 9999);
  const countText = take("COUNT");
  const untilText = take("UNTIL");
  const wkst = take("WKST");
  const byDay = take("BYDAY");
  const byMonthDay = take("BYMONTHDAY");
  const byMonth = take("BYMONTH");
  const bySetPos = take("BYSETPOS");
  if (interval === null || fields.size > 0) return null;
  if (countText !== undefined && untilText !== undefined) return null;

  const end: RepeatEnd = {};
  if (countText !== undefined) {
    const count = whole(countText, 1, MAX_COUNT);
    if (count === null) return null;
    end.count = count;
  }
  if (untilText !== undefined) {
    const until = untilDay(untilText);
    if (until === null) return null;
    end.until = until;
  }

  const start = parts(startDay);
  const weekday = weekdayOf(startDay);
  const onDates = byMonthDay !== undefined || byMonth !== undefined || bySetPos !== undefined;
  let repeat: Repeat | null = null;
  if (freq === "DAILY" && !onDates) {
    // Every day on some weekdays is every week on them.
    const weekdays = byDay === undefined ? null : codesToWeekdays(byDay);
    if (byDay === undefined) repeat = { freq: "daily", interval };
    else if (weekdays && interval === 1) repeat = { freq: "weekly", interval, weekdays };
  } else if (freq === "WEEKLY" && !onDates) {
    const weekdays = byDay === undefined ? [weekday] : codesToWeekdays(byDay);
    // The rule's own first day of the week (Monday when it names none) must mean the same days
    // as the household's: the same day, or a rule that neither changes.
    const ruleStart = wkst === undefined ? 0 : CODES.indexOf(wkst);
    const sameWeeks =
      weekdays !== null &&
      ruleStart >= 0 &&
      (ruleStart === weekStartsOn ||
        (!weekStartMatters(interval, weekdays, ruleStart) &&
          !weekStartMatters(interval, weekdays, weekStartsOn)));
    if (weekdays && sameWeeks) repeat = { freq: "weekly", interval, weekdays };
  } else if (freq === "MONTHLY" && byMonth === undefined) {
    if (byDay === undefined && bySetPos === undefined) {
      const date = byMonthDay === undefined ? start.date : whole(byMonthDay, 1, 31);
      if (date === start.date) repeat = { freq: "monthly", interval, by: "date" };
    } else if (byDay !== undefined && byMonthDay === undefined) {
      // "2TH", or "TH" with BYSETPOS=2: the start day's place among its weekdays in the month.
      const match = /^([+-]?\d{1,2})?([A-Z]{2})$/.exec(byDay);
      const position = whole(match?.[1] ?? bySetPos, -5, 5);
      const once = match?.[1] === undefined || bySetPos === undefined;
      if (match?.[2] === pick(CODES, weekday) && once && position === weekdayPosition(startDay)) {
        repeat = { freq: "monthly", interval, by: "weekday" };
      }
    }
  } else if (freq === "YEARLY" && byDay === undefined && bySetPos === undefined) {
    const month = byMonth === undefined ? start.month : whole(byMonth, 1, 12);
    const date = byMonthDay === undefined ? start.date : whole(byMonthDay, 1, 31);
    if (month === start.month && date === start.date) repeat = { freq: "yearly", interval };
  }
  if (repeat?.freq === "weekly") repeat.weekdays = cleanWeekdays(repeat.weekdays, startDay);
  return repeat ? { repeat, end } : null;
}

/** Whether two repeats are the same rule (weekdays compared as sets). */
export function sameRepeat(a: Repeat | null, b: Repeat | null): boolean {
  if (!a || !b) return a === b;
  if (a.freq !== b.freq || cleanInterval(a.interval) !== cleanInterval(b.interval)) return false;
  if (a.freq === "weekly" && b.freq === "weekly") {
    return sortedWeekdays(a.weekdays).join() === sortedWeekdays(b.weekdays).join();
  }
  if (a.freq === "monthly" && b.freq === "monthly") return a.by === b.by;
  return true;
}

/** "Dec 31", or "Jan 15, 2027" in another year than the start day's: the day a repeat ends. */
function untilDate(until: string, startDay: string): string {
  const sameYear = until.slice(0, 4) === startDay.slice(0, 4);
  return `${monthDay(until)}${sameYear ? "" : `, ${until.slice(0, 4)}`}`;
}

/** The start day's place among its weekdays in its month, as the messages' select says it:
 * "second", or "last". */
function nthOf(startDay: string): string {
  const position = weekdayPosition(startDay);
  return position === -1 ? "last" : pick(NTH, position - 1);
}

/** "the 9th": the start day's date, for a monthly repeat's sentence. */
export function monthDateWords(startDay: string): string {
  return t("calendar.repeat.month_date", { date: parts(startDay).date });
}

/** "the second Thursday", or "the last Thursday": the start day's place in its month. */
export function monthWeekdayWords(startDay: string): string {
  return t("calendar.repeat.month_weekday", {
    nth: nthOf(startDay),
    weekday: weekdayLong(weekdayOf(startDay)),
  });
}

/** The Custom form's two month choices, each a whole sentence: "On the 9th". */
export function monthDateChoice(startDay: string): string {
  return t("calendar.repeat.month_by.date", { date: parts(startDay).date });
}

/** "On the second Thursday", "On the last Thursday". */
export function monthWeekdayChoice(startDay: string): string {
  return t("calendar.repeat.month_by.weekday", {
    nth: nthOf(startDay),
    weekday: weekdayLong(weekdayOf(startDay)),
  });
}

/** Weekdays in the household's order: "Sun and Mon" where the week starts on Sunday. */
function inWeekOrder(weekdays: readonly number[], weekStartsOn: number): number[] {
  return orderedWeekdays(weekStartsOn).filter((day) => weekdays.includes(day));
}

export function describeRepeat(
  repeat: Repeat,
  startDay: string,
  end?: RepeatEnd,
  weekStartsOn = 0,
): string {
  const n = cleanInterval(repeat.interval);
  let text: string;
  switch (repeat.freq) {
    case "daily":
      text = t("calendar.repeat.daily", { n });
      break;
    case "weekly": {
      const days = cleanWeekdays(repeat.weekdays, startDay);
      text =
        n === 1 && days.join() === WORKWEEK.join()
          ? t("calendar.repeat.every_weekday")
          : t("calendar.repeat.weekly", {
              n,
              days: listed(inWeekOrder(days, weekStartsOn).map(weekdayShort)),
            });
      break;
    }
    case "monthly":
      text = t("calendar.repeat.monthly", {
        n,
        day: repeat.by === "date" ? monthDateWords(startDay) : monthWeekdayWords(startDay),
      });
      break;
    case "yearly":
      text = t("calendar.repeat.yearly", { n, date: monthDay(startDay) });
      break;
  }
  if (end?.until) {
    return t("calendar.repeat.until", { rule: text, date: untilDate(end.until, startDay) });
  }
  if (end?.count !== undefined) {
    const count = Math.min(MAX_COUNT, Math.max(1, Math.trunc(end.count)));
    return t("calendar.repeat.count", { rule: text, n: count });
  }
  return text;
}

/** What the Custom form holds: every `interval` days, weeks, months or years; the weekdays for
 * weeks; the date or the nth weekday for months. */
export interface CustomRepeat {
  freq: Repeat["freq"];
  interval: number;
  /** 0 Monday … 6 Sunday; used when `freq` is weekly. */
  weekdays: number[];
  /** Used when `freq` is monthly. */
  monthlyBy: "date" | "weekday";
}

export function customToRepeat(custom: CustomRepeat, startDay: string): Repeat {
  const interval = cleanInterval(custom.interval);
  switch (custom.freq) {
    case "daily":
      return { freq: "daily", interval };
    case "weekly":
      return { freq: "weekly", interval, weekdays: cleanWeekdays(custom.weekdays, startDay) };
    case "monthly":
      return { freq: "monthly", interval, by: custom.monthlyBy };
    case "yearly":
      return { freq: "yearly", interval };
  }
}

/** The form's fields for a repeat. With none yet, it starts as every week on the start day. */
export function repeatToCustom(repeat: Repeat | null, startDay: string): CustomRepeat {
  const weekday = weekdayOf(startDay);
  if (!repeat) return { freq: "weekly", interval: 1, weekdays: [weekday], monthlyBy: "date" };
  return {
    freq: repeat.freq,
    interval: cleanInterval(repeat.interval),
    weekdays: repeat.freq === "weekly" ? cleanWeekdays(repeat.weekdays, startDay) : [weekday],
    monthlyBy: repeat.freq === "monthly" ? repeat.by : "date",
  };
}

/** Whether one of the preset chips already says this repeat (null is "Doesn't repeat"). */
export function isPreset(repeat: Repeat | null, startDay: string): boolean {
  return repeatPresets(startDay).some((preset) => sameRepeat(preset.repeat, repeat));
}

export function repeatPresets(startDay: string): RepeatPreset[] {
  const weekday = weekdayOf(startDay);
  const repeats: [string, Repeat][] = [
    ["daily", { freq: "daily", interval: 1 }],
    ["weekdays", { freq: "weekly", interval: 1, weekdays: [...WORKWEEK] }],
    ["weekly", { freq: "weekly", interval: 1, weekdays: [weekday] }],
    ["biweekly", { freq: "weekly", interval: 2, weekdays: [weekday] }],
    ["monthly-date", { freq: "monthly", interval: 1, by: "date" }],
    ["monthly-weekday", { freq: "monthly", interval: 1, by: "weekday" }],
    ["yearly", { freq: "yearly", interval: 1 }],
  ];
  return [
    { key: "none", label: t("calendar.repeat.none"), repeat: null },
    ...repeats.map(([key, repeat]) => ({ key, label: describeRepeat(repeat, startDay), repeat })),
  ];
}
