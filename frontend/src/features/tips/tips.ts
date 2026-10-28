/**
 * Tips under the board (UX §3, ADR 0028, on by default since ADR 0034): one thing Sunroom can
 * do, in the family's words.
 *
 * To add or change one, edit `TIPS` below: an `id` nobody else uses, the `text` (at most 90
 * characters, a capital letter or a quote first, a period last, no emoji; `tips.test.ts`
 * checks), and `needs` naming the plugins it's about, so it shows only while they're on.
 * `pickTip` draws one at random, never the same twice in a row.
 */

export interface Tip {
  id: string;
  text: string;
  /** The plugins it's about: it shows only while every one of them is on. */
  needs?: readonly string[];
}

export const TIPS: readonly Tip[] = [
  {
    id: "quick-add",
    text: 'Type "Dentist Thu 2:30pm Mia" in Add: Sunroom reads the day, the time and the person.',
  },
  { id: "drag", text: "Hold a chip on the board, then drag it to another day." },
  { id: "tap-a-day", text: "Tap an empty spot on a day to add something there." },
  { id: "weeks", text: "Swipe the week sideways or use the arrows. This Week brings you back." },
  {
    id: "show",
    text: "Filter: pick a person to see only their week. It clears after two minutes.",
  },
  { id: "who", text: "People gives each person their own column." },
  { id: "hours", text: "Hours draws each day from midnight to midnight. Zoom in when it's busy." },
  {
    id: "rolling",
    text: "Rolling Week keeps today in the same column. Pick it from the View menu.",
  },
  { id: "undo", text: "Removed something by mistake? Tap Undo on the message before it goes." },
  {
    id: "recently-removed",
    text: "Removed it last week? Settings → Recently Removed keeps it for 7 days.",
  },
  { id: "lock", text: "The lock in the rail opens Settings. A parent PIN keeps children out." },
  { id: "text-size", text: "Text too small from across the room? Settings → Display → Text size." },
  {
    id: "today-panel",
    text: "Hide the Today panel with the button at the top right of the board.",
  },
  {
    id: "usuals",
    text: "Lists: Usuals are the things you add most. One tap puts one back on the list.",
    needs: ["lists"],
  },
  {
    id: "item-sheet",
    text: "Lists: tap an item to change its day or who it's for, or to remove it.",
    needs: ["lists"],
  },
  {
    id: "list-hold",
    text: "Hold a list's tile to rename or remove the list.",
    needs: ["lists"],
  },
  { id: "chores", text: "Tasks: one tap on the box marks it done.", needs: ["chores"] },
  {
    id: "all-tasks",
    text: "Tasks: All Tasks lists every task, even next month's. Tap one to change or remove it.",
    needs: ["chores"],
  },
  {
    id: "task-sheet",
    text: "Tap a task's name to change it, skip it today, or remove it.",
    needs: ["chores"],
  },
  {
    id: "routines",
    text: "Routines walk a child through a morning or bedtime list, one step at a time.",
    needs: ["chores"],
  },
  {
    id: "copy-week",
    text: "Meals: Copy Last Week fills the whole week in one tap.",
    needs: ["meals"],
  },
  {
    id: "ingredients",
    text: "Meals: Add Ingredients to Groceries puts a meal's shopping on your grocery list.",
    needs: ["meals", "lists"],
  },
  {
    id: "countdown",
    text: "Countdowns: open any event and tap Add a Countdown.",
    needs: ["countdowns"],
  },
  {
    id: "photos",
    text: "Photos: add them from any signed-in device, several at once.",
    needs: ["screensaver"],
  },
  {
    id: "screensaver",
    text: "Leave the screen alone and your photos take over. A tap brings the calendar back.",
    needs: ["screensaver"],
  },
  {
    id: "photo-libraries",
    text: "Photos: Settings → Photos & Screensaver shows your Immich photos, by person, album or tag.",
    needs: ["screensaver"],
  },
  { id: "weather", text: "Tap the weather to see the forecast.", needs: ["weather"] },
  {
    id: "dim",
    text: "Settings → Display → Dim in the evening makes the screen gentler before bed.",
  },
  {
    id: "backup",
    text: "On a signed-in device, Settings → Backup → Download saves a copy of it all.",
  },
  {
    id: "install",
    text: "On a phone, add Sunroom to the Home Screen from More → Install the App.",
  },
  {
    id: "devices-do-more",
    text: "Signed-in devices can do more: downloads, adding photos, restores and Google's sign-in.",
  },
  {
    id: "devices-settings",
    text: "Change a setting on any signed-in device and every screen follows at once.",
  },
  {
    id: "accounts",
    text: "A calendar you already use? Settings → Calendars & Accounts → Add an Account.",
    needs: ["calendar_sync"],
  },
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
