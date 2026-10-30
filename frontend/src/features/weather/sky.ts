/**
 * The weather in the family's words (UX §2): Open-Meteo sends WMO weather codes; the wall shows
 * an icon and a word or two, a key in lang/en.json (ADR 0043) said where it's shown. Temperatures
 * are whole degrees in the household's units, written "64°" (Settings → Features → Weather says
 * which).
 */
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudMoon,
  CloudRain,
  CloudSnow,
  CloudSun,
  Moon,
  Sun,
  type LucideIcon,
} from "lucide-react";

import { t, type Key } from "../../lib/lang";

export interface Sky {
  icon: LucideIcon;
  /** The sky's words, a key: `t(sky.words)` says "Partly cloudy". */
  words: Key;
}

export function sky(code: number, isDay = true): Sky {
  if (code === 0) {
    return isDay
      ? { icon: Sun, words: "weather.sky.sunny" }
      : { icon: Moon, words: "weather.sky.clear" };
  }
  if (code === 1)
    return isDay
      ? { icon: CloudSun, words: "weather.sky.mostly_sunny" }
      : { icon: CloudMoon, words: "weather.sky.mostly_clear" };
  if (code === 2) return { icon: isDay ? CloudSun : CloudMoon, words: "weather.sky.partly_cloudy" };
  if (code === 3) return { icon: Cloud, words: "weather.sky.cloudy" };
  if (code === 45 || code === 48) return { icon: CloudFog, words: "weather.sky.fog" };
  if (code === 56 || code === 57 || code === 66 || code === 67)
    return { icon: CloudRain, words: "weather.sky.freezing_rain" };
  if (code >= 51 && code <= 55) return { icon: CloudDrizzle, words: "weather.sky.drizzle" };
  if (code >= 61 && code <= 65) return { icon: CloudRain, words: "weather.sky.rain" };
  if (code >= 80 && code <= 82) return { icon: CloudRain, words: "weather.sky.showers" };
  if ((code >= 71 && code <= 77) || code === 85 || code === 86)
    return { icon: CloudSnow, words: "weather.sky.snow" };
  if (code >= 95) return { icon: CloudLightning, words: "weather.sky.thunderstorms" };
  return { icon: Cloud, words: "weather.sky.cloudy" };
}

export function degrees(value: number): string {
  return `${String(Math.round(value))}°`;
}

/** "High 70°, low 52°" for screen readers and the day's line. */
export function highLow(high: number, low: number): string {
  return t("weather.high_low", { high: degrees(high), low: degrees(low) });
}

/** A chance of rain worth saying: 30% and up ("70%"). */
export function rainChance(percent: number | null | undefined): string | null {
  return percent != null && percent >= 30 ? `${String(percent)}%` : null;
}

/**
 * The household's place without its country, for the forecast's one-line title (ADR 0033):
 * "Sample Town, Sample State" for "Sample Town, Sample State, United States". The label is
 * Sunroom's own: the server joins the town, the region and the country with commas, the country
 * last when Open-Meteo sends one (`place_label`, plugins/weather/open_meteo.py), so the last part
 * is the country. A place sent without a country loses its region instead, a fair price for a
 * short title; a place of one part ("Singapore") stays as it is. Settings → Household still
 * shows the whole label, where the country helps.
 */
export function placeWithoutCountry(label: string | null): string | null {
  const parts = (label ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length > 1) return parts.slice(0, -1).join(", ");
  return parts[0] ?? null;
}
