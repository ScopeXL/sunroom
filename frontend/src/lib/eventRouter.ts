/**
 * Turns live-update events into cache updates (PLAN §11.5). Events only invalidate: the
 * server is the truth. Debounced 250 ms with a 1 s ceiling, so a burst refetches once.
 */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { qk } from "../api/keys";
import type { ServerEvent } from "./events";

const DEBOUNCE_MS = 250;
const MAX_WAIT_MS = 1000;

export function createInvalidator(queryClient: QueryClient) {
  const pending = new Map<string, QueryKey>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let firstQueuedAt: number | undefined;

  const flush = () => {
    timer = undefined;
    firstQueuedAt = undefined;
    const keys = [...pending.values()];
    pending.clear();
    for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  };

  return (queryKey: QueryKey) => {
    pending.set(JSON.stringify(queryKey), queryKey);
    const now = Date.now();
    firstQueuedAt ??= now;
    clearTimeout(timer);
    const wait = Math.min(DEBOUNCE_MS, Math.max(0, firstQueuedAt + MAX_WAIT_MS - now));
    timer = setTimeout(flush, wait);
  };
}

/**
 * What each plugin's own queries are keyed under. A change to a plugin's switch or settings
 * refreshes them at once (the screensaver's timing, the Tasks board's stars, which meals are
 * planned), not whenever they next go stale: no setting needs a refresh (ADR 0029).
 */
const PLUGIN_KEYS: Record<string, readonly QueryKey[]> = {
  calendar_sync: [["calendar-sync"]],
  lists: [["lists"]],
  chores: [["chores"]],
  meals: [["meals"]],
  countdowns: [["countdowns"]],
  screensaver: [["screensaver"], ["photos"]],
  weather: [["weather"]],
};

export interface EventHandlers {
  onSignedOut: () => void;
  /** A parent asked every wall screen to do something now (wall screens act; phones ignore). */
  onKioskCommand?: (command: string, event: ServerEvent) => void;
  /** Sunroom is running itself again (a restore, ADR 0034): every page waits and reloads. */
  onRestarting?: (reason: string) => void;
}

export function createEventHandler(queryClient: QueryClient, handlers: EventHandlers) {
  const invalidate = createInvalidator(queryClient);
  return (event: ServerEvent) => {
    switch (event.type) {
      case "hello":
        if (event.mode === "resync") void queryClient.invalidateQueries();
        break;
      case "members.changed":
        invalidate(["members"]);
        invalidate(qk.session());
        // Birthdays count down from people's birthdays.
        invalidate(["countdowns"]);
        invalidate(["occurrences"]);
        break;
      case "settings.changed":
        invalidate(qk.settings());
        invalidate(qk.session());
        invalidate(qk.kioskLayout());
        invalidate(qk.allowlist());
        invalidate(["weather"]);
        invalidate(qk.update());
        // The backup policy (nightly off: an old copy isn't a problem).
        invalidate(qk.problems());
        break;
      case "devices.changed":
        invalidate(qk.devices());
        invalidate(qk.session());
        break;
      case "plugins.changed": {
        invalidate(qk.plugins());
        // A feature turned off, or one that stopped (Needs Attention, ADR 0034).
        invalidate(qk.problems());
        // A plugin's settings may change what it adds to the board (dinner on the calendar).
        invalidate(["occurrences"]);
        const own = typeof event.id === "string" ? PLUGIN_KEYS[event.id] : undefined;
        // A plugin this build doesn't know: everything, rather than guess its keys.
        if (!own) void queryClient.invalidateQueries();
        for (const key of own ?? []) invalidate(key);
        break;
      }
      case "photos.changed":
        invalidate(["photos"]);
        invalidate(["screensaver"]);
        invalidate(qk.problems());
        break;
      case "events.changed":
        invalidate(["occurrences"]);
        invalidate(["event"]);
        invalidate(["event-search"]);
        invalidate(qk.removedEvents());
        break;
      case "calendars.changed":
        invalidate(["calendars"]);
        invalidate(["occurrences"]);
        invalidate(qk.syncAccounts());
        break;
      case "sync.changed":
        invalidate(["calendar-sync"]);
        invalidate(qk.problems());
        break;
      case "update.available":
        invalidate(qk.update());
        invalidate(qk.problems());
        break;
      case "lists.changed":
        invalidate(["lists"]);
        break;
      case "chores.changed":
      case "points.changed":
      case "routines.changed":
        invalidate(["chores"]);
        break;
      case "meals.changed":
        invalidate(["meals"]);
        invalidate(["occurrences"]);
        break;
      case "countdowns.changed":
        invalidate(["countdowns"]);
        invalidate(["occurrences"]);
        break;
      case "screensaver.changed":
        invalidate(["screensaver"]);
        invalidate(qk.problems());
        break;
      case "weather.changed":
        invalidate(["weather"]);
        break;
      case "kiosk.command":
        if (typeof event.command === "string") handlers.onKioskCommand?.(event.command, event);
        break;
      case "session.expired":
        handlers.onSignedOut();
        break;
      case "server.restarting":
        handlers.onRestarting?.(typeof event.reason === "string" ? event.reason : "restart");
        break;
      default:
        break;
    }
  };
}
