import { describe, expect, it } from "vitest";

import { t } from "../../lib/lang";
import { pickTip, TIPS, type Tip } from "./tips";

const EVERY_PLUGIN = new Set([
  "calendar_sync",
  "lists",
  "chores",
  "meals",
  "countdowns",
  "screensaver",
  "weather",
]);

const SAMPLE: readonly Tip[] = [
  { id: "a", text: "tips.drag" },
  { id: "b", text: "tips.usuals", needs: ["lists"] },
  { id: "c", text: "tips.ingredients", needs: ["meals", "lists"] },
];

describe("tips under the board (ADR 0028)", () => {
  it("never shows the same tip twice in a row", () => {
    const first = () => 0;
    expect(pickTip(SAMPLE, new Set(["lists"]), null, first)?.id).toBe("a");
    expect(pickTip(SAMPLE, new Set(["lists"]), "a", first)?.id).toBe("b");
    // Over many picks, each differs from the one before.
    let last: string | null = null;
    for (let index = 0; index < 200; index += 1) {
      const tip = pickTip(TIPS, EVERY_PLUGIN, last);
      expect(tip?.id).not.toBe(last);
      last = tip?.id ?? null;
    }
  });

  it("skips tips about a plugin that's off", () => {
    const picked = new Set<string>();
    for (let step = 0; step < 10; step += 1) {
      picked.add(pickTip(SAMPLE, new Set(["meals"]), null, () => step / 10)?.id ?? "");
    }
    expect([...picked]).toEqual(["a"]);
    expect(
      TIPS.filter((tip) => tip.needs?.length).every(
        (tip) => pickTip([tip], new Set(), null) === null,
      ),
    ).toBe(true);
  });

  it("keeps the only tip that fits, and has none when nothing fits", () => {
    expect(pickTip(SAMPLE, new Set(), "a")?.id).toBe("a");
    expect(pickTip([], EVERY_PLUGIN, null)).toBeNull();
    expect(
      pickTip([{ id: "x", text: "tips.copy_week", needs: ["meals"] }], new Set(), null),
    ).toBeNull();
  });

  it("words every tip as a short plain sentence (UX §2), under its own key", () => {
    expect(new Set(TIPS.map((tip) => tip.id)).size).toBe(TIPS.length);
    for (const tip of TIPS) {
      expect(tip.text, tip.id).toBe(`tips.${tip.id.replaceAll("-", "_")}`);
      const words = t(tip.text);
      expect(words.length, tip.id).toBeLessThanOrEqual(90);
      expect(words, tip.id).toMatch(/^[A-Z"].*[.]$/);
      expect(words, tip.id).not.toMatch(/\p{Extended_Pictographic}/u);
      for (const id of tip.needs ?? []) expect(EVERY_PLUGIN.has(id), `${tip.id}: ${id}`).toBe(true);
    }
  });
});
