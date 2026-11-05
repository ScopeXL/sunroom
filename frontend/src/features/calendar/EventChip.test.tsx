import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Member } from "../../lib/household";
import { chipTone, occurrenceLabel, PeopleEdge } from "./EventChip";
import type { Occurrence, PersonColor } from "./types";

afterEach(cleanup);

const person = (id: string, color: PersonColor): Member => ({
  id,
  name: id,
  role: "kid",
  color,
  color_word: color,
  birthday: null,
  avatar_url: null,
  archived: false,
});
// The household's order.
const ANA = person("Ana", "sea");
const SAM = person("Sam", "sky");
const MIA = person("Mia", "rose");
const LEO = person("Leo", "moss");
const ZOE = person("Zoe", "copper");

const NOW = "2026-10-07T10:00:00";

function swim(change: Partial<Occurrence> = {}): Occurrence {
  return {
    key: "swim|",
    title: "Mia & Leo's swim",
    all_day: false,
    start_local: "2026-10-08T16:00:00",
    end_local: "2026-10-08T17:00:00",
    member_ids: [],
    color: null,
    ...change,
  } as Occurrence;
}

describe("a chip for several people (ADR 0034)", () => {
  it("draws their colors as its bar, in household order, on a neutral tint", () => {
    const tone = chipTone(swim(), [MIA, LEO], NOW, true);
    expect(tone.edge).toEqual(["rose", "moss"]);
    expect(tone.className).toContain("bg-line/60");
    expect(tone.className).toContain("pl-[18px]");
    expect(tone.className).not.toContain("border-l-[6px]");
    expect(chipTone(swim(), [ANA, SAM, MIA], NOW, true).edge).toEqual(["sea", "sky", "rose"]);
    // Four at most: the rest still have their avatars and names.
    expect(chipTone(swim(), [ANA, SAM, MIA, LEO, ZOE], NOW, true).edge).toEqual([
      "sea",
      "sky",
      "rose",
      "moss",
    ]);
  });

  it("keeps one person's bar, an event's own color, and the look of now and the past", () => {
    expect(chipTone(swim(), [MIA], NOW, true).edge).toBeNull();
    expect(chipTone(swim(), [MIA], NOW, true).className).toContain("border-l-[6px]");
    expect(chipTone(swim({ color: "lime" }), [MIA, LEO], NOW, true).edge).toBeNull();
    expect(chipTone(swim(), [], NOW, true).edge).toBeNull();
    const on = swim({ start_local: "2026-10-07T09:30:00", end_local: "2026-10-07T10:30:00" });
    expect(chipTone(on, [MIA, LEO], NOW, true).edge).toBeNull();
    const past = swim({ start_local: "2026-10-07T08:00:00", end_local: "2026-10-07T09:00:00" });
    expect(chipTone(past, [MIA, LEO], NOW, true).edge).toBeNull();
  });

  it("paints the bar in equal segments of each solid", () => {
    const { container } = render(<PeopleEdge colors={["rose", "moss", "copper"]} />);
    const edge = container.querySelector<HTMLElement>("[data-edge]");
    expect(edge?.className).toContain("edge edge-3");
    expect(edge?.getAttribute("aria-hidden")).toBe("true");
    expect(edge?.style.getPropertyValue("--seg-1")).toBe(
      "light-dark(var(--rose-l), var(--rose-d))",
    );
    expect(edge?.style.getPropertyValue("--seg-3")).toBe(
      "light-dark(var(--copper-l), var(--copper-d))",
    );
  });
});

describe("an event's name says what its chip shows first (UX §10, WCAG 2.5.3)", () => {
  const DAY = "2026-10-08";

  it("starts with the time and the title, then who, until when and the day", () => {
    expect(occurrenceLabel(swim({ title: "Soccer practice" }), [MIA], DAY)).toBe(
      "4:00 PM Soccer practice, Mia, until 5:00 PM, Thursday October 8",
    );
    expect(occurrenceLabel(swim({ title: "Swim" }), [MIA, LEO], DAY)).toBe(
      "4:00 PM Swim, Mia, Leo, until 5:00 PM, Thursday October 8",
    );
  });

  it("says all day first, and Everyone when no one is named", () => {
    const allDay = swim({ title: "Field day", all_day: true, start_local: null, end_local: null });
    expect(occurrenceLabel(allDay, [], DAY)).toBe(
      "all day Field day, Everyone, Thursday October 8",
    );
  });

  it("keeps a row's title, people and place together, as the row shows them", () => {
    const swimAt = swim({ title: "Swim", location: "Sample Street" });
    expect(occurrenceLabel(swimAt, [MIA], DAY, { location: true })).toBe(
      "4:00 PM Swim, Mia, Sample Street, until 5:00 PM, Thursday October 8",
    );
    expect(occurrenceLabel(swimAt, [], DAY, { location: true })).toBe(
      "4:00 PM Swim, Sample Street, Everyone, until 5:00 PM, Thursday October 8",
    );
    // Only a row asks for it: a chip on the wall doesn't show its place.
    expect(occurrenceLabel(swimAt, [MIA], DAY)).toBe(
      "4:00 PM Swim, Mia, until 5:00 PM, Thursday October 8",
    );
  });

  it("takes a row's own first words, and doesn't say until twice", () => {
    expect(occurrenceLabel(swim({ title: "Swim" }), [MIA], DAY, { when: "until 5:00 PM" })).toBe(
      "until 5:00 PM Swim, Mia, Thursday October 8",
    );
  });

  it("leaves out until when an event has no length", () => {
    const moment = swim({ title: "Swim", end_local: "2026-10-08T16:00:00" });
    expect(occurrenceLabel(moment, [MIA], DAY)).toBe("4:00 PM Swim, Mia, Thursday October 8");
  });
});
