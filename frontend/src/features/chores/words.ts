/**
 * What chores say (UX §2, §4 "Chores room"): "by 5:00 PM · ★2 · Mia's turn", "Done by Mia ·
 * 7:42 AM", "2 of 3", "★ 42 · +12 this week · 6 days in a row". Stars are always the star glyph
 * with a number. The words are `tasks.*` in lang/en.json (ADR 0043).
 */
import { addDays, formatTime, formatWallTime, shortDate, shortWeekday } from "../../lib/dates";
import { t } from "../../lib/lang";
import { repeatWords, type RepeatParts } from "../calendar/repeat";

export interface Named {
  id: string;
  name: string;
}

const nameOf = (people: Named[], id: string | null | undefined) =>
  id ? people.find((person) => person.id === id)?.name : undefined;

/** Names in a sentence: "Mia", "Mia and Leo", "Mia, Leo and Sam". */
export function namesText(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return t("tasks.names.and", { rest: names.slice(0, -1).join(", "), last: names.at(-1) ?? "" });
}

/** The toast after a parent gives or takes stars (UX §2): "Gave Mia and Leo 5 stars", "Took
 * 1 star from Mia". The button that sent it says Give Stars or Take Stars by the same sign. */
export function starsToast(points: number, names: readonly string[]): string {
  const values = { n: Math.abs(points), names: namesText(names) };
  return points > 0 ? t("tasks.stars.gave.toast", values) : t("tasks.stars.took.toast", values);
}

/** What Custom… gives or takes (ADR 0034): the stepper's count, below zero to take. */
export function customPoints(direction: "give" | "take", count: number): number {
  return direction === "give" ? count : -count;
}

/** "17:00" → "5:00 PM" (or "17:00" on a 24-hour household). */
export function clockText(hhmm: string): string {
  return formatWallTime(`2000-01-01T${hhmm}:00`);
}

/** The line under a chore's title. */
export function boxLine(
  box: {
    due_time: string | null;
    points: number;
    since: string | null;
    turn_id: string | null;
    owner_id: string | null;
    completion: { status: string } | null;
  },
  people: Named[],
  stars: boolean,
): string {
  const parts: string[] = [];
  if (box.since) parts.push(t("tasks.box.since", { day: shortWeekday(box.since) }));
  if (box.due_time && !box.completion) {
    parts.push(t("tasks.box.by", { time: clockText(box.due_time) }));
  }
  if (stars && box.points > 0) parts.push(`★${String(box.points)}`);
  const turn = nameOf(people, box.turn_id);
  if (turn && !box.completion) parts.push(t("tasks.box.turn", { name: turn }));
  return parts.join(" · ");
}

/** A task's next day (All Tasks, ADR 0036): "Today", "Tomorrow", "Sat, Nov 14"; "Finished" when
 * it has none (a one-off that's done, a rule that has ended: it leaves the next day). */
export function nextWord(nextDue: string | null, today: string): string {
  if (nextDue === null) return t("tasks.next.finished");
  if (nextDue === today) return t("tasks.next.today");
  if (nextDue === addDays(today, 1)) return t("tasks.next.tomorrow");
  return shortDate(nextDue);
}

/** The line under a task in All Tasks and its sheet (ADR 0036): its rule, its next day, when
 * it's due by, its stars and whose it is. "Every week on Sat · Sat, Nov 14 · by 5:00 PM · ★2",
 * "Once · Tomorrow", "Every day · Today · Mia and Leo take turns". */
export function ruleLine(
  chore: {
    rrule: string | null;
    repeat_text: string;
    repeat?: RepeatParts | null;
    start_date?: string;
    next_due: string | null;
    due_time: string | null;
    points: number;
    assignee_mode: string;
    assignee_member_ids: readonly string[];
  },
  people: Named[],
  stars: boolean,
  today: string,
): string {
  const parts = [
    chore.rrule ? (repeatWords(chore) ?? chore.repeat_text) : t("tasks.rule.once"),
    nextWord(chore.next_due, today),
  ];
  if (chore.due_time) parts.push(t("tasks.box.by", { time: clockText(chore.due_time) }));
  if (stars && chore.points > 0) parts.push(`★${String(chore.points)}`);
  const names = chore.assignee_member_ids.flatMap((id) => nameOf(people, id) ?? []);
  if (chore.assignee_mode === "rotate" && names.length)
    parts.push(t("tasks.rule.turns", { names: namesText(names) }));
  else if (chore.assignee_mode === "fixed" && names.length > 1) {
    parts.push(t("tasks.rule.each", { names: namesText(names) }));
  } else if (chore.assignee_mode === "any") parts.push(t("tasks.anyone"));
  return parts.join(" · ");
}

/** A box's spoken name (UX §10): "Feed the dog, Mia, 2 stars, due 5:00 PM"; screen readers
 * add "checkbox, not checked". */
export function boxLabel(
  box: {
    title: string;
    due_time: string | null;
    points: number;
    since: string | null;
    turn_id: string | null;
    owner_id: string | null;
    completion: { member_id: string; completed_at: string; status: string } | null;
  },
  people: Named[],
  stars: boolean,
): string {
  const parts = [box.title];
  const owner = nameOf(people, box.owner_id);
  const turn = nameOf(people, box.turn_id);
  parts.push(owner ?? (turn ? t("tasks.box.turn", { name: turn }) : t("tasks.box.anyone")));
  if (stars && box.points > 0) parts.push(t("tasks.stars.count", { n: box.points }));
  if (box.due_time && !box.completion) {
    parts.push(t("tasks.box.due", { time: clockText(box.due_time) }));
  }
  if (box.since) parts.push(t("tasks.box.since", { day: shortWeekday(box.since) }));
  if (box.completion) parts.push(doneLine(box.completion, people));
  return parts.join(", ");
}

/** "Done by Mia · 7:42 AM", or "Mia says it's done · 7:42 AM" while a parent hasn't checked. */
export function doneLine(
  completion: { member_id: string; completed_at: string; status: string },
  people: Named[],
): string {
  const who = nameOf(people, completion.member_id) ?? t("tasks.done.someone");
  const at = formatTime(new Date(completion.completed_at));
  return completion.status === "pending"
    ? t("tasks.done.pending", { name: who })
    : t("tasks.done.by", { name: who, time: at });
}

/** "2 of 3" (UX §2: never "2/3"). */
export function countText(done: number, total: number): string {
  return t("tasks.progress", { done, total });
}

/** "★ 42 · +12 this week · 6 days in a row"; a broken streak just says 0 (UX §10). */
export function starsLine(stars: { balance: number; week: number; streak: number }): string {
  const parts = [`★ ${String(stars.balance)}`];
  if (stars.week > 0) parts.push(t("tasks.stars.week", { n: stars.week }));
  parts.push(t("tasks.stars.streak", { n: stars.streak }));
  return parts.join(" · ");
}

/** "All done, Mia!", or "All done!" for Anyone's chores. */
export function allDoneText(name: string | null): string {
  return name ? t("tasks.all_done.person", { name }) : t("tasks.all_done.anyone");
}

/** "Leo's bedtime routine" unless its title already says whose it is. */
export function routineTitle(title: string, name: string | undefined): string {
  if (!name || title.toLowerCase().startsWith(name.toLowerCase())) return title;
  const routine = `${title.charAt(0).toLowerCase()}${title.slice(1)}`;
  return t("tasks.routine.for_kid", { name, routine });
}
