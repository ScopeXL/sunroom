/**
 * What the wall screen is showing right now, beyond the URL: the board's view, which week, day
 * or month, the person filter, whether the Today panel is hidden and the rail folded on this
 * screen, the Week layout and zoom chosen on it, and the event sheet or Add panel that's open.
 * After 2 minutes idle the board goes back to now, so the next person who glances sees this
 * week, and what the screen chose for itself stays (UX §1 "Idle, wake and reset", ADR 0031).
 *
 * A screen remembers it (ADR 0030): everything here but the open panel, and the room the screen
 * is in, are kept in this browser, so a refresh, an update or a restart comes back to them,
 * unless Settings → Display → When it starts says the home view. Going back to now is
 * remembered like any other change: a screen that sat idle comes back to this week.
 */
import { lastActivity } from "./idle";
import { createStore } from "./store";

/** The board's views: Rolling Week (yesterday, today and the five days after) is one of its
 * own since ADR 0042; it was a switch on the Week view (ADR 0033, 0036). */
export type BoardView = "week" | "rolling" | "day" | "month" | "people" | "today";
/** How the Week board draws a day (ADR 0028): stacked chips, or the hours from midnight. */
export type WeekLayout = "agenda" | "hours";

export type BoardPanel =
  /** `eventId` null: a birthday's read-only sheet, which has no event behind it. */
  | { kind: "event"; eventId: string | null; recurrenceId: string | null; key: string }
  /** `type`: what Add makes (an event, or a plugin's "item", "chore"); none: the room's. */
  | {
      kind: "add";
      day: string | null;
      hour: number | null;
      /** With `hour`, the minute a tap on the Hours grid chose. */
      minute?: number | null;
      type?: string;
      title?: string;
    }
  | { kind: "edit"; eventId: string; recurrenceId: string | null }
  | null;

export interface DisplayState {
  /** null: the household's home view (Settings → Display). */
  view: BoardView | null;
  weekOffset: number;
  /** The Day view's day; null is today. */
  day: string | null;
  monthOffset: number;
  /** null: as the household set it in Settings → Display. */
  panelShown: boolean | null;
  /** The rail folded to its icons on this screen; null: the household's Compact rail setting. */
  railCollapsed: boolean | null;
  /** null: the household's Week layout (Settings → Display). */
  weekLayout: WeekLayout | null;
  /** How far the Hours grid is zoomed in: 1 fits the whole day, each Zoom in is half again. */
  hoursZoom: number;
  /** Show these people's events (and Everyone's); empty shows all. */
  people: string[];
  panel: BoardPanel;
}

const INITIAL: DisplayState = {
  view: null,
  weekOffset: 0,
  day: null,
  monthOffset: 0,
  panelShown: null,
  railCollapsed: null,
  weekLayout: null,
  hoursZoom: 1,
  people: [],
  panel: null,
};

const MEMORY_KEY = "sunroom.display.view";
const ROOM_KEY = "sunroom.display.room";

type View = Omit<DisplayState, "panel">;

const isView = (value: unknown): value is BoardView | null =>
  value === null ||
  value === "week" ||
  value === "rolling" ||
  value === "day" ||
  value === "month" ||
  value === "people" ||
  value === "today";
const isLayout = (value: unknown): value is WeekLayout | null =>
  value === null || value === "agenda" || value === "hours";
const isChoice = (value: unknown): value is boolean | null =>
  value === null || typeof value === "boolean";
const isOffset = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value);
const isDay = (value: unknown): value is string | null =>
  value === null || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
const isZoom = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 1;
const isIds = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((id) => typeof id === "string");

/**
 * What this browser kept of the view, or null: nothing kept, storage switched off (private
 * browsing just forgets), or a shape this build doesn't know. Every field is checked: it's the
 * first thing the page draws, before the server has said anything.
 */
export function remembered(): View | null {
  try {
    const raw = localStorage.getItem(MEMORY_KEY);
    if (raw === null) return null;
    const kept = JSON.parse(raw) as Record<string, unknown> | null;
    if (typeof kept !== "object" || kept?.v !== 1) return null;
    const {
      view,
      weekOffset,
      day,
      monthOffset,
      panelShown,
      railCollapsed,
      weekLayout,
      hoursZoom,
      people,
    } = kept;
    // 0.14.0 to 0.16.1 kept Rolling week beside the view, a switch on Week; since 0.17.0 it is
    // a view of its own (ADR 0042), so a screen that had it on comes back on it.
    const rolling = kept.rollingWeek === true && view === "week";
    if (
      !isView(view) ||
      !isOffset(weekOffset) ||
      !isDay(day) ||
      !isOffset(monthOffset) ||
      !isChoice(panelShown) ||
      !isChoice(railCollapsed) ||
      !isLayout(weekLayout) ||
      !isZoom(hoursZoom) ||
      !isIds(people)
    ) {
      return null;
    }
    return {
      view: rolling ? "rolling" : view,
      weekOffset,
      day,
      monthOffset,
      panelShown,
      railCollapsed,
      weekLayout,
      hoursZoom,
      people,
    };
  } catch {
    return null;
  }
}

// Settings → Display → When it starts: "The home view" keeps nothing here (setRemembering).
let remembering = true;
let written: string | null = null;

function remember(state: DisplayState): void {
  if (!remembering) return;
  const view: View & { v: 1 } = {
    v: 1,
    view: state.view,
    weekOffset: state.weekOffset,
    day: state.day,
    monthOffset: state.monthOffset,
    panelShown: state.panelShown,
    railCollapsed: state.railCollapsed,
    weekLayout: state.weekLayout,
    hoursZoom: state.hoursZoom,
    people: state.people,
  };
  const next = JSON.stringify(view);
  // Only the panel changed: an open sheet or a draft in Add is never kept (UX §1).
  if (next === written) return;
  written = next;
  try {
    localStorage.setItem(MEMORY_KEY, next);
  } catch {
    // Storage is off: the view lasts until the page reloads.
  }
}

function forget(): void {
  written = null;
  try {
    localStorage.removeItem(MEMORY_KEY);
    localStorage.removeItem(ROOM_KEY);
  } catch {
    // Storage is off: there was nothing to forget.
  }
}

export const displayState = createStore<DisplayState>({ ...INITIAL, ...remembered() });
displayState.subscribe(() => {
  remember(displayState.get());
});

/**
 * Whether this screen keeps its view for its next start (the household's When it starts).
 * Turned off, what was kept is dropped at once, so the next start has nothing to come back to;
 * what's on screen stays. Turned on again, it keeps the view from here.
 */
export function setRemembering(on: boolean): void {
  if (on === remembering) return;
  remembering = on;
  if (on) remember(displayState.get());
  else forget();
}

/** Start on the home view: nothing kept, and nothing chosen on this screen. */
export function forgetView(): void {
  forget();
  displayState.set(INITIAL);
}

// A room's address ("/lists", "/chores/rewards"), never Settings or a page from before sign-in.
const ROOM_PATH = /^\/[a-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/;
const NOT_ROOMS = [
  "settings",
  "display",
  "calendar",
  "more",
  "pair",
  "who",
  "setup",
  "sign-in",
  "join",
  "install",
];

function keptRoom(): string | null {
  try {
    const path = localStorage.getItem(ROOM_KEY);
    if (path === null || !ROOM_PATH.test(path)) return null;
    return NOT_ROOMS.includes(path.split("/")[1] ?? "") ? null : path;
  } catch {
    return null;
  }
}

// Read once, as the page loads: the shell writes the room it is in from its first render on.
const startRoom = keptRoom();

/** The room this screen was in when it last ran, for a page that opened at home (the Pi's
 * launcher always opens /display). Null: it was home, or nothing is kept. */
export function roomAtStart(): string | null {
  return remembering ? startRoom : null;
}

/** Keep the room this screen is in (its address), or null for home. Never Settings. */
export function rememberRoom(path: string | null): void {
  if (!remembering) return;
  try {
    if (path === null) localStorage.removeItem(ROOM_KEY);
    else localStorage.setItem(ROOM_KEY, path);
  } catch {
    // Storage is off: a restart opens at home.
  }
}

export function updateDisplay(change: Partial<DisplayState>): void {
  displayState.set((state) => ({ ...state, ...change }));
}

/** Add or Change is open: what someone was typing outlasts the 2-minute reset (UX §1). */
export function editorOpen(): boolean {
  const panel = displayState.get().panel;
  return panel?.kind === "add" || panel?.kind === "edit";
}

/**
 * Something on the screen that mustn't be cut short by the room's idle return (a kid running a
 * routine, UX §6). Returns the release.
 */
export const idleHolds = createStore<number>(0);

export function holdIdle(): () => void {
  idleHolds.set((n) => n + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    idleHolds.set((n) => Math.max(0, n - 1));
  };
}

/**
 * Whether nobody has touched the screen since the board went back to now. Meanwhile a zoomed
 * Hours grid keeps now in view (ADR 0031). Any touch ends it.
 */
export const resting = createStore<boolean>(false);
lastActivity.subscribe(() => {
  resting.set(false);
});

/**
 * Back to now, after 2 minutes idle (UX §1 "Idle, wake and reset", ADR 0031): this week, today
 * and this month, everyone's events, and nothing open. What the screen chose for itself stays:
 * its view, the Week layout and zoom, the Today panel and the rail. A board already there is left
 * alone, so nothing redraws, and the screen rests either way.
 */
export function backToNow(): void {
  displayState.set((state) =>
    state.weekOffset === 0 &&
    state.day === null &&
    state.monthOffset === 0 &&
    state.people.length === 0 &&
    state.panel === null
      ? state
      : { ...state, weekOffset: 0, day: null, monthOffset: 0, people: [], panel: null },
  );
  resting.set(true);
}

/** The household's choices (Settings → Display) that a screen can also make for itself. */
export interface HouseholdChoices {
  homeView: string;
  weekLayout: WeekLayout;
  todayPanel: boolean;
  compactRail: boolean;
}

// What this page last read of them; null until the settings first arrive.
let household: HouseholdChoices | null = null;

/**
 * The household's choices, each time the settings arrive. When one changes (in Settings, on
 * this screen or a phone), this screen's own choice of the same thing gives way, so the change
 * shows at once: the latest choice wins (ADR 0031). The first ones a page reads are only noted,
 * so what a screen kept from before its start stands.
 */
export function householdChose(next: HouseholdChoices): void {
  const before = household;
  household = next;
  if (!before) return;
  const change: Partial<DisplayState> = {};
  if (next.homeView !== before.homeView) change.view = null;
  if (next.weekLayout !== before.weekLayout) change.weekLayout = null;
  if (next.todayPanel !== before.todayPanel) change.panelShown = null;
  if (next.compactRail !== before.compactRail) change.railCollapsed = null;
  if (Object.keys(change).length) updateDisplay(change);
}
