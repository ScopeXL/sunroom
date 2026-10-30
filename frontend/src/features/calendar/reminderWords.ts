/**
 * How reminders read (UX §4 "More…", ADR 0034): "10 min before", "1½ hours before", "1 day
 * before", "10 min and 1 hour before"; and the Remind row's choices, so whatever an event holds
 * has a label (R1: one 30 minutes ahead showed a blank button, since the row offered only None,
 * 10 min, 1 hour and 1 day). In the page's language, as they're asked for.
 */
import { t } from "../../lib/lang";
import { lengthWords } from "../../ui/LengthField";

const DAY = 24 * 60;

/** What the Remind row offers, after Default and None. */
export const REMIND_PRESETS = [5, 10, 15, 30, 60, 120, 1440] as const;

/** "1 day", "2 days", else the length's words ("30 min", "1½ hours"). */
function span(minutes: number): string {
  if (minutes > 0 && minutes % DAY === 0) return t("dates.length.days", { n: minutes / DAY });
  return lengthWords(minutes);
}

/** "10 min before"; 0 is "When it starts". */
export function minutesLabel(minutes: number): string {
  return minutes === 0
    ? t("calendar.reminders.at_start")
    : t("calendar.reminders.before", { length: span(minutes) });
}

/** Several in one: "10 min and 1 hour before", "5 min, 1 hour and 1 day before". */
export function remindersLabel(reminders: readonly number[]): string {
  const sorted = [...new Set(reminders)].sort((a, b) => a - b);
  if (sorted.length <= 1) {
    return sorted[0] === undefined ? t("calendar.reminders.none") : minutesLabel(sorted[0]);
  }
  const words = sorted.map((minutes) =>
    minutes === 0 ? t("calendar.reminders.list.start") : span(minutes),
  );
  const last = words.pop() ?? "";
  return t("calendar.reminders.several", { list: words.join(", "), last });
}

/** The Remind row's value for an event's three states (ADR 0034). */
export function reminderValue(
  reminders: readonly number[],
  off: boolean,
  defaultMinutes: number | null,
): string {
  if (reminders.length) return [...new Set(reminders)].sort((a, b) => a - b).join(",");
  // With no Default reminder in the household, "the default" is no reminder at all.
  return off || defaultMinutes === null ? "none" : "default";
}

/** What a value picked on the row stores. */
export function reminderPick(value: string): { reminders: number[]; off: boolean } {
  if (value === "default") return { reminders: [], off: false };
  if (value === "none") return { reminders: [], off: true };
  return { reminders: value.split(",").map(Number), off: false };
}

/**
 * The Remind row's choices: "Default (10 min before)" first when the household has one, then
 * None, then the presets; anything else an event holds (45 minutes, two reminders) is added as
 * one more choice in its own words, so nothing ever shows blank.
 */
export function reminderChoices(
  defaultMinutes: number | null,
  stored: readonly number[],
): { value: string; label: string }[] {
  const choices = [
    ...(defaultMinutes === null
      ? []
      : [
          {
            value: "default",
            label: t("calendar.reminders.default", { reminder: minutesLabel(defaultMinutes) }),
          },
        ]),
    { value: "none", label: t("calendar.reminders.none") },
    ...REMIND_PRESETS.map((minutes) => ({ value: String(minutes), label: minutesLabel(minutes) })),
  ];
  const held = reminderValue(stored, false, defaultMinutes);
  if (stored.length && !choices.some((choice) => choice.value === held)) {
    choices.push({ value: held, label: remindersLabel(stored) });
  }
  return choices;
}
