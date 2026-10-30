/**
 * Tips under the board (UX §3, ADR 0028, on by default since ADR 0034): one thing Sunroom can
 * do, in the family's words.
 *
 * To add or change one, edit `TIPS` below: an `id` nobody else uses, the `text`, which is the key
 * `tips.<id>` (dashes as underscores) with its English in `lang/en.json` (at most 90 characters,
 * a capital letter or a quote first, a period last, no emoji; `tips.test.ts` checks), and
 * `needs` naming the plugins it's about, so it shows only while they're on. `pickTip` draws one
 * at random, never the same twice in a row.
 */
import type { Key } from "../../lib/lang";

export interface Tip {
  id: string;
  /** Its words' key, said in the page's language where it's shown (ADR 0043). */
  text: Key;
  /** The plugins it's about: it shows only while every one of them is on. */
  needs?: readonly string[];
}

export const TIPS: readonly Tip[] = [
  { id: "quick-add", text: "tips.quick_add" },
  { id: "drag", text: "tips.drag" },
  { id: "tap-a-day", text: "tips.tap_a_day" },
  { id: "weeks", text: "tips.weeks" },
  { id: "show", text: "tips.show" },
  { id: "who", text: "tips.who" },
  { id: "hours", text: "tips.hours" },
  { id: "rolling", text: "tips.rolling" },
  { id: "undo", text: "tips.undo" },
  { id: "recently-removed", text: "tips.recently_removed" },
  { id: "lock", text: "tips.lock" },
  { id: "text-size", text: "tips.text_size" },
  { id: "today-panel", text: "tips.today_panel" },
  { id: "usuals", text: "tips.usuals", needs: ["lists"] },
  { id: "item-sheet", text: "tips.item_sheet", needs: ["lists"] },
  { id: "list-hold", text: "tips.list_hold", needs: ["lists"] },
  { id: "chores", text: "tips.chores", needs: ["chores"] },
  { id: "all-tasks", text: "tips.all_tasks", needs: ["chores"] },
  { id: "task-sheet", text: "tips.task_sheet", needs: ["chores"] },
  { id: "routines", text: "tips.routines", needs: ["chores"] },
  { id: "copy-week", text: "tips.copy_week", needs: ["meals"] },
  { id: "ingredients", text: "tips.ingredients", needs: ["meals", "lists"] },
  { id: "countdown", text: "tips.countdown", needs: ["countdowns"] },
  { id: "photos", text: "tips.photos", needs: ["screensaver"] },
  { id: "screensaver", text: "tips.screensaver", needs: ["screensaver"] },
  { id: "photo-libraries", text: "tips.photo_libraries", needs: ["screensaver"] },
  { id: "weather", text: "tips.weather", needs: ["weather"] },
  { id: "dim", text: "tips.dim" },
  { id: "backup", text: "tips.backup" },
  { id: "install", text: "tips.install" },
  { id: "devices-do-more", text: "tips.devices_do_more" },
  { id: "devices-settings", text: "tips.devices_settings" },
  { id: "accounts", text: "tips.accounts", needs: ["calendar_sync"] },
];

export function tipFits(tip: Tip, enabled: ReadonlySet<string>): boolean {
  return (tip.needs ?? []).every((id) => enabled.has(id));
}

/**
 * The next tip: one whose plugins are on, never the one just shown (unless it's the only one
 * that fits), or null when none fits.
 */
export function pickTip(
  tips: readonly Tip[],
  enabled: ReadonlySet<string>,
  lastId: string | null,
  random: () => number = Math.random,
): Tip | null {
  const fits = tips.filter((tip) => tipFits(tip, enabled));
  const fresh = fits.length > 1 ? fits.filter((tip) => tip.id !== lastId) : fits;
  if (fresh.length === 0) return null;
  return fresh[Math.min(fresh.length - 1, Math.floor(random() * fresh.length))] ?? null;
}
