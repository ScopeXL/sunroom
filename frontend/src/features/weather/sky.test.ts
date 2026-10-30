import { Cloud, CloudMoon, CloudRain, CloudSnow, Moon, Sun } from "lucide-react";
import { describe, expect, it } from "vitest";

import { t } from "../../lib/lang";
import { degrees, highLow, placeWithoutCountry, rainChance, sky } from "./sky";

/** The sky as the family reads it: its icon and its words in English. */
function said(code: number, isDay?: boolean) {
  const { icon, words } = sky(code, isDay);
  return { icon, words: t(words) };
}

describe("the weather's words", () => {
  it("names the sky from its WMO code, by day and by night", () => {
    expect(said(0)).toEqual({ icon: Sun, words: "Sunny" });
    expect(said(0, false)).toEqual({ icon: Moon, words: "Clear" });
    expect(said(2, false)).toEqual({ icon: CloudMoon, words: "Partly cloudy" });
    expect(said(3).words).toBe("Cloudy");
    expect(said(45).words).toBe("Fog");
    expect(said(53).words).toBe("Drizzle");
    expect(said(57).words).toBe("Freezing rain");
    expect(said(63)).toEqual({ icon: CloudRain, words: "Rain" });
    expect(said(81).words).toBe("Showers");
    expect(said(75)).toEqual({ icon: CloudSnow, words: "Snow" });
    expect(said(99).words).toBe("Thunderstorms");
    expect(said(42)).toEqual({ icon: Cloud, words: "Cloudy" });
  });

  it("writes temperatures and rain plainly", () => {
    expect(degrees(63.6)).toBe("64°");
    expect(degrees(-2.4)).toBe("-2°");
    expect(highLow(70, 52)).toBe("High 70°, low 52°");
    expect(rainChance(20)).toBeNull();
    expect(rainChance(60)).toBe("60%");
    expect(rainChance(null)).toBeNull();
  });

  it("names the place without its country, the last of its parts", () => {
    expect(placeWithoutCountry("Sample Town, Sample State, United States")).toBe(
      "Sample Town, Sample State",
    );
    expect(placeWithoutCountry("Sampleton, United Kingdom")).toBe("Sampleton");
    expect(placeWithoutCountry("Sample Town")).toBe("Sample Town");
    expect(placeWithoutCountry("  Sample Town ,  Sample State , United States ")).toBe(
      "Sample Town, Sample State",
    );
    expect(placeWithoutCountry(null)).toBeNull();
    expect(placeWithoutCountry(" , ")).toBeNull();
  });
});
