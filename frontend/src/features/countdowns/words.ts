/** Countdowns in the family's words (UX §2, §4 "Countdowns room"; lang/en.json, ADR 0043). */
import { t } from "../../lib/lang";

/** The tile's big line: "12 days", then "Tomorrow" and "Today!" on the last days. */
export function daysText(days: number): string {
  return t("countdowns.days", { n: Math.max(0, days) });
}

/** A Coming up line: "Mia's birthday · 12 days"; on the day, "Today: Mia's birthday!". */
export function comingUpText(title: string, days: number): string {
  return t("countdowns.coming_up.line", { title, n: Math.max(0, days) });
}

/** What a kid's birthday brings: "Turns 9". */
export function turningText(turning: number | null | undefined): string | null {
  return turning != null && turning > 0 ? t("countdowns.turning", { n: turning }) : null;
}
