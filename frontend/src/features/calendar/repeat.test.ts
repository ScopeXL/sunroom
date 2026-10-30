import { afterEach, describe, expect, it } from "vitest";

import { setDatePreferences } from "../../lib/dates";
import {
  customToRepeat,
  describeRepeat,
  isPreset,
  monthDateWords,
  partsToWords,
  repeatWords,
  monthWeekdayWords,
  repeatPresets,
  repeatToCustom,
  repeatToRRule,
  rruleToRepeat,
  sameRepeat,
  weekStartMatters,
  type CustomRepeat,
  type Repeat,
  type RepeatEnd,
  type RepeatParts,
} from "./repeat";

afterEach(() => {
  setDatePreferences({ timezone: "UTC", timeFormat: "12h" });
});

const THURSDAY = "2025-10-09"; // the second Thursday of October 2025

const daily = (interval: number): Repeat => ({ freq: "daily", interval });
const weekly = (interval: number, weekdays: number[]): Repeat => ({
  freq: "weekly",
  interval,
  weekdays,
});
const monthlyOnDate = (interval: number): Repeat => ({ freq: "monthly", interval, by: "date" });
const monthlyOnWeekday = (interval: number): Repeat => ({
  freq: "monthly",
  interval,
  by: "weekday",
});
const yearly = (interval: number): Repeat => ({ freq: "yearly", interval });

describe("presets", () => {
  it("offers the editor's choices for a start day, in order", () => {
    expect(repeatPresets(THURSDAY)).toEqual([
      { key: "none", label: "Doesn't repeat", repeat: null },
      { key: "daily", label: "Every day", repeat: daily(1) },
      { key: "weekdays", label: "Every weekday", repeat: weekly(1, [0, 1, 2, 3, 4]) },
      { key: "weekly", label: "Every week on Thu", repeat: weekly(1, [3]) },
      { key: "biweekly", label: "Every 2 weeks on Thu", repeat: weekly(2, [3]) },
      { key: "monthly-date", label: "Every month on the 9th", repeat: monthlyOnDate(1) },
      {
        key: "monthly-weekday",
        label: "Every month on the second Thursday",
        repeat: monthlyOnWeekday(1),
      },
      { key: "yearly", label: "Every year on Oct 9", repeat: yearly(1) },
    ]);
  });

  it.each([
    // A fifth weekday is always the month's last.
    ["2026-10-29", "Every week on Thu", "Every month on the 29th", "the last Thursday", "Oct 29"],
    // A fourth that is also the last is the last.
    ["2026-11-26", "Every week on Thu", "Every month on the 26th", "the last Thursday", "Nov 26"],
    ["2026-10-22", "Every week on Thu", "Every month on the 22nd", "the fourth Thursday", "Oct 22"],
    ["2026-10-01", "Every week on Thu", "Every month on the 1st", "the first Thursday", "Oct 1"],
    ["2026-10-03", "Every week on Sat", "Every month on the 3rd", "the first Saturday", "Oct 3"],
    ["2026-10-11", "Every week on Sun", "Every month on the 11th", "the second Sunday", "Oct 11"],
    ["2026-10-13", "Every week on Tue", "Every month on the 13th", "the second Tuesday", "Oct 13"],
    ["2026-10-31", "Every week on Sat", "Every month on the 31st", "the last Saturday", "Oct 31"],
  ])("names the presets for %s", (day, week, date, weekday, yearDay) => {
    const labels = repeatPresets(day).map((preset) => preset.label);
    expect(labels).toEqual([
      "Doesn't repeat",
      "Every day",
      "Every weekday",
      week,
      week.replace("Every week", "Every 2 weeks"),
      date,
      `Every month on ${weekday}`,
      `Every year on ${yearDay}`,
    ]);
  });
});

describe("rules", () => {
  const day = "2026-10-08"; // the second Thursday of October 2026

  it("writes the RRULE values the server stores", () => {
    expect(repeatToRRule(daily(1), day)).toBe("FREQ=DAILY");
    expect(repeatToRRule(daily(3), day)).toBe("FREQ=DAILY;INTERVAL=3");
    expect(repeatToRRule(weekly(1, [3]), day)).toBe("FREQ=WEEKLY;BYDAY=TH");
    expect(repeatToRRule(weekly(2, [3]), day)).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH");
    expect(repeatToRRule(weekly(1, [0, 1, 2, 3, 4]), day)).toBe("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR");
    expect(repeatToRRule(weekly(1, [3, 1, 3]), day)).toBe("FREQ=WEEKLY;BYDAY=TU,TH");
    expect(repeatToRRule(weekly(1, []), day)).toBe("FREQ=WEEKLY;BYDAY=TH");
    expect(repeatToRRule(monthlyOnDate(1), day)).toBe("FREQ=MONTHLY");
    expect(repeatToRRule(monthlyOnWeekday(2), day)).toBe("FREQ=MONTHLY;INTERVAL=2;BYDAY=2TH");
    expect(repeatToRRule(monthlyOnWeekday(1), "2026-10-29")).toBe("FREQ=MONTHLY;BYDAY=-1TH");
    expect(repeatToRRule(yearly(1), day)).toBe("FREQ=YEARLY");
  });

  it("ends on a date or after a number of times", () => {
    const rule = (end: RepeatEnd) => repeatToRRule(weekly(2, [3]), day, end);
    expect(rule({ until: "2026-12-31" })).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20261231");
    expect(rule({ count: 10 })).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;COUNT=10");
    expect(rule({ until: "2026-12-31", count: 10 })).toBe(
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20261231",
    );
    expect(rule({ count: 5000 })).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;COUNT=1000");
    expect(rule({})).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH");
  });

  it.each(["2025-10-09", "2026-10-29", "2026-11-26", "2026-10-31", "2026-10-11", "2028-02-29"])(
    "reads back every rule it writes for %s",
    (start) => {
      const repeats = [
        ...repeatPresets(start).flatMap((preset) => (preset.repeat ? [preset.repeat] : [])),
        daily(3),
        weekly(3, [0, 2, 4]),
        weekly(2, [5, 6]),
        monthlyOnDate(6),
        monthlyOnWeekday(2),
        yearly(2),
      ];
      const ends: RepeatEnd[] = [{}, { until: "2029-03-31" }, { count: 12 }];
      for (const repeat of repeats) {
        for (const end of ends) {
          expect(rruleToRepeat(repeatToRRule(repeat, start, end), start)).toEqual({ repeat, end });
        }
      }
    },
  );

  it("reads the same rules as other calendars write them", () => {
    const read = (rule: string) => rruleToRepeat(rule, day)?.repeat ?? null;
    expect(read("RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=TH")).toEqual(weekly(1, [3]));
    expect(read("FREQ=WEEKLY;WKST=SU;BYDAY=TU,TH")).toEqual(weekly(1, [1, 3]));
    expect(read("FREQ=WEEKLY")).toEqual(weekly(1, [3]));
    expect(read("freq=daily;interval=2")).toEqual(daily(2));
    expect(read("FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR")).toEqual(weekly(1, [0, 1, 2, 3, 4]));
    expect(read("FREQ=MONTHLY;BYMONTHDAY=8")).toEqual(monthlyOnDate(1));
    expect(read("FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2")).toEqual(monthlyOnWeekday(1));
    expect(read("FREQ=MONTHLY;BYDAY=+2TH")).toEqual(monthlyOnWeekday(1));
    expect(read("FREQ=YEARLY;BYMONTH=10;BYMONTHDAY=8")).toEqual(yearly(1));
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=SA;WKST=SU")).toEqual(weekly(2, [5]));
    expect(rruleToRepeat("FREQ=MONTHLY;BYDAY=-1TH", "2026-11-26")?.repeat).toEqual(
      monthlyOnWeekday(1),
    );
  });

  it.each([
    "FREQ=MONTHLY;BYMONTHDAY=9", // another date than the start day's
    "FREQ=MONTHLY;BYMONTHDAY=-1",
    "FREQ=MONTHLY;BYDAY=2TU", // another weekday
    "FREQ=MONTHLY;BYDAY=TH", // every Thursday of the month
    "FREQ=MONTHLY;BYDAY=2TH;BYSETPOS=1",
    "FREQ=YEARLY;BYMONTH=11",
    "FREQ=DAILY;INTERVAL=2;BYDAY=MO",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU;WKST=SU", // the week's first day matters here
    "FREQ=WEEKLY;BYDAY=1MO",
    "FREQ=WEEKLY;BYHOUR=9",
    "FREQ=HOURLY",
    "FREQ=WEEKLY;INTERVAL=0",
    "FREQ=WEEKLY;COUNT=5;UNTIL=20261231",
    "FREQ=WEEKLY;COUNT=0",
    "FREQ=WEEKLY;COUNT=1001",
    "FREQ=WEEKLY;UNTIL=20261331",
    "FREQ=WEEKLY;FREQ=DAILY",
    "INTERVAL=2",
    "nonsense",
    "",
  ])("calls %s custom", (rule) => {
    expect(rruleToRepeat(rule, day)).toBeNull();
  });

  it("says when the fourth Thursday is also the last", () => {
    // The editor writes "the last Thursday" for Nov 26, so "4TH" is a different rule.
    expect(rruleToRepeat("FREQ=MONTHLY;BYDAY=4TH", "2026-11-26")).toBeNull();
    expect(rruleToRepeat("FREQ=MONTHLY;BYDAY=4TH", "2026-10-22")?.repeat).toEqual(
      monthlyOnWeekday(1),
    );
  });

  it("reads an end time as the household's day", () => {
    setDatePreferences({ timezone: "America/New_York", timeFormat: "12h" });
    const until = (value: string) => rruleToRepeat(`FREQ=WEEKLY;UNTIL=${value}`, day)?.end;
    expect(until("20261231")).toEqual({ until: "2026-12-31" });
    expect(until("20270101T045959Z")).toEqual({ until: "2026-12-31" }); // 11:59 PM in New York
    expect(until("20261231T235959Z")).toEqual({ until: "2026-12-31" });
    expect(until("20261231T120000")).toEqual({ until: "2026-12-31" });
    expect(rruleToRepeat("FREQ=WEEKLY;COUNT=10", day)?.end).toEqual({ count: 10 });
  });
});

describe("descriptions", () => {
  it("names any repeat the way the presets do", () => {
    expect(describeRepeat(daily(1), THURSDAY)).toBe("Every day");
    expect(describeRepeat(daily(3), THURSDAY)).toBe("Every 3 days");
    expect(describeRepeat(weekly(1, [1, 3]), THURSDAY)).toBe("Every week on Tue and Thu");
    expect(describeRepeat(weekly(1, [4, 0, 2]), THURSDAY)).toBe("Every week on Mon, Wed and Fri");
    expect(describeRepeat(weekly(1, [0, 1, 2, 3, 4]), THURSDAY)).toBe("Every weekday");
    expect(describeRepeat(weekly(2, [0, 1, 2, 3, 4]), THURSDAY)).toBe(
      "Every 2 weeks on Mon, Tue, Wed, Thu and Fri",
    );
    expect(describeRepeat(weekly(1, [5, 6]), THURSDAY)).toBe("Every week on Sat and Sun");
    expect(describeRepeat(monthlyOnDate(2), THURSDAY)).toBe("Every 2 months on the 9th");
    expect(describeRepeat(monthlyOnWeekday(3), THURSDAY)).toBe(
      "Every 3 months on the second Thursday",
    );
    expect(describeRepeat(yearly(3), THURSDAY)).toBe("Every 3 years on Oct 9");
  });

  it("adds when it ends", () => {
    const biweekly = weekly(2, [3]);
    expect(describeRepeat(biweekly, THURSDAY, { until: "2025-12-31" })).toBe(
      "Every 2 weeks on Thu, until Dec 31",
    );
    expect(describeRepeat(biweekly, THURSDAY, { until: "2026-01-15" })).toBe(
      "Every 2 weeks on Thu, until Jan 15, 2026",
    );
    expect(describeRepeat(biweekly, THURSDAY, { count: 10 })).toBe(
      "Every 2 weeks on Thu, 10 times",
    );
    expect(describeRepeat(biweekly, THURSDAY, { count: 1 })).toBe("Every 2 weeks on Thu, once");
    expect(describeRepeat(biweekly, THURSDAY, {})).toBe("Every 2 weeks on Thu");
  });
});

describe("comparing", () => {
  it("compares weekdays as sets", () => {
    expect(sameRepeat(weekly(1, [3, 1]), weekly(1, [1, 3]))).toBe(true);
    expect(sameRepeat(weekly(1, [1]), weekly(2, [1]))).toBe(false);
    expect(sameRepeat(monthlyOnDate(1), monthlyOnWeekday(1))).toBe(false);
    expect(sameRepeat(daily(1), weekly(1, [0, 1, 2, 3, 4, 5, 6]))).toBe(false);
    expect(sameRepeat(null, null)).toBe(true);
    expect(sameRepeat(null, daily(1))).toBe(false);
  });
});

describe("the Custom form (ADR 0029)", () => {
  const FREQS = ["daily", "weekly", "monthly", "yearly"] as const;
  const SETS = [[3], [1, 3], [0, 2, 4], [5, 6], [0, 1, 2, 3, 4, 5, 6]];
  const ENDS: RepeatEnd[] = [{}, { until: "2026-03-31" }, { count: 12 }];

  it("round-trips every shape it can make, through the rule and back", () => {
    let checked = 0;
    for (const freq of FREQS) {
      for (const interval of [1, 2, 3]) {
        for (const weekdays of freq === "weekly" ? SETS : [[3]]) {
          for (const monthlyBy of freq === "monthly"
            ? (["date", "weekday"] as const)
            : (["date"] as const)) {
            for (const end of ENDS) {
              for (const weekStartsOn of [0, 6]) {
                const custom: CustomRepeat = { freq, interval, weekdays, monthlyBy };
                const repeat = customToRepeat(custom, THURSDAY);
                const rule = repeatToRRule(repeat, THURSDAY, end, weekStartsOn);
                const back = rruleToRepeat(rule, THURSDAY, weekStartsOn);
                expect(back, rule).toEqual({ repeat, end });
                expect(repeatToCustom(back?.repeat ?? null, THURSDAY)).toEqual(custom);
                checked += 1;
              }
            }
          }
        }
      }
    }
    expect(checked).toBe(162);
  });

  it("starts as every week on the start day, and keeps at least one weekday", () => {
    expect(repeatToCustom(null, THURSDAY)).toEqual({
      freq: "weekly",
      interval: 1,
      weekdays: [3],
      monthlyBy: "date",
    });
    const none: CustomRepeat = { freq: "weekly", interval: 2, weekdays: [], monthlyBy: "date" };
    expect(customToRepeat(none, THURSDAY)).toEqual(weekly(2, [3]));
    expect(customToRepeat({ ...none, interval: 0 }, THURSDAY)).toEqual(weekly(1, [3]));
  });

  it("knows which repeats a preset chip already says", () => {
    expect(isPreset(null, THURSDAY)).toBe(true);
    expect(isPreset(weekly(1, [3]), THURSDAY)).toBe(true);
    expect(isPreset(weekly(2, [3]), THURSDAY)).toBe(true);
    expect(isPreset(weekly(1, [4, 3, 2, 1, 0]), THURSDAY)).toBe(true); // Every weekday
    expect(isPreset(weekly(2, [1, 3]), THURSDAY)).toBe(false);
    expect(isPreset(weekly(1, [2]), THURSDAY)).toBe(false); // another day than the start's
    expect(isPreset(daily(3), THURSDAY)).toBe(false);
    expect(isPreset(yearly(1), THURSDAY)).toBe(true);
  });

  it("words the month choices from the start day", () => {
    expect(monthDateWords(THURSDAY)).toBe("the 9th");
    expect(monthWeekdayWords(THURSDAY)).toBe("the second Thursday");
    expect(monthWeekdayWords("2026-11-26")).toBe("the last Thursday");
    expect(monthDateWords("2026-10-22")).toBe("the 22nd");
  });
});

describe("the week's first day (WKST)", () => {
  it("matters only every few weeks, on days either side of it", () => {
    expect(weekStartMatters(2, [0, 6], 6)).toBe(true); // Mon and Sun, Sunday first
    expect(weekStartMatters(2, [5, 6], 6)).toBe(true); // Sat and Sun
    expect(weekStartMatters(2, [1, 3], 6)).toBe(false); // Tue and Thu: the same week either way
    expect(weekStartMatters(2, [6], 6)).toBe(false); // one day
    expect(weekStartMatters(1, [0, 6], 6)).toBe(false); // every week
    expect(weekStartMatters(2, [0, 6], 0)).toBe(false); // Monday first is the rule's default
    expect(weekStartMatters(3, [4, 5], 5)).toBe(true); // Saturday first: Fri and Sat
  });

  it("is written only then, and read back under the same rule", () => {
    expect(repeatToRRule(weekly(2, [0, 6]), THURSDAY, undefined, 6)).toBe(
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=SU",
    );
    expect(repeatToRRule(weekly(2, [1, 3]), THURSDAY, undefined, 6)).toBe(
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH",
    );
    expect(repeatToRRule(weekly(2, [0, 6]), THURSDAY, { count: 4 }, 6)).toBe(
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=SU;COUNT=4",
    );
    const read = (rule: string, weekStartsOn: number) =>
      rruleToRepeat(rule, THURSDAY, weekStartsOn)?.repeat ?? null;
    // A Sunday-first household reads its own rule, and one whose days don't depend on it.
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=SU", 6)).toEqual(weekly(2, [0, 6]));
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH", 6)).toEqual(weekly(2, [1, 3]));
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH;WKST=SU", 0)).toEqual(weekly(2, [1, 3]));
    // But not a rule that means other days under its own first day: that one is kept as it is.
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU", 6)).toBeNull();
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=SU", 0)).toBeNull();
    expect(read("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,SU;WKST=XX", 6)).toBeNull();
  });

  it("lists the days in the household's order", () => {
    expect(describeRepeat(weekly(2, [0, 6]), THURSDAY, undefined, 6)).toBe(
      "Every 2 weeks on Sun and Mon",
    );
    expect(describeRepeat(weekly(2, [0, 6]), THURSDAY)).toBe("Every 2 weeks on Mon and Sun");
    expect(describeRepeat(weekly(1, [0, 1, 2, 3, 4]), THURSDAY, undefined, 6)).toBe(
      "Every weekday",
    );
    expect(describeRepeat(weekly(1, [1, 3, 5]), THURSDAY, { count: 6 }, 6)).toBe(
      "Every week on Tue, Thu and Sat, 6 times",
    );
  });
});

describe("a repeat the server sent in parts (ADR 0043)", () => {
  const NONE: RepeatParts = {
    freq: null,
    interval: 1,
    weekdays: [],
    month_days: [],
    last_day: false,
    nth: null,
    weekday: null,
    month: null,
    until: null,
    count: null,
  };
  const FIRST = "2026-10-08";

  // The server's own sentences for the same parts (tests/domain/test_recurrence.py).
  it.each<[Partial<RepeatParts>, string]>([
    [{ freq: "daily", interval: 3 }, "Every 3 days"],
    [{ freq: "weekly", weekdays: [0, 1, 2, 3, 4] }, "Every weekday"],
    [{ freq: "weekly", weekdays: [0, 1, 2, 3, 4, 5, 6] }, "Every day"],
    [{ freq: "weekly", weekdays: [3] }, "Every week on Thu"],
    [{ freq: "weekly", weekdays: [6, 0] }, "Every week on Sun and Mon"],
    [{ freq: "weekly", interval: 2, weekdays: [0, 2, 4] }, "Every 2 weeks on Mon, Wed and Fri"],
    [{ freq: "monthly", month_days: [9] }, "Every month on the 9th"],
    [{ freq: "monthly", month_days: [1, 15] }, "Every month on the 1st and 15th"],
    [{ freq: "monthly", last_day: true }, "Every month on the last day"],
    [{ freq: "monthly", nth: 2, weekday: 1 }, "Every month on the second Tuesday"],
    [{ freq: "monthly", nth: 5, weekday: 2 }, "Every month on the fifth Wednesday"],
    [{ freq: "monthly", nth: -1, weekday: 4 }, "Every month on the last Friday"],
    [{ freq: "monthly", interval: 3, month_days: [1] }, "Every 3 months on the 1st"],
    [{ freq: "yearly", month: 10, month_days: [9] }, "Every year on Oct 9"],
    [{ freq: "yearly", interval: 2, month: 10, month_days: [9] }, "Every 2 years on Oct 9"],
    [{ freq: "yearly", month: 5, nth: 2, weekday: 6 }, "Every year on the second Sunday of May"],
    [{ freq: "yearly", month: 9, nth: 1, weekday: 0 }, "Every year on the first Monday of Sep"],
    [{ freq: "weekly", weekdays: [1], count: 10 }, "Every week on Tue, 10 times"],
    [{ freq: "daily", count: 1 }, "Every day, once"],
    [{ freq: "daily", until: "2026-12-31" }, "Every day, until Dec 31"],
    [{ freq: "daily", until: "2027-01-15" }, "Every day, until Jan 15, 2027"],
    [{ count: 6 }, "Repeats on a custom schedule, 6 times"],
  ])("%j says the server's sentence", (shape, sentence) => {
    expect(partsToWords({ ...NONE, ...shape }, "The server's English", FIRST)).toBe(sentence);
  });

  it("says the server's English when there are no parts, and nothing for no repeat", () => {
    expect(partsToWords(null, "Every week on Thu", FIRST)).toBe("Every week on Thu");
    expect(partsToWords(undefined, null, FIRST)).toBeNull();
  });

  it("counts an event's end from its first day", () => {
    const parts = { ...NONE, freq: "daily" as const, until: "2027-01-15" };
    expect(repeatWords({ repeat: parts, start: "2027-01-02T09:00:00" })).toBe(
      "Every day, until Jan 15",
    );
    expect(repeatWords({ repeat: parts, start_date: "2026-12-30" })).toBe(
      "Every day, until Jan 15, 2027",
    );
  });
});
