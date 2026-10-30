import { afterEach, describe, expect, it, vi } from "vitest";

import { setLanguage } from "../../lib/lang";
import { parseQuickAdd, type QuickAddContext, type QuickAddDraft } from "./quickAdd";
import type { Repeat } from "./repeat";

const ANA = "member-ana";
const SAM = "member-sam";
const MIA = "member-mia";
const LEO = "member-leo";

// Wednesday Oct 7, 2026 at 9:41 AM in New York; the household's week starts on Sunday.
const household: QuickAddContext = {
  now: new Date("2026-10-07T13:41:00Z"),
  zone: "America/New_York",
  weekStartsOn: 6,
  members: [
    { id: ANA, name: "Ana" },
    { id: SAM, name: "Sam" },
    { id: MIA, name: "Mia" },
    { id: LEO, name: "Leo" },
  ],
  defaultDay: "2026-10-07",
};

const BLANK: Omit<QuickAddDraft, "understood"> = {
  title: "",
  day: null,
  allDay: true,
  start: null,
  end: null,
  durationMinutes: null,
  memberIds: [],
  repeat: null,
};

function parse(text: string, ctx: Partial<QuickAddContext> = {}): QuickAddDraft {
  return parseQuickAdd(text, { ...household, ...ctx });
}

/** The understood spans as "kind words", e.g. "time 2:30pm". */
function understood(text: string, draft: QuickAddDraft): string[] {
  return draft.understood.map(({ kind, start, end }) => `${kind} ${text.slice(start, end)}`);
}

interface Case {
  text: string;
  draft: Partial<Omit<QuickAddDraft, "understood">>;
  words: string[];
}

function reads(cases: Case[]): void {
  it.each(cases)("$text", ({ text, draft, words }) => {
    const parsed = parse(text);
    expect({ ...parsed, understood: [] }).toEqual({ ...BLANK, ...draft, understood: [] });
    expect(understood(text, parsed)).toEqual(words);
  });
}

const weekly = (interval: number, weekdays: number[]): Repeat => ({
  freq: "weekly",
  interval,
  weekdays,
});

describe("the phrases in the plan", () => {
  reads([
    {
      // No length is invented: the editor applies its own one-hour default.
      text: "Dentist Thu 2:30pm Mia",
      draft: {
        title: "Dentist",
        day: "2026-10-08",
        allDay: false,
        start: "14:30",
        memberIds: [MIA],
      },
      words: ["day Thu", "time 2:30pm", "who Mia"],
    },
    {
      text: "Soccer practice every Tue 4-5pm Mia",
      draft: {
        title: "Soccer practice",
        day: "2026-10-13",
        allDay: false,
        start: "16:00",
        end: "17:00",
        durationMinutes: 60,
        memberIds: [MIA],
        repeat: weekly(1, [1]),
      },
      words: ["repeat every Tue", "time 4-5pm", "who Mia"],
    },
    {
      text: "Pajama day Fri all day Leo",
      draft: { title: "Pajama day", day: "2026-10-09", memberIds: [LEO] },
      words: ["day Fri", "allDay all day", "who Leo"],
    },
    {
      // "at" stays when no time follows it; no day was said, so the editor's day (today) holds.
      text: "Dinner at Grandma's 6:30pm",
      draft: { title: "Dinner at Grandma's", allDay: false, start: "18:30" },
      words: ["time 6:30pm"],
    },
    {
      // Today (the editor's day) is a weekday already, so the day is left to the editor.
      text: "Piano lesson weekdays 3pm for 30 min Leo",
      draft: {
        title: "Piano lesson",
        allDay: false,
        start: "15:00",
        end: "15:30",
        durationMinutes: 30,
        memberIds: [LEO],
        repeat: weekly(1, [0, 1, 2, 3, 4]),
      },
      words: ["repeat weekdays", "time 3pm", "length for 30 min", "who Leo"],
    },
    {
      text: "Book club next Tue 7pm with Ana and Sam",
      draft: {
        title: "Book club",
        day: "2026-10-13",
        allDay: false,
        start: "19:00",
        memberIds: [ANA, SAM],
      },
      words: ["day next Tue", "time 7pm", "who with Ana and Sam"],
    },
    {
      // Lengths are for timed events; a stay of several days is left in the title.
      text: "Trip Oct 20 for 3 days",
      draft: { title: "Trip for 3 days", day: "2026-10-20" },
      words: ["day Oct 20"],
    },
    {
      text: "Vet 10/9 at 9",
      draft: { title: "Vet", day: "2026-10-09", allDay: false, start: "09:00" },
      words: ["day 10/9", "time at 9"],
    },
    {
      text: "Haircut tomorrow noon",
      draft: { title: "Haircut", day: "2026-10-08", allDay: false, start: "12:00" },
      words: ["day tomorrow", "time noon"],
    },
    { text: "Movie night", draft: { title: "Movie night" }, words: [] },
    {
      // A possessive name sets Who and stays in the title, where it belongs.
      text: "Mia's recital Nov 2 6pm",
      draft: {
        title: "Mia's recital",
        day: "2026-11-02",
        allDay: false,
        start: "18:00",
        memberIds: [MIA],
      },
      words: ["who Mia's", "day Nov 2", "time 6pm"],
    },
    {
      text: "Call 14:30",
      draft: { title: "Call", allDay: false, start: "14:30" },
      words: ["time 14:30"],
    },
    {
      text: "every other week Sat 10am Swim Mia",
      draft: {
        title: "Swim",
        day: "2026-10-10",
        allDay: false,
        start: "10:00",
        memberIds: [MIA],
        repeat: weekly(2, [5]),
      },
      words: ["repeat every other week", "day Sat", "time 10am", "who Mia"],
    },
    {
      text: "Garbage night every Monday",
      draft: { title: "Garbage night", day: "2026-10-12", repeat: weekly(1, [0]) },
      words: ["repeat every Monday"],
    },
    {
      text: "Lunch with Leo at noon",
      draft: { title: "Lunch", allDay: false, start: "12:00", memberIds: [LEO] },
      words: ["who with Leo", "time at noon"],
    },
  ]);
});

describe("days", () => {
  reads([
    { text: "Pizza today", draft: { title: "Pizza", day: "2026-10-07" }, words: ["day today"] },
    { text: "Pizza tonight", draft: { title: "Pizza", day: "2026-10-07" }, words: ["day tonight"] },
    {
      text: "Pizza the day after tomorrow",
      draft: { title: "Pizza", day: "2026-10-09" },
      words: ["day the day after tomorrow"],
    },
    {
      // Today's weekday is today, even after the time has passed: never a day in the past.
      text: "Swim Wed 9am",
      draft: { title: "Swim", day: "2026-10-07", allDay: false, start: "09:00" },
      words: ["day Wed", "time 9am"],
    },
    { text: "Party Sat", draft: { title: "Party", day: "2026-10-10" }, words: ["day Sat"] },
    {
      text: "Party next Sat",
      draft: { title: "Party", day: "2026-10-17" },
      words: ["day next Sat"],
    },
    {
      text: "Party on Saturday",
      draft: { title: "Party", day: "2026-10-10" },
      words: ["day on Saturday"],
    },
    {
      text: "Soccer Tues 4pm",
      draft: { title: "Soccer", day: "2026-10-13", allDay: false, start: "16:00" },
      words: ["day Tues", "time 4pm"],
    },
    {
      text: "Dentist Thu, Oct 8 at 2",
      draft: { title: "Dentist", day: "2026-10-08", allDay: false, start: "14:00" },
      words: ["day Thu, Oct 8", "time at 2"],
    },
    { text: "Picnic 9 Oct", draft: { title: "Picnic", day: "2026-10-09" }, words: ["day 9 Oct"] },
    {
      text: "Picnic October 9th",
      draft: { title: "Picnic", day: "2026-10-09" },
      words: ["day October 9th"],
    },
    {
      text: "Dentist on Oct 9",
      draft: { title: "Dentist", day: "2026-10-09" },
      words: ["day Oct 9"],
    },
    {
      // A date that has passed this year is next year's.
      text: "Picnic Oct 6",
      draft: { title: "Picnic", day: "2027-10-06" },
      words: ["day Oct 6"],
    },
    { text: "Picnic 10/6", draft: { title: "Picnic", day: "2027-10-06" }, words: ["day 10/6"] },
    {
      text: "Leap day Feb 29",
      draft: { title: "Leap day", day: "2028-02-29" },
      words: ["day Feb 29"],
    },
    {
      text: "Wedding Oct 1, 2027",
      draft: { title: "Wedding", day: "2027-10-01" },
      words: ["day Oct 1, 2027"],
    },
    {
      text: "Birthday Oct 9 yearly",
      draft: { title: "Birthday", day: "2026-10-09", repeat: { freq: "yearly", interval: 1 } },
      words: ["day Oct 9", "repeat yearly"],
    },
    {
      text: "Dentist on the 14th",
      draft: { title: "Dentist", day: "2026-10-14" },
      words: ["day on the 14th"],
    },
    {
      text: "Dentist Wednesday the 14th",
      draft: { title: "Dentist", day: "2026-10-14" },
      words: ["day Wednesday the 14th"],
    },
    {
      text: "Dentist the 3rd",
      draft: { title: "Dentist", day: "2026-11-03" },
      words: ["day the 3rd"],
    },
    {
      text: "Fireworks the 4th of July",
      draft: { title: "Fireworks", day: "2027-07-04" },
      words: ["day 4th of July"],
    },
    {
      // The same day said twice is one day.
      text: "Dentist tomorrow Thu 2pm",
      draft: { title: "Dentist", day: "2026-10-08", allDay: false, start: "14:00" },
      words: ["day tomorrow Thu", "time 2pm"],
    },
    {
      // A numeric date gives way to any other day: here "3/4" is a grade.
      text: "Grade 3/4 concert Nov 12 6pm",
      draft: { title: "Grade 3/4 concert", day: "2026-11-12", allDay: false, start: "18:00" },
      words: ["day Nov 12", "time 6pm"],
    },
    {
      // Several days are no single day: they stay in the title for the editor to settle.
      text: "Gym Mon/Wed/Fri 6am",
      draft: { title: "Gym Mon/Wed/Fri", allDay: false, start: "06:00" },
      words: ["time 6am"],
    },
    { text: "Swim Sat Sun", draft: { title: "Swim Sat Sun" }, words: [] },
    { text: "Camp Mon-Fri", draft: { title: "Camp Mon-Fri" }, words: [] },
    { text: "Camp Mon through Fri", draft: { title: "Camp Mon through Fri" }, words: [] },
    { text: "Beach trip Oct 20-23", draft: { title: "Beach trip Oct 20-23" }, words: [] },
    {
      text: "Beach trip Oct 20 - Oct 23",
      draft: { title: "Beach trip Oct 20 - Oct 23" },
      words: [],
    },
    { text: "Dentist today Thu", draft: { title: "Dentist today Thu" }, words: [] },
    { text: "Return books before Fri", draft: { title: "Return books before Fri" }, words: [] },
    // Not days: an article before "sun", an acronym, a weekend, a span from now.
    { text: "Fun in the sun", draft: { title: "Fun in the sun" }, words: [] },
    {
      text: "SAT prep Thu 4pm",
      draft: { title: "SAT prep", day: "2026-10-08", allDay: false, start: "16:00" },
      words: ["day Thu", "time 4pm"],
    },
    { text: "Camping weekend", draft: { title: "Camping weekend" }, words: [] },
    { text: "Call Mom in 2 days", draft: { title: "Call Mom in 2 days" }, words: [] },
    { text: "Trip 2027 March", draft: { title: "Trip 2027 March" }, words: [] },
  ]);

  it("counts the following week from the household's first day", () => {
    expect(parse("Brunch next Sun").day).toBe("2026-10-11");
    expect(parse("Brunch next Sun", { weekStartsOn: 0 }).day).toBe("2026-10-18");
    expect(parse("Brunch Sun", { weekStartsOn: 0 }).day).toBe("2026-10-11");
  });

  it("leaves the day to the editor when none was said", () => {
    expect(parse("Call 14:30", { defaultDay: "2026-10-09" }).day).toBeNull();
  });
});

describe("times", () => {
  const at = (text: string) => {
    const { start, end, durationMinutes } = parse(`Call ${text}`);
    return [start, end, durationMinutes];
  };

  it("reads clock times", () => {
    expect(at("2:30pm")).toEqual(["14:30", null, null]);
    expect(at("2:30 pm")).toEqual(["14:30", null, null]);
    expect(at("2pm")).toEqual(["14:00", null, null]);
    expect(at("9 a.m.")).toEqual(["09:00", null, null]);
    expect(at("14:30")).toEqual(["14:30", null, null]);
    expect(at("noon")).toEqual(["12:00", null, null]);
    expect(at("midnight")).toEqual(["00:00", null, null]);
    expect(at("12 noon")).toEqual(["12:00", null, null]);
    expect(at("12am")).toEqual(["00:00", null, null]);
    expect(at("@ 4")).toEqual(["16:00", null, null]);
  });

  it("reads a bare hour as the next sensible one", () => {
    expect(at("at 1")).toEqual(["13:00", null, null]);
    expect(at("at 4")).toEqual(["16:00", null, null]);
    expect(at("at 7")).toEqual(["19:00", null, null]);
    expect(at("at 8")).toEqual(["08:00", null, null]);
    expect(at("at 11")).toEqual(["11:00", null, null]);
    expect(at("at 12")).toEqual(["12:00", null, null]);
    expect(at("at 4:30")).toEqual(["16:30", null, null]);
    expect(at("at 4am")).toEqual(["04:00", null, null]);
    expect(at("at 07:30")).toEqual(["07:30", null, null]); // written as a 24-hour time
  });

  it("reads ranges", () => {
    expect(at("4-5pm")).toEqual(["16:00", "17:00", 60]);
    expect(at("2-3:30pm")).toEqual(["14:00", "15:30", 90]);
    expect(at("4pm to 5pm")).toEqual(["16:00", "17:00", 60]);
    expect(at("from 4 to 5pm")).toEqual(["16:00", "17:00", 60]);
    expect(at("9-11am")).toEqual(["09:00", "11:00", 120]);
    expect(at("11-1pm")).toEqual(["11:00", "13:00", 120]);
    expect(at("10-12pm")).toEqual(["10:00", "12:00", 120]);
    expect(at("at 4-5")).toEqual(["16:00", "17:00", 60]);
    expect(at("10am-2")).toEqual(["10:00", "14:00", 240]);
    expect(at("noon-1:30pm")).toEqual(["12:00", "13:30", 90]);
    // Across midnight the end is earlier than the start; the length says how long.
    expect(at("10pm-1am")).toEqual(["22:00", "01:00", 180]);
  });

  it("leaves numbers that aren't times in the title", () => {
    expect(parse("Room 12 cleanup")).toMatchObject({ title: "Room 12 cleanup", allDay: true });
    expect(parse("Party 7-10")).toMatchObject({ title: "Party 7-10", allDay: true });
    expect(parse("Library until 5pm")).toMatchObject({ title: "Library until 5pm", allDay: true });
  });

  it("lets all day overrule a time", () => {
    const text = "Fair Sat all day 9am";
    const draft = parse(text);
    expect(draft).toMatchObject({
      title: "Fair 9am",
      day: "2026-10-10",
      allDay: true,
      start: null,
    });
    expect(understood(text, draft)).toEqual(["day Sat", "allDay all day"]);
  });
});

describe("lengths", () => {
  const length = (text: string) => {
    const { start, end, durationMinutes } = parse(text);
    return [start, end, durationMinutes];
  };

  it("adds a length to the start", () => {
    expect(length("Run 7am for 2h")).toEqual(["07:00", "09:00", 120]);
    expect(length("Run 7am for 2 hours")).toEqual(["07:00", "09:00", 120]);
    expect(length("Run 7am for 1.5 hours")).toEqual(["07:00", "08:30", 90]);
    expect(length("Run 7am for 90 minutes")).toEqual(["07:00", "08:30", 90]);
    expect(length("Run 7am 30 min")).toEqual(["07:00", "07:30", 30]);
    expect(length("Run 7am for 45m")).toEqual(["07:00", "07:45", 45]);
    expect(length("Run 7am for an hour")).toEqual(["07:00", "08:00", 60]);
    expect(length("Run 7am for half an hour")).toEqual(["07:00", "07:30", 30]);
    expect(length("Run 7am for an hour and a half")).toEqual(["07:00", "08:30", 90]);
    expect(length("Run 7am for 1h30")).toEqual(["07:00", "08:30", 90]);
    expect(length("Run 7am for 1 hour 15 min")).toEqual(["07:00", "08:15", 75]);
    expect(length("Movie 11pm for 2 hours")).toEqual(["23:00", "01:00", 120]);
  });

  it("keeps a length with no time for the editor's time picker", () => {
    expect(parse("Nap for 20 min")).toMatchObject({
      title: "Nap",
      allDay: true,
      start: null,
      end: null,
      durationMinutes: 20,
    });
  });

  it("lets a range overrule a length", () => {
    const text = "Soccer 4-5pm for 2h";
    const draft = parse(text);
    expect(draft).toMatchObject({ title: "Soccer for 2h", durationMinutes: 60, end: "17:00" });
    expect(understood(text, draft)).toEqual(["time 4-5pm"]);
  });

  it("doesn't read when as how long", () => {
    expect(parse("Call Mom in 30 min").understood).toEqual([]);
    expect(parse("Leave 2 hours later").understood).toEqual([]);
  });
});

describe("people", () => {
  reads([
    {
      text: "dentist mia",
      draft: { title: "dentist", memberIds: [MIA] },
      words: ["who mia"],
    },
    {
      // In household order, whatever the order they were named in.
      text: "Leo, Mia & Sam swim 4pm",
      draft: { title: "swim", allDay: false, start: "16:00", memberIds: [SAM, MIA, LEO] },
      words: ["who Leo, Mia & Sam", "time 4pm"],
    },
    {
      text: "Soccer Mia Leo Sat",
      draft: { title: "Soccer", day: "2026-10-10", memberIds: [MIA, LEO] },
      words: ["who Mia", "who Leo", "day Sat"],
    },
    {
      // A name inside the title's phrase stays in it.
      text: "Pick up Leo from school 3pm",
      draft: { title: "Pick up Leo from school", allDay: false, start: "15:00", memberIds: [LEO] },
      words: ["who Leo", "time 3pm"],
    },
    {
      text: "Sleepover at Mia’s Fri",
      draft: { title: "Sleepover at Mia’s", day: "2026-10-09", memberIds: [MIA] },
      words: ["who Mia’s", "day Fri"],
    },
    {
      text: "Swim for Mia",
      draft: { title: "Swim", memberIds: [MIA] },
      words: ["who Mia"],
    },
    // A name inside another word is not the name.
    { text: "Samba class", draft: { title: "Samba class" }, words: [] },
    { text: "Leopard Anagram Miasma", draft: { title: "Leopard Anagram Miasma" }, words: [] },
  ]);

  it("tells a month from a member with its name", () => {
    // A synthetic fifth member whose name is also a month.
    const members = [...household.members, { id: "member-may", name: "May" }];
    expect(parse("Dentist May 5", { members })).toMatchObject({
      title: "Dentist",
      day: "2027-05-05",
      memberIds: [],
    });
    expect(parse("Swim with May", { members })).toMatchObject({
      title: "Swim",
      memberIds: ["member-may"],
    });
  });

  it("matches names with spaces and the longest name first", () => {
    const members = [
      { id: "a", name: "Sam" },
      { id: "b", name: "Sam Jr" },
    ];
    expect(parse("Ballet Sam  Jr", { members })).toMatchObject({
      title: "Ballet",
      memberIds: ["b"],
    });
  });

  it("reads a first name for a longer one, folds accents, and skips one letter (ADR 0034)", () => {
    // The server reads imported titles by the same rules (domain/people.py).
    const sofia = { id: "as", name: "Ana Sofia" };
    expect(
      parse("Ana's recital", { members: [sofia, { id: "l", name: "Leo" }] }).memberIds,
    ).toEqual(["as"]);
    expect(
      parse("Ana's recital", { members: [{ id: "a", name: "Ana" }, sofia] }).memberIds,
    ).toEqual(["a"]);
    // A first word two people share is nobody's.
    expect(
      parse("Ana's recital", { members: [sofia, { id: "am", name: "Ana Maria" }] }).memberIds,
    ).toEqual([]);
    expect(parse("Zoe swim", { members: [{ id: "z", name: "Zoë" }] })).toMatchObject({
      title: "swim",
      memberIds: ["z"],
    });
    expect(parse("ZOË swim", { members: [{ id: "z", name: "Zoe" }] }).memberIds).toEqual(["z"]);
    expect(parse("Plan A", { members: [{ id: "a", name: "A" }] }).memberIds).toEqual([]);
  });
});

describe("repeats", () => {
  const repeat = (text: string, ctx: Partial<QuickAddContext> = {}) => {
    const draft = parse(text, ctx);
    return { title: draft.title, day: draft.day, repeat: draft.repeat };
  };

  it("reads each kind of repeat", () => {
    expect(repeat("Vitamins daily").repeat).toEqual({ freq: "daily", interval: 1 });
    expect(repeat("Vitamins every day").repeat).toEqual({ freq: "daily", interval: 1 });
    expect(repeat("Water plants every 3 days").repeat).toEqual({ freq: "daily", interval: 3 });
    expect(repeat("Water plants every other day").repeat).toEqual({ freq: "daily", interval: 2 });
    expect(repeat("Rent monthly").repeat).toEqual({ freq: "monthly", interval: 1, by: "date" });
    expect(repeat("Rent every month").repeat).toEqual({
      freq: "monthly",
      interval: 1,
      by: "date",
    });
    expect(repeat("Haircut every 2 months").repeat).toEqual({
      freq: "monthly",
      interval: 2,
      by: "date",
    });
    expect(repeat("Taxes every year").repeat).toEqual({ freq: "yearly", interval: 1 });
    expect(repeat("Taxes yearly").repeat).toEqual({ freq: "yearly", interval: 1 });
    expect(repeat("Taxes annually").repeat).toEqual({ freq: "yearly", interval: 1 });
  });

  it("puts a weekly repeat on the event's day", () => {
    expect(repeat("Swim weekly")).toEqual({ title: "Swim", day: null, repeat: weekly(1, [2]) });
    expect(repeat("Swim every week", { defaultDay: "2026-10-09" }).repeat).toEqual(weekly(1, [4]));
    expect(repeat("Swim every 2 weeks Thu")).toEqual({
      title: "Swim",
      day: "2026-10-08",
      repeat: weekly(2, [3]),
    });
    expect(repeat("Swim every week on Tue and Thu")).toEqual({
      title: "Swim",
      day: "2026-10-08",
      repeat: weekly(1, [1, 3]),
    });
  });

  it("starts on the next of the weekdays named", () => {
    expect(repeat("Gym every Mon, Tue and Fri")).toEqual({
      title: "Gym",
      day: "2026-10-09",
      repeat: weekly(1, [0, 1, 4]),
    });
    expect(repeat("Gym Tuesdays and Thursdays")).toEqual({
      title: "Gym",
      day: "2026-10-08",
      repeat: weekly(1, [1, 3]),
    });
    expect(repeat("Chess every other Tue")).toEqual({
      title: "Chess",
      day: "2026-10-13",
      repeat: weekly(2, [1]),
    });
    expect(repeat("Hike every weekend")).toEqual({
      title: "Hike",
      day: "2026-10-10",
      repeat: weekly(1, [5, 6]),
    });
    expect(repeat("Pay rent monthly on the 1st")).toEqual({
      title: "Pay rent",
      day: "2026-11-01",
      repeat: { freq: "monthly", interval: 1, by: "date" },
    });
  });

  it("keeps the day tapped on the board when it is one of them", () => {
    const tapped = (defaultDay: string) => repeat("Soccer every Tue", { defaultDay }).day;
    expect(tapped("2026-10-07")).toBe("2026-10-13"); // a Wednesday: the next Tuesday
    expect(tapped("2026-10-20")).toBeNull(); // a Tuesday: the editor keeps it
    expect(tapped("2026-10-06")).toBe("2026-10-13"); // a Tuesday, but in the past
    expect(repeat("Gym every Mon, Wed and Fri").day).toBeNull(); // today is a Wednesday
    expect(repeat("Pay rent monthly on the 1st", { defaultDay: "2026-12-01" }).day).toBeNull();
  });

  it("reads a list of weekdays after every", () => {
    expect(repeat("Soccer every Tue and every Thu")).toEqual({
      title: "Soccer",
      day: "2026-10-08",
      repeat: weekly(1, [1, 3]),
    });
  });

  it("keeps a day that was said over the repeat's", () => {
    expect(repeat("Soccer Oct 20 every Tue")).toEqual({
      title: "Soccer",
      day: "2026-10-20",
      repeat: weekly(1, [1]),
    });
  });

  it("leaves an end date in the title rather than start on it", () => {
    expect(repeat("Soccer every Tue until Dec 31")).toEqual({
      title: "Soccer until Dec 31",
      day: "2026-10-13",
      repeat: weekly(1, [1]),
    });
  });
});

describe("titles", () => {
  const title = (text: string) => parse(text).title;

  it("takes out the words that were understood and what joined them", () => {
    expect(title("Dentist, Thu, 2:30pm, Mia")).toBe("Dentist");
    expect(title("Dentist - Thu 2:30pm")).toBe("Dentist");
    expect(title("Dentist @ 2pm")).toBe("Dentist");
    expect(title("Party Sat!")).toBe("Party");
    expect(title("Soccer with coach Tue 4pm")).toBe("Soccer with coach");
    expect(title("PTA   meeting Thu 7pm")).toBe("PTA meeting");
    expect(title("Thu 2pm")).toBe("");
  });

  it("keeps the whole text when nothing was understood", () => {
    expect(parse("  Movie   night ")).toEqual({ ...BLANK, title: "Movie night", understood: [] });
    expect(parse("")).toEqual({ ...BLANK, understood: [] });
  });

  it("lists the understood spans in the order they were typed", () => {
    const text = "Leo piano Tue at 4 for 30 min every week";
    expect(understood(text, parse(text))).toEqual([
      "who Leo",
      "day Tue",
      "time at 4",
      "length for 30 min",
      "repeat every week",
    ]);
  });
});

describe("time zones", () => {
  const phrases = [
    "Dentist Thu 2:30pm Mia",
    "Soccer practice every Tue 4-5pm Mia",
    "Haircut tomorrow noon",
    "Vet 10/9 at 9",
    "Picnic Oct 6",
    "Book club next Tue 7pm with Ana and Sam",
    "Movie 11pm for 2 hours",
  ];
  const all = (ctx: Partial<QuickAddContext> = {}) => phrases.map((text) => parse(text, ctx));

  it("reads the household's wall time, wherever the household is", () => {
    // 9:41 AM on Wednesday Oct 7 in both places.
    const tokyo = all({ zone: "Asia/Tokyo", now: new Date("2026-10-07T00:41:00Z") });
    const honolulu = all({ zone: "Pacific/Honolulu", now: new Date("2026-10-07T19:41:00Z") });
    expect(tokyo).toEqual(all());
    expect(honolulu).toEqual(all());
  });

  it("takes today from the household's zone", () => {
    const now = new Date("2026-10-08T02:00:00Z"); // 10 PM Wednesday in New York, Thursday in Tokyo
    expect(parse("Dentist tomorrow", { now }).day).toBe("2026-10-08");
    expect(parse("Dentist tomorrow", { now, zone: "Asia/Tokyo" }).day).toBe("2026-10-09");
    expect(parse("Dentist Wed", { now, zone: "Asia/Tokyo" }).day).toBe("2026-10-14");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("doesn't depend on the device's own zone", () => {
    const expected = all();
    for (const zone of ["Pacific/Kiritimati", "Pacific/Pago_Pago", "Europe/London"]) {
      vi.stubEnv("TZ", zone);
      expect(all()).toEqual(expected);
    }
    // The device's zone really did change: Kiritimati is 14 hours ahead of UTC.
    vi.stubEnv("TZ", "Pacific/Kiritimati");
    expect(new Date(2026, 9, 7).getTimezoneOffset()).toBe(-14 * 60);
  });
});

describe("in the page's language (ADR 0043)", () => {
  afterEach(async () => {
    await setLanguage("en", { remember: false });
  });

  it("reads its words from lang/: the language's own lists, English's where it has none", async () => {
    await setLanguage("es", { remember: false });
    // "mañana" and "pasado mañana" are lang/es.json's; "every" is still English's.
    expect(parse("Dentista mañana")).toEqual({
      ...BLANK,
      title: "Dentista",
      day: "2026-10-08",
      understood: [{ kind: "day", start: 9, end: 15 }],
    });
    expect(parse("Dentista pasado mañana").day).toBe("2026-10-09");
    expect(parse("Natación every Tue").repeat).toEqual(weekly(1, [1]));
  });

  it("reads dates and times with chrono's locale for the language", async () => {
    await setLanguage("es", { remember: false });
    expect(parse("Dentista 9 de octubre")).toMatchObject({ title: "Dentista", day: "2026-10-09" });
    expect(parse("Dentista jueves 15:30")).toMatchObject({
      title: "Dentista",
      day: "2026-10-08",
      allDay: false,
      start: "15:30",
    });
    // Spanish writes the day first: 10/9 is the 10th of September, next year's by now.
    expect(parse("Dentista 10/9").day).toBe("2027-09-10");
  });

  it("types English in the pseudo language", async () => {
    const english = parse("Dentist Thu 2:30pm Mia");
    await setLanguage("pseudo", { remember: false });
    expect(parse("Dentist Thu 2:30pm Mia")).toEqual(english);
  });
});

describe("a page that runs for days", () => {
  it("still reads ’ after thousands of lines (V8 14.6 cut it from a pattern, docs/GOTCHAS.md)", () => {
    let wrong: string | null = null;
    for (let n = 0; n < 6000 && wrong === null; n += 1) {
      const { title } = parse("Mia’s recital");
      if (title !== "Mia’s recital") wrong = `line ${String(n)} read "${title}"`;
    }
    expect(wrong).toBeNull();
  });
});
