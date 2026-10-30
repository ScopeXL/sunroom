/**
 * What lists say (UX §2, §4 "Lists room"): counts in each kind's own words ("12 to get", "4 to
 * do", "9 to pack"), a tile's last change ("Mia added Milk · 2:10 PM"), and several items typed
 * at once ("Milk, eggs, bread"). The words are `lists.*` in lang/en.json (ADR 0043).
 */
import { formatTime, monthDay, shortWeekday, zonedParts } from "../../lib/dates";
import { t, type Key } from "../../lib/lang";

export type ListKind = "grocery" | "todo" | "packing" | "custom";

/** How many are left, in each kind's words: "12 to get". */
const LEFT: Record<ListKind, Key> = {
  grocery: "lists.count.left.grocery",
  todo: "lists.count.left.todo",
  packing: "lists.count.left.packing",
  custom: "lists.count.left.custom",
};

/** "12 to get", "4 to do · 1 for today", "All done", "Nothing on it yet". */
export function countLine(kind: ListKind, open: number, done: number, due = 0): string {
  if (open === 0) return done > 0 ? t("lists.count.all_done") : t("lists.count.empty");
  const count = t(LEFT[kind], { n: open });
  return due > 0 ? `${count} · ${t("lists.count.due", { n: due })}` : count;
}

/** When something happened, as the tile says it: "2:10 PM" today, "Mon" this week, else
 * "Oct 2". */
export function whenText(at: string, today: string): string {
  const moment = new Date(at);
  const day = zonedParts(moment).day;
  if (day === today) return formatTime(moment);
  const age = (Date.parse(today) - Date.parse(day)) / 86_400_000;
  return age > 0 && age < 7 ? shortWeekday(day) : monthDay(day);
}

/** "Mia added Milk · 2:10 PM"; nobody named (the wall screen): "Added Milk · 2:10 PM". */
export function lastChangeLine(
  change: { action: "added" | "checked"; text: string; member_id: string | null; at: string },
  nameOf: (id: string) => string | undefined,
  today: string,
): string {
  const who = change.member_id ? nameOf(change.member_id) : undefined;
  const values = { item: change.text, when: whenText(change.at, today) };
  if (change.action === "added") {
    return who ? t("lists.last.added_by", { name: who, ...values }) : t("lists.last.added", values);
  }
  return who
    ? t("lists.last.checked_by", { name: who, ...values })
    : t("lists.last.checked", values);
}

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "Milk, eggs, bread" → ["Milk", "Eggs", "Bread"]: commas make several items (UX §4). */
export function splitItems(typed: string): string[] {
  return typed
    .split(/[,\n]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map(capitalize);
}
