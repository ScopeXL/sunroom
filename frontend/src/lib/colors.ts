import type { components } from "../api/schema";
import { t, type Key } from "./lang";

export type PersonColor = components["schemas"]["MemberOut"]["color"];

/** The twelve person colors, each with its plain word's key (UX §10, ADR 0043): what a picker
 * shows and a screen reader says. One list for every color picker in the app; the last four came in 0.12.0, after
 * the first eight, so nobody's color moved (ADR 0034). */
export const COLORS: readonly { value: PersonColor; word: Key }[] = [
  { value: "clay", word: "ui.colors.clay" },
  { value: "olive", word: "ui.colors.olive" },
  { value: "moss", word: "ui.colors.moss" },
  { value: "sea", word: "ui.colors.sea" },
  { value: "sky", word: "ui.colors.sky" },
  { value: "iris", word: "ui.colors.iris" },
  { value: "berry", word: "ui.colors.berry" },
  { value: "rose", word: "ui.colors.rose" },
  { value: "copper", word: "ui.colors.copper" },
  { value: "bark", word: "ui.colors.bark" },
  { value: "slate", word: "ui.colors.slate" },
  { value: "lime", word: "ui.colors.lime" },
];

/** "Red" for "clay", in the page's language; the value itself if it's one we don't know. */
export function colorWord(color: string): string {
  const found = COLORS.find((candidate) => candidate.value === color);
  return found ? t(found.word) : color;
}
