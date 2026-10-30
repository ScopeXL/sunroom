/**
 * Quick add (UX §4 and §6, ADR 0015): one line of text read as an event draft while the family
 * types, in the browser. chrono-node finds dates and times; the small grammars here find repeats,
 * lengths, people, "all day" and the casual words (today, tomorrow, noon). Each finding is a span
 * of the text, so the editor can show which words were understood.
 *
 * The grammars' words are the page's language's (ADR 0043): `quickadd.words.*` in lang/, each a
 * list of words joined by `|` (docs/LANGUAGES.md "Quick add's words"), and chrono reads with the
 * registry's `chrono` locale. The shapes are English's ("every other week on Tue"), each filled
 * with the language's words; a language without a list reads English's.
 *
 * Everything is the household's wall time. chrono gets a reference made from the household's
 * today, and none of its own day or year guesses are used, only what it read in the text (a
 * month and day, a weekday, an hour and minute), so the device's time zone never moves a result.
 */
import * as chrono from "chrono-node";

import { addDays, weekOf, weekdayOf, zonedParts } from "../../lib/dates";
import { getLanguage, LANGUAGES, wordList, type Key, type LanguageCode } from "../../lib/lang";
import type { Repeat } from "./repeat";

export interface QuickAddMember {
  id: string;
  name: string;
}

export interface QuickAddContext {
  now: Date; // server-corrected now
  zone: string; // the household's IANA zone; everything below is in this zone
  weekStartsOn: number; // 0 Monday … 6 Sunday
  members: QuickAddMember[];
  defaultDay: string; // ISO date: the day tapped on the board, or today
}

export type UnderstoodKind = "day" | "time" | "length" | "who" | "repeat" | "allDay";

/** A span of the input text the parser used, as in `text.slice(start, end)`. */
export interface Understood {
  kind: UnderstoodKind;
  start: number;
  end: number;
}

export interface QuickAddDraft {
  title: string; // the input minus the parsed words, tidied
  day: string | null; // ISO date understood, or null (the editor then uses defaultDay)
  allDay: boolean; // true when "all day" was said, or when no time was understood
  start: string | null; // "HH:MM" 24-hour local wall time, null when all day
  end: string | null; // "HH:MM" when a range ("2-3pm") or a length ("for 2h") was given
  durationMinutes: number | null; // from a length or a range
  memberIds: string[]; // members named, in household order
  repeat: Repeat | null;
  understood: Understood[]; // sorted by start; the editor highlights these spans
}

interface Span {
  start: number;
  end: number;
}

/** How a day was said: "tomorrow", "Thu", "Oct 9" or "the 9th", "10/9". */
type DaySource = "word" | "weekday" | "date" | "slash";

/** A repeat as said, before the event's day settles its weekday. */
interface RepeatWords {
  freq: Repeat["freq"];
  interval: number;
  weekdays?: number[];
  monthDay?: number;
}

type Finding = Span &
  (
    | { kind: "allDay" }
    | { kind: "repeat"; words: RepeatWords }
    | { kind: "length"; minutes: number }
    | { kind: "who"; ids: string[]; possessive: boolean }
    | { kind: "day"; day: string; source: DaySource }
    | { kind: "time"; from: number; to: number | null }
  );

interface Reading {
  text: string;
  /** The text with found words hidden, so the grammars after them and chrono skip them. */
  masked: string;
  findings: Finding[];
}

type Groups = (string | undefined)[];

interface Match extends Span {
  groups: Groups;
}

const HIDDEN = "\uE000";
const DAY_MINUTES = 24 * 60;
const HALF_DAY = 12 * 60;
const WORKWEEK = [0, 1, 2, 3, 4];
const WEEKEND = [5, 6];

// Whole words, without lookbehind (older Safari lacks it): the left edge is the first group.
const LEFT = "(^|[^\\p{L}\\p{N}_])";
const RIGHT = "(?![\\p{L}\\p{N}_])";

function words(body: string): RegExp {
  return new RegExp(`${LEFT}(?:${body})${RIGHT}`, "giu");
}

function matches(pattern: RegExp, text: string): Match[] {
  return Array.from(text.matchAll(pattern), (match) => ({
    start: match.index + (match[1]?.length ?? 0),
    end: match.index + match[0].length,
    groups: match.slice(2),
  }));
}

function hide(text: string, { start, end }: Span): string {
  return text.slice(0, start) + HIDDEN.repeat(end - start) + text.slice(end);
}

function claim(reading: Reading, finding: Finding): void {
  reading.findings.push(finding);
  reading.masked = hide(reading.masked, finding);
}

const pad = (value: number): string => String(value).padStart(2, "0");
const clock = (minutes: number): string => `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
/** Minutes from one wall time to the next time it's `to`, across midnight if need be. */
const minutesAfter = (from: number, to: number): number =>
  (to - from + DAY_MINUTES) % DAY_MINUTES || DAY_MINUTES;

function isoDay(year: number, month: number, date: number): string | null {
  const day = new Date(Date.UTC(year, month - 1, date));
  if (day.getUTCFullYear() !== year || day.getUTCMonth() !== month - 1) return null;
  return day.toISOString().slice(0, 10);
}

/** The first of these weekdays on or after today. */
function nextOnWeekdays(today: string, weekdays: readonly number[]): string {
  return addDays(today, Math.min(...weekdays.map((day) => (day - weekdayOf(today) + 7) % 7)));
}

/** The first day of a month with this date ("the 9th") on or after today. */
function nextOnDate(today: string, date: number): string | null {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7)) - 1;
  for (let ahead = month; ahead < month + 12; ahead += 1) {
    const day = isoDay(year + Math.floor(ahead / 12), (ahead % 12) + 1, date);
    if (day && day >= today) return day;
  }
  return null;
}

/* The language's words */

/**
 * Words or a name as a pattern: the pattern characters escaped, a space as any run of spaces,
 * and every character past ASCII as `\u{…}`. A pattern made while the page runs stays ASCII
 * (the fixed ones write ’ as `\u2019` too): V8 14.6 (Node 26) cut ’ in such a pattern to one
 * byte after some thousands of parses, and "Mia’s" stopped being read (docs/GOTCHAS.md).
 */
function escape(words: string): string {
  return words
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/[^\p{ASCII}]/gu, (char) => `\\u{${(char.codePointAt(0) ?? 0).toString(16)}}`)
    .replace(/ /g, "\\s+");
}

/** A list of words as one group of a pattern, the longest first ("tues" before "tue"). A list
 * with no words matches nothing. */
function anyOf(list: readonly string[]): string {
  if (!list.length) return "(?!)";
  return `(?:${[...list]
    .sort((a, b) => b.length - a.length)
    .map(escape)
    .join("|")})`;
}

/** Each weekday's words, 0 Monday … 6 Sunday: as one day ("Tue"), and as every one ("Tuesdays"). */
const WEEKDAY_WORDS: readonly (readonly [Key, Key])[] = [
  ["quickadd.words.monday", "quickadd.words.mondays"],
  ["quickadd.words.tuesday", "quickadd.words.tuesdays"],
  ["quickadd.words.wednesday", "quickadd.words.wednesdays"],
  ["quickadd.words.thursday", "quickadd.words.thursdays"],
  ["quickadd.words.friday", "quickadd.words.fridays"],
  ["quickadd.words.saturday", "quickadd.words.saturdays"],
  ["quickadd.words.sunday", "quickadd.words.sundays"],
];

/** chrono, as Sunroom reads with it, for each of the registry's `chrono` locales it has. */
interface ChronoLocale {
  /** Its parsers without the casual words ("tonight", "this evening"); `dayFirst` reads 10/9 as
   * the 10th of September. */
  parsers: (dayFirst: boolean) => chrono.Parser[];
  /** What "@" before a time becomes ("soccer @ 4"): the word its time parser reads there, at
   * most two letters long. */
  at: string;
  /** Words it doesn't know, respelled as ones it does, never longer: English's has no "tues". */
  respell: readonly [RegExp, (word: string) => string][];
}

const ENGLISH_CHRONO: ChronoLocale = {
  parsers: (dayFirst) => chrono.en.configuration.createConfiguration(false, dayFirst).parsers,
  at: "at",
  respell: [[words("tues|weds"), (word) => word.slice(0, 3)]],
};

/** A language whose `chrono` isn't here reads with English's, which knows every way of writing
 * a date or a time in numbers ("10/9", "16:30", "4pm") and English's words. */
const CHRONO: Readonly<Record<string, ChronoLocale>> = {
  en: ENGLISH_CHRONO,
  es: {
    parsers: (dayFirst) => chrono.es.createConfiguration(false, dayFirst).parsers,
    at: "a",
    respell: [],
  },
};

/** Whether the language writes the day before the month ("9/10" for the 9th of October). */
function dayFirst(locale: string): boolean {
  const parts = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "numeric",
    timeZone: "UTC",
  }).formatToParts(new Date(Date.UTC(2026, 9, 9)));
  const at = (type: string) => parts.findIndex((part) => part.type === type);
  return at("day") < at("month");
}

/** Every pattern and word quick add reads, in one language (made once per language). */
interface Grammar {
  /** A number said as a word ("two", "second", "a"), to its value. */
  values: Map<string, number>;
  /** A weekday's word, one or every ("tue", "tuesdays"), to 0 Monday … 6 Sunday. */
  weekdays: Map<string, number>;
  weekdayWord: RegExp;
  allDay: RegExp;
  repeats: [RegExp, (groups: Groups) => RepeatWords | null][];
  lengths: [RegExp, (groups: Groups) => number][];
  whenBefore: RegExp;
  whenAfter: RegExp;
  /** The words around people's names, folded as their names are matched: "with", "and". */
  with: string;
  and: string;
  /** Months' names (folded), and what comes before one in a date: "5th of May". */
  months: Set<string>;
  dateBefore: RegExp;
  dayWords: RegExp;
  today: Set<string>;
  dayAfterTomorrow: Set<string>;
  nthDay: RegExp;
  reader: chrono.Chrono;
  respell: [RegExp, (word: string) => string][];
  weekParts: RegExp;
  notAStartTime: RegExp;
  next: RegExp;
  last: RegExp;
  shortWeekday: RegExp;
  afterThe: RegExp;
  notAStartDay: RegExp;
  betweenDays: RegExp;
  dangling: Set<string>;
  joins: Set<string>;
}

/* Numbers and weekdays as words */

/** 2 for "2", "two", "2nd" or "second" (and 1 for "a"); null for anything else. */
function numberOf(g: Grammar, word: string | undefined): number | null {
  const lower = word?.toLowerCase() ?? "";
  if (/^\d/.test(lower)) return parseInt(lower, 10);
  return g.values.get(lower) ?? null;
}

/** The weekdays a list names ("Tue and Thu"), sorted. */
function weekdaysIn(g: Grammar, list: string): number[] {
  const days = matches(g.weekdayWord, list).map(
    ({ start, end }) => g.weekdays.get(list.slice(start, end).toLowerCase()) ?? -1,
  );
  return [...new Set(days)].filter((day) => day >= 0).sort((a, b) => a - b);
}

/* Repeats */

function intervalOf(g: Grammar, [other, count, nth]: Groups): number | null {
  if (other) return 2;
  const number = numberOf(g, count ?? nth) ?? 1;
  return number >= 1 && number <= 99 ? number : null;
}

function weekly(g: Grammar, interval: number | null, list: string | undefined): RepeatWords | null {
  if (interval === null) return null;
  const weekdays = list ? weekdaysIn(g, list) : [];
  return weekdays.length ? { freq: "weekly", interval, weekdays } : { freq: "weekly", interval };
}

function monthly(interval: number | null, date: string | undefined): RepeatWords | null {
  if (interval === null) return null;
  if (date === undefined) return { freq: "monthly", interval };
  const monthDay = Number(date);
  return monthDay >= 1 && monthDay <= 31 ? { freq: "monthly", interval, monthDay } : null;
}

function every(freq: "daily" | "yearly", interval: number | null): RepeatWords | null {
  return interval === null ? null : { freq, interval };
}

/* Lengths */

function hoursOf(text: string | undefined): number {
  const whole = text?.replace("½", "").trim();
  return (whole ? Number(whole) : 0) + (text?.includes("½") ? 0.5 : 0);
}

/** The language's grammar: English's shapes, its words. */
function grammarOf(language: LanguageCode): Grammar {
  const list = (...keys: Key[]): string[] => keys.flatMap((key) => wordList(key, language));
  const any = (...keys: Key[]): string => anyOf(list(...keys));
  const lookup = (...entries: [readonly string[], number][]): Map<string, number> => {
    const found = new Map<string, number>();
    for (const [said, value] of entries)
      for (const word of said) if (!found.has(word)) found.set(word, value);
    return found;
  };

  const numbers = list("quickadd.words.numbers");
  const ones = WEEKDAY_WORDS.map(([one]) => list(one));
  const everies = WEEKDAY_WORDS.map(([, many]) => list(many));
  const values = lookup(
    [list("quickadd.words.a"), 1],
    ...numbers.map((word, index): [string[], number] => [[word], index + 1]),
    ...list("quickadd.words.ordinals").map((word, index): [string[], number] => [
      [word],
      index + 2,
    ]),
  );
  const weekdays = lookup(
    ...[...ones, ...everies].map((said, index): [string[], number] => [said, index % 7]),
  );

  // People are matched without accents (`fold`), so the words around their names are folded too.
  const anyFolded = (...keys: Key[]): string => anyOf(list(...keys).map(fold));
  const andOf = (word: string): string => `\\s*,\\s*(?:${word}\\s+)?|\\s*[&/+]\\s*|\\s+${word}\\s+`;

  const AND_WORD = any("quickadd.words.and");
  const ON = any("quickadd.words.on");
  const THE = any("quickadd.words.the");
  const OF = any("quickadd.words.of");
  const SUFFIX = any("quickadd.words.ordinal_suffixes");
  const DAYS = anyOf(everies.flat());
  const ANY_DAY = anyOf([...everies.flat(), ...ones.flat()]);
  const AND = andOf(AND_WORD);
  const DAY_LIST = `${ANY_DAY}(?:(?:${AND}|\\s+)${ANY_DAY})*`;

  // Repeats. "every Tue and Thu", also "every Tue and every Thu".
  const EVERY = `${any("quickadd.words.every")}\\s+`;
  const EVERY_DAY_LIST = `${ANY_DAY}(?:(?:${AND}|\\s+)(?:${EVERY})?${ANY_DAY})*`;
  const OTHER = any("quickadd.words.other");
  const ORDINALS = any("quickadd.words.ordinal_numbers", "quickadd.words.ordinals");
  const INTERVAL = `(?:(${OTHER})\\s+|(\\d{1,2}|${anyOf(numbers)})\\s+|(${ORDINALS})\\s+)?`;
  const ON_DAYS = `(?:\\s+${ON}\\s+(${DAY_LIST}))?`;
  const ON_DATE = `(?:\\s+${ON}\\s+${THE}\\s+(\\d{1,2})${SUFFIX}?)?`;
  const weeklyWords = new Set(list("quickadd.words.weekly"));

  // Lengths. Each pattern's first group is "for", which only some may leave out.
  const FOR = any("quickadd.words.for");
  const ABOUT = `(?:${any("quickadd.words.about")}\\s+)?`;
  const HOURS = any("quickadd.words.hour_short", "quickadd.words.hour");
  const MINUTES = any("quickadd.words.minute_short", "quickadd.words.minute");
  const hourWords = new Set(list("quickadd.words.hour"));

  const MONTHS = any("quickadd.words.months");
  const chronoLocale = CHRONO[LANGUAGES[language].chrono] ?? ENGLISH_CHRONO;
  const shortest = ones.map((said) => [...said].sort((a, b) => a.length - b.length)[0] ?? "");
  const boundedBy = (key: Key) => new RegExp(`${LEFT}${any(key)}${RIGHT}`, "iu");
  const ending = (key: Key) => new RegExp(`(?:^|[^\\p{L}\\p{N}_])${any(key)}\\s*$`, "iu");

  const g: Grammar = {
    values,
    weekdays,
    weekdayWord: words(ANY_DAY),
    allDay: words(any("quickadd.words.all_day")),
    // In this order: the words one pattern found are hidden from the ones after it.
    repeats: [
      [
        words(`${EVERY}${INTERVAL}${any("quickadd.words.week")}${ON_DAYS}`),
        (groups) => weekly(g, intervalOf(g, groups), groups[3]),
      ],
      [
        words(`${EVERY}${INTERVAL}${any("quickadd.words.month")}${ON_DATE}`),
        (groups) => monthly(intervalOf(g, groups), groups[3]),
      ],
      [
        words(`${EVERY}${INTERVAL}${any("quickadd.words.day")}`),
        (groups) => every("daily", intervalOf(g, groups)),
      ],
      [
        words(`${EVERY}${INTERVAL}${any("quickadd.words.year")}`),
        (groups) => every("yearly", intervalOf(g, groups)),
      ],
      [
        words(
          `${EVERY}${any("quickadd.words.weekday", "quickadd.words.weekdays")}|(?:${ON}\\s+)?${any("quickadd.words.weekdays")}`,
        ),
        () => ({ freq: "weekly", interval: 1, weekdays: WORKWEEK }),
      ],
      [
        words(
          `${EVERY}${any("quickadd.words.weekend", "quickadd.words.weekends")}|(?:${ON}\\s+)?${any("quickadd.words.weekends")}`,
        ),
        () => ({ freq: "weekly", interval: 1, weekdays: WEEKEND }),
      ],
      [
        words(`${EVERY}(${OTHER}\\s+)?(${EVERY_DAY_LIST})`),
        ([other, days]) => weekly(g, other ? 2 : 1, days),
      ],
      [words(`(?:${ON}\\s+)?(${DAYS}(?:(?:${AND}|\\s+)${DAYS})*)`), ([days]) => weekly(g, 1, days)],
      [
        words(`(${any("quickadd.words.weekly", "quickadd.words.fortnightly")})${ON_DAYS}`),
        ([word, days]) => weekly(g, weeklyWords.has(word?.toLowerCase() ?? "") ? 1 : 2, days),
      ],
      [words(`${any("quickadd.words.monthly")}${ON_DATE}`), ([date]) => monthly(1, date)],
      [words(any("quickadd.words.daily")), () => every("daily", 1)],
      [words(any("quickadd.words.yearly")), () => every("yearly", 1)],
    ],
    lengths: [
      [words(`(${FOR}\\s+)${ABOUT}${any("quickadd.words.hour_and_a_half")}`), () => 90],
      [words(`(${FOR}\\s+)${ABOUT}${any("quickadd.words.half_hour")}`), () => 30],
      [
        words(
          `(${FOR}\\s+)${ABOUT}(${any("quickadd.words.a", "quickadd.words.numbers")})\\s+(${any("quickadd.words.hour", "quickadd.words.minute")})`,
        ),
        ([, count, unit]) =>
          (numberOf(g, count) ?? 0) * (hourWords.has(unit?.toLowerCase() ?? "") ? 60 : 1),
      ],
      [
        words(
          `(${FOR}\\s+${ABOUT})?(\\d+(?:\\.\\d+)?\\s*\\u00bd?|\\u00bd)\\s*${HOURS}(?:\\s*(?:${AND_WORD}\\s+)?(\\d{1,2})\\s*${MINUTES}|(\\d{2}))?`,
        ),
        ([, hours, minutes, attached]) => hoursOf(hours) * 60 + Number(minutes ?? attached ?? 0),
      ],
      [words(`(${FOR}\\s+${ABOUT})?(\\d+)\\s*${MINUTES}`), ([, minutes]) => Number(minutes)],
    ],
    // Without "for", "in 30 min" and "2 hours later" say when, not how long.
    whenBefore: ending("quickadd.words.when_before"),
    whenAfter: new RegExp(`^\\s*${any("quickadd.words.when_after")}${RIGHT}`, "iu"),
    with: anyFolded("quickadd.words.with"),
    and: andOf(anyFolded("quickadd.words.and")),
    months: new Set(list("quickadd.words.months").map(fold)),
    // "5th of May": a month's name after a date.
    dateBefore: new RegExp(
      `\\d${anyFolded("quickadd.words.ordinal_suffixes")}?\\s+(?:${anyFolded("quickadd.words.of")}\\s+)?$`,
      "iu",
    ),
    dayWords: words(
      any("quickadd.words.day_after_tomorrow", "quickadd.words.today", "quickadd.words.tomorrow"),
    ),
    today: new Set(list("quickadd.words.today")),
    dayAfterTomorrow: new Set(list("quickadd.words.day_after_tomorrow")),
    // "on the 9th", but not "the 4th of July", which chrono reads whole.
    nthDay: words(`(?:${ON}\\s+)?${THE}\\s+(\\d{1,2})${SUFFIX}(?!\\s+(?:${OF}\\s+)?${MONTHS})`),
    // chrono's parsers without its casual words ("tonight", "this evening") or its refiners:
    // which day a weekday means, the year of a date and how results combine are decided here.
    reader: new chrono.Chrono({
      parsers: chronoLocale.parsers(dayFirst(LANGUAGES[language].locale)),
      refiners: [],
    }),
    // Words chrono reads once respelled, at the same length so every offset still holds.
    respell: [
      [words(`(?:12\\s*)?${any("quickadd.words.noon")}`), () => "12pm"],
      [words(`(?:12\\s*)?${any("quickadd.words.midnight")}`), () => "12am"],
      ...chronoLocale.respell,
      [/()@\s/gu, () => chronoLocale.at], // "soccer @ 4"
    ],
    weekParts: words(
      any(
        "quickadd.words.weekday",
        "quickadd.words.weekdays",
        "quickadd.words.weekend",
        "quickadd.words.weekends",
      ),
    ),
    // A time after these ends something rather than starting it: "Library until 5pm".
    notAStartTime: ending("quickadd.words.ends_time"),
    next: boundedBy("quickadd.words.next"),
    last: boundedBy("quickadd.words.last"),
    // A weekday's shortest word, as an acronym looks: "SAT prep".
    shortWeekday: new RegExp(`${LEFT}(${anyOf(shortest)})${RIGHT}`, "iu"),
    afterThe: new RegExp(`(?:^|[^\\p{L}\\p{N}_])${THE}\\s+$`, "iu"),
    // A day after these ends something rather than starting it: "every Tue until Dec 31".
    notAStartDay: ending("quickadd.words.ends_day"),
    // What joins the days of a list or a range: "Mon/Wed/Fri", "Sat and Sun", "Oct 20 - Oct 23".
    betweenDays: new RegExp(
      `^\\s*(?:,\\s*)?(?:${any("quickadd.words.between_days")}|&|\\/|\\+|-|\\u2013|\\u2014)?\\s*$`,
      "iu",
    ),
    // Words that only join a title to what was taken out of it: "Dentist on [Oct 9]".
    dangling: new Set(list("quickadd.words.joining")),
    joins: new Set(list("quickadd.words.and")),
  };
  return g;
}

const grammars = new Map<LanguageCode, Grammar>();

/** The page's language's grammar (the pseudo language types English). */
function grammar(): Grammar {
  const page = getLanguage();
  const language = page === "pseudo" ? "en" : page;
  let found = grammars.get(language);
  if (!found) {
    found = grammarOf(language);
    grammars.set(language, found);
  }
  return found;
}

/* "all day" */

function readAllDay(g: Grammar, reading: Reading): void {
  for (const { start, end } of matches(g.allDay, reading.masked)) {
    claim(reading, { kind: "allDay", start, end });
  }
}

function readRepeats(g: Grammar, reading: Reading): void {
  for (const [pattern, read] of g.repeats) {
    for (const { start, end, groups } of matches(pattern, reading.masked)) {
      const repeat = read(groups);
      if (repeat) claim(reading, { kind: "repeat", start, end, words: repeat });
    }
  }
}

function readLengths(g: Grammar, reading: Reading): void {
  for (const [pattern, read] of g.lengths) {
    for (const { start, end, groups } of matches(pattern, reading.masked)) {
      const minutes = Math.round(read(groups));
      if (!(minutes >= 1 && minutes <= DAY_MINUTES)) continue;
      const loose = !groups[0];
      if (loose && g.whenBefore.test(reading.masked.slice(0, start))) continue;
      if (loose && g.whenAfter.test(reading.masked.slice(end))) continue;
      claim(reading, { kind: "length", start, end, minutes });
    }
  }
}

/* People */

/**
 * Lowercase without accents, one character for each one given, so positions in what was typed
 * still line up (the server's `domain/people.fold`): Zoë and Zoe meet.
 */
function fold(text: string): string {
  let out = "";
  for (const char of text.split(""))
    out += (char.normalize("NFKD")[0] ?? char).toLowerCase()[0] ?? char;
  return out;
}

const folded = (name: string): string => fold(name.trim()).replace(/\s+/g, " ");

/**
 * What each person can be called (ADR 0034, as `domain/people.py`): their full name, and for a
 * name of several words its first word, unless that is someone else's whole name or the first
 * word of another name too; never under two letters. Folded, to whose it is.
 */
function callNames(members: readonly QuickAddMember[]): Map<string, string> {
  const keys = members.map((member) => folded(member.name));
  const whole = new Set(keys);
  const firsts = new Map<string, number>();
  for (const key of keys) {
    const [first, ...rest] = key.split(" ");
    if (first && rest.length) firsts.set(first, (firsts.get(first) ?? 0) + 1);
  }
  const names = new Map<string, string>();
  members.forEach((member, index) => {
    const key = keys[index] ?? "";
    if (key.replace(/ /g, "").length >= 2 && !names.has(key)) names.set(key, member.id);
    const [first, ...rest] = key.split(" ");
    if (first && rest.length && first.length >= 2 && !whole.has(first) && firsts.get(first) === 1)
      names.set(first, member.id);
  });
  return names;
}

function readPeople(g: Grammar, reading: Reading, members: readonly QuickAddMember[]): void {
  const called = callNames(members);
  if (!called.size) return;
  // Longest first, so "Ana Sofia" wins over "Ana".
  const names = [...called.keys()]
    .sort((a, b) => b.length - a.length)
    .map(escape)
    .join("|");
  const name = `(?:${names})(?:['\\u2019]s)?`;
  const group = words(`(${g.with}\\s*)?(${name}(?:(?:${g.and})${name})*)`);
  const one = words(`(${names})(['\\u2019]s)?`);
  // Matched without accents; the positions are the typed text's.
  const text = fold(reading.masked);
  for (const { start, end, groups } of matches(group, text)) {
    const said = matches(one, groups[1] ?? "");
    const first = folded(said[0]?.groups[0] ?? "");
    // A month's name beside a number is a date: "May 5", "5 May".
    if (said.length === 1 && g.months.has(first)) {
      const after = text.slice(end);
      const before = text.slice(0, start);
      if (/^\s*\d/.test(after) || g.dateBefore.test(before)) continue;
    }
    const spoken = new Set(said.map((match) => called.get(folded(match.groups[0] ?? ""))));
    const ids = members.filter((member) => spoken.has(member.id)).map(({ id }) => id);
    const possessive = said.some((match) => Boolean(match.groups[1]));
    if (ids.length) claim(reading, { kind: "who", start, end, ids, possessive });
  }
}

/* Casual day words */

function readDayWords(g: Grammar, reading: Reading, today: string): void {
  for (const { start, end } of matches(g.dayWords, reading.masked)) {
    const word = reading.text.slice(start, end).toLowerCase().replace(/\s+/g, " ");
    const ahead = g.dayAfterTomorrow.has(word) ? 2 : g.today.has(word) ? 0 : 1;
    claim(reading, { kind: "day", start, end, day: addDays(today, ahead), source: "word" });
  }
  for (const { start, end, groups } of matches(g.nthDay, reading.masked)) {
    const day = nextOnDate(today, Number(groups[0]));
    if (day) claim(reading, { kind: "day", start, end, day, source: "date" });
  }
}

/* Dates and times, read by chrono */

const DATE_PARTS: chrono.Component[] = ["day", "month", "weekday", "year"];

/** "Thu" is the next Thursday on or after today; "next Thu" the one in the following week. */
function weekdayDay(
  g: Grammar,
  result: chrono.ParsedResult,
  today: string,
  weekStartsOn: number,
): string {
  const weekday = ((result.start.get("weekday") ?? 1) + 6) % 7; // chrono counts from Sunday
  const ahead = (weekday - weekdayOf(today) + 7) % 7;
  if (g.next.test(result.text)) {
    const nextWeek = addDays(weekOf(today, weekStartsOn)[0] ?? today, 7);
    return addDays(nextWeek, (weekday - weekStartsOn + 7) % 7);
  }
  if (g.last.test(result.text)) return addDays(today, ahead - 7);
  return addDays(today, ahead);
}

/** The month and day on or after today (a past one is next year's), or in the year said. */
function dateDay(result: chrono.ParsedResult, today: string): string | null {
  const month = result.start.get("month");
  const date = result.start.get("day");
  const year = result.start.get("year");
  if (month === null || date === null) return null;
  if (result.start.isCertain("year") && year !== null) return isoDay(year, month, date);
  const thisYear = Number(today.slice(0, 4));
  for (let next = thisYear; next <= thisYear + 8; next += 1) {
    const day = isoDay(next, month, date);
    if (day && day >= today) return day;
  }
  return null;
}

const minutesOf = (components: chrono.ParsedComponents): number =>
  (components.get("hour") ?? 0) * 60 + (components.get("minute") ?? 0);

/** A time or a range in minutes after midnight, am and pm settled as a family means them. */
function readClock(result: chrono.ParsedResult): { from: number; to: number | null } {
  const { start, end } = result;
  let from = minutesOf(start);
  const startHour = start.get("hour") ?? 0;
  if (!start.isCertain("meridiem")) {
    if (end?.isCertain("meridiem")) {
      // chrono gave the start the end's am or pm: right for "4-5pm", not for "11-1pm".
      if (startHour >= 12 && from > minutesOf(end)) from -= HALF_DAY;
    } else if (startHour >= 1 && startHour <= 7 && !/^\D*0\d/.test(result.text)) {
      // A bare "at 4" is the next sensible hour: 1–7 PM, 8–11 AM. "07:30" is a 24-hour time.
      from += HALF_DAY;
    }
  }
  if (!end) return { from, to: null };
  let to = minutesOf(end);
  const endHour = end.get("hour") ?? 0;
  if (!end.isCertain("meridiem") && endHour <= 12) {
    // Whichever of its am and pm comes first after the start: "at 4-5", "10am-2".
    const morning = (endHour % 12) * 60 + (end.get("minute") ?? 0);
    const evening = morning + HALF_DAY;
    to = minutesAfter(from, morning) < minutesAfter(from, evening) ? morning : evening;
  }
  return { from, to: to === from ? null : to };
}

function readChrono(g: Grammar, reading: Reading, today: string, weekStartsOn: number): void {
  let text = reading.masked;
  const respelled: Span[] = [];
  for (const [pattern, spell] of g.respell) {
    for (const { start, end } of matches(pattern, text)) {
      const word = text.slice(start, end);
      const spelled = spell(word);
      if (spelled.length > word.length) continue; // it would move every offset after it
      text = text.slice(0, start) + spelled.padEnd(word.length) + text.slice(end);
      respelled.push({ start, end });
    }
  }
  // "weekend" and "weekday" on their own stay in the title rather than meaning a Saturday.
  for (const span of matches(g.weekParts, text)) text = hide(text, span);

  const [year = 1970, month = 1, date = 1] = today.split("-").map(Number);
  // Noon on the household's today in the device's zone: chrono only takes the date from it.
  const reference = new Date(year, month - 1, date, 12);
  const kept: chrono.ParsedResult[] = [];
  for (const result of g.reader.parse(text, reference)) {
    if (result.text.includes(HIDDEN) || result.start.tags().has("result/relativeDate")) continue;
    if (/^\d*(?:\.\d*)?$/.test(result.text.replace(/\s/g, ""))) continue; // a bare "20"
    // Of two readings that overlap, keep the longer, as chrono's own refiner does.
    const last = kept.at(-1);
    if (last && result.index < last.index + last.text.length) {
      if (result.text.length <= last.text.length) continue;
      kept.pop();
    }
    kept.push(result);
  }

  for (const result of kept) {
    const span = { start: result.index, end: result.index + result.text.trimEnd().length };
    for (const word of respelled) {
      if (word.start < span.end && word.end > span.start) {
        span.start = Math.min(span.start, word.start);
        span.end = Math.max(span.end, word.end);
      }
    }
    const before = reading.text.slice(0, span.start);
    const parts = result.start;
    const hasDate = DATE_PARTS.some((part) => parts.isCertain(part));
    if (parts.isCertain("hour")) {
      if (hasDate || g.notAStartTime.test(before)) continue;
      claim(reading, { kind: "time", ...span, ...readClock(result) });
    } else if (hasDate && !result.end) {
      if (parts.isCertain("weekday") && !parts.isCertain("day")) {
        // "Fun in the sun" and "SAT prep" don't name days.
        const short = g.shortWeekday.exec(result.text)?.[2];
        const acronym = short === short?.toUpperCase() && /\p{Ll}/u.test(reading.text);
        if ((short !== undefined && acronym) || g.afterThe.test(before)) continue;
        const day = weekdayDay(g, result, today, weekStartsOn);
        claim(reading, { kind: "day", ...span, day, source: "weekday" });
      } else if (parts.isCertain("day") && parts.isCertain("month")) {
        // A month alone ("March 2027") names no day.
        const day = dateDay(result, today);
        const slash = result.start.tags().has("parser/SlashDateFormatParser");
        if (day) claim(reading, { kind: "day", ...span, day, source: slash ? "slash" : "date" });
      }
    }
  }
}

/* Settling the days */

const BESIDE = /^[\s,]*$/;

/**
 * Days said together become one: "Thu, Oct 9" is the date and its weekday, "tomorrow Thu" the
 * same day twice. Several different days ("Mon/Wed/Fri", "Sat and Sun", "Oct 20 - Oct 23") are
 * no single day, so they stay in the title, as does a day that ends something.
 */
function settleDays(g: Grammar, reading: Reading): void {
  const { text } = reading;
  const days: Extract<Finding, { kind: "day" }>[] = [];
  for (const finding of reading.findings) if (finding.kind === "day") days.push(finding);
  days.sort((a, b) => a.start - b.start);

  const joined: typeof days = [];
  for (const day of days) {
    const previous = joined.at(-1);
    if (previous && BESIDE.test(text.slice(previous.end, day.start))) {
      const pair = [previous, day];
      const weekday = pair.find((one) => one.source === "weekday");
      const date = pair.find((one) => one.source !== "weekday" && one.source !== "word");
      if (previous.day === day.day || (weekday && date)) {
        const source = date?.source ?? previous.source;
        joined[joined.length - 1] = {
          ...previous,
          end: day.end,
          day: date?.day ?? day.day,
          source,
        };
        continue;
      }
    }
    joined.push(day);
  }

  const settled = joined.filter((day, index) => {
    const previous = joined[index - 1];
    const next = joined[index + 1];
    if (previous && g.betweenDays.test(text.slice(previous.end, day.start))) return false;
    if (next && g.betweenDays.test(text.slice(day.end, next.start))) return false;
    return !g.notAStartDay.test(text.slice(0, day.start));
  });
  reading.findings = [...reading.findings.filter((finding) => finding.kind !== "day"), ...settled];
}

/* The draft */

const CONNECTORS = "[\\s,;:&+@/\\-\\u2013\\u2014]+";
const LEADING_MARKS = new RegExp(`^${CONNECTORS}`, "u");
const TRAILING_MARKS = new RegExp(`${CONNECTORS}$`, "u");
const FIRST_WORD = /^[\p{L}\p{N}'’]+/u;
const LAST_WORD = /[\p{L}\p{N}'’]+$/u;

const tidy = (text: string): string => text.replace(/\s+/g, " ").trim();

/** A piece of the title between found words, without joining words left hanging at its ends. */
function trimPiece(g: Grammar, piece: string): string {
  let rest = piece;
  let previous: string;
  do {
    previous = rest;
    rest = rest.replace(TRAILING_MARKS, "");
    const last = LAST_WORD.exec(rest)?.[0];
    if (last && g.dangling.has(last.toLowerCase())) rest = rest.slice(0, -last.length);
  } while (rest !== previous);
  do {
    previous = rest;
    rest = rest.replace(LEADING_MARKS, "");
    const first = FIRST_WORD.exec(rest)?.[0];
    if (first && g.joins.has(first.toLowerCase())) rest = rest.slice(first.length);
  } while (rest !== previous);
  // A lone "!" or "." left from "Party Sat!" goes too.
  return /[\p{L}\p{N}]/u.test(rest) ? rest : "";
}

function titleOf(g: Grammar, text: string, cuts: readonly Span[]): string {
  const pieces: string[] = [];
  let at = 0;
  for (const cut of cuts) {
    pieces.push(text.slice(at, cut.start));
    at = cut.end;
  }
  pieces.push(text.slice(at));
  return tidy(pieces.map((piece) => trimPiece(g, piece)).join(" "));
}

function hasTitleWord(g: Grammar, text: string): boolean {
  const found = text.match(/[\p{L}\p{N}][\p{L}\p{N}'’]*/gu) ?? [];
  return found.some((word) => !g.dangling.has(word.toLowerCase()));
}

/** "Mia's recital", "Take Leo to soccer": the name is part of the title too. */
function inTitle(g: Grammar, text: string, used: readonly Finding[], index: number): boolean {
  const finding = used[index];
  if (finding?.kind !== "who") return false;
  if (finding.possessive) return true;
  const before = text.slice(used[index - 1]?.end ?? 0, finding.start);
  const after = text.slice(finding.end, used[index + 1]?.start ?? text.length);
  return hasTitleWord(g, before) && hasTitleWord(g, after);
}

function draftOf(g: Grammar, reading: Reading, ctx: QuickAddContext, today: string): QuickAddDraft {
  const { text } = reading;
  const ordered = [...reading.findings].sort((a, b) => a.start - b.start);
  const first = <K extends UnderstoodKind>(kind: K) =>
    ordered.find((finding): finding is Extract<Finding, { kind: K }> => finding.kind === kind);
  // The first of each kind counts, but "10/9" only when no other day was said ("Grade 3/4 concert
  // Nov 12"). "all day" overrules a time, and a range a length.
  const allDaySaid = first("allDay");
  const days = ordered.filter((finding) => finding.kind === "day");
  const daySaid = days.find((finding) => finding.source !== "slash") ?? days[0];
  const time = allDaySaid ? undefined : first("time");
  const length = allDaySaid || (time && time.to !== null) ? undefined : first("length");
  const repeatSaid = first("repeat");
  const chosen = new Set<Finding | undefined>([allDaySaid, daySaid, time, length, repeatSaid]);
  const used = ordered.filter((finding) => finding.kind === "who" || chosen.has(finding));
  if (!used.length) {
    return {
      title: tidy(text),
      day: null,
      allDay: true,
      start: null,
      end: null,
      durationMinutes: null,
      memberIds: [],
      repeat: null,
      understood: [],
    };
  }

  let day = daySaid?.day ?? null;
  let repeat: Repeat | null = null;
  if (repeatSaid) {
    const { freq, interval, weekdays, monthDay } = repeatSaid.words;
    // "every Tue" starts on the next Tuesday and "monthly on the 1st" on the next 1st, unless
    // the day tapped on the board is already one of them.
    const tapped = ctx.defaultDay >= today ? ctx.defaultDay : null;
    if (!day && weekdays && !(tapped && weekdays.includes(weekdayOf(tapped)))) {
      day = nextOnWeekdays(today, weekdays);
    }
    if (!day && monthDay && Number(tapped?.slice(8)) !== monthDay) {
      day = nextOnDate(today, monthDay);
    }
    if (freq === "weekly") {
      repeat = {
        freq,
        interval,
        weekdays: weekdays ? [...weekdays] : [weekdayOf(day ?? ctx.defaultDay)],
      };
    } else if (freq === "monthly") {
      repeat = { freq, interval, by: "date" };
    } else {
      repeat = { freq, interval };
    }
  }

  let end: string | null = null;
  let durationMinutes = length?.minutes ?? null;
  if (time && time.to !== null) {
    end = clock(time.to);
    durationMinutes = minutesAfter(time.from, time.to);
  } else if (time && length) {
    end = clock((time.from + length.minutes) % DAY_MINUTES);
  }

  const named = new Set(used.flatMap((finding) => (finding.kind === "who" ? finding.ids : [])));
  const cuts = used.filter((_, index) => !inTitle(g, text, used, index));
  return {
    title: titleOf(g, text, cuts),
    day,
    allDay: !time,
    start: time ? clock(time.from) : null,
    end,
    durationMinutes,
    memberIds: ctx.members.filter(({ id }) => named.has(id)).map(({ id }) => id),
    repeat,
    understood: used.map((finding) => ({
      kind: finding.kind,
      start: finding.start,
      end: finding.end,
    })),
  };
}

/** The line read as a draft, with the page's language's words. */
export function parseQuickAdd(text: string, ctx: QuickAddContext): QuickAddDraft {
  const g = grammar();
  const today = zonedParts(ctx.now, ctx.zone).day;
  const reading: Reading = { text, masked: text, findings: [] };
  readAllDay(g, reading);
  readRepeats(g, reading);
  readLengths(g, reading);
  readPeople(g, reading, ctx.members);
  readDayWords(g, reading, today);
  readChrono(g, reading, today, ctx.weekStartsOn);
  settleDays(g, reading);
  return draftOf(g, reading, ctx, today);
}
