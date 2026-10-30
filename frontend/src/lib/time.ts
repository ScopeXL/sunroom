/**
 * A ticking "now" for clocks and the lit day (UX §3). It changes once a minute, on the minute,
 * so only the clock, the now line and the date re-render; the exact time is serverNow().
 */
import { onClockMoved, serverNow } from "./clock";
import { createStore, useStore } from "./store";

const MINUTE = 60_000;

/** The current minute (ms since the epoch, by the server's clock, rounded down). */
export const minute = createStore<number>(Math.floor(serverNow() / MINUTE) * MINUTE);

let timer: ReturnType<typeof setTimeout> | undefined;

function schedule(): void {
  const now = serverNow();
  minute.set(Math.floor(now / MINUTE) * MINUTE);
  timer = setTimeout(schedule, MINUTE - (now % MINUTE) + 25);
}

/** Start ticking (once, from the shell). The returned function stops it. */
export function startClock(): () => void {
  if (timer === undefined) schedule();
  return () => {
    clearTimeout(timer);
    timer = undefined;
  };
}

/** Re-sync after the server clock offset changes a lot (a Pi that just got its time). */
export function resyncClock(): void {
  if (timer === undefined) {
    minute.set(Math.floor(serverNow() / MINUTE) * MINUTE);
    return;
  }
  clearTimeout(timer);
  schedule();
}

onClockMoved(resyncClock);

/** Bumped when the household's zone or 12- or 24-hour choice changes (lib/household), or the
 * page's language (lib/lang), so every clock, date and time on screen redraws at once instead of
 * at the next minute. */
const preferences = createStore<number>(0);

/** Redraw everything that reads the time now: the household's zone or clock, or the language,
 * changed. */
export function refreshMinute(): void {
  preferences.set((count) => count + 1);
}

export function useMinute(): Date {
  useStore(preferences);
  return new Date(useStore(minute));
}
