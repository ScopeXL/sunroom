import { Clock, RefreshCw, Wifi, WifiOff, type LucideIcon } from "lucide-react";

import { connection } from "../lib/connection";
import { liveStatus, type LiveStatus } from "../lib/events";
import { t, useT, type Key } from "../lib/lang";
import { createStore, useStore } from "../lib/store";
import { showToast } from "../lib/toast";
import { Button } from "./Button";
import { useShell } from "./shell";

/**
 * Is this screen hearing live updates? (UX §8, ADR 0028, 0030.) One icon, five states, told
 * apart by shape, never by color alone: connected, reconnecting, checking every 30 seconds
 * (something between here and the server holds the stream back), offline, and nothing once
 * signed out. About → Connection shows it in every state; a header only while it has something
 * to say.
 */
export type LiveState = "live" | "reconnecting" | "polling" | "offline" | "hidden";

/** How long a state other than connected must last before the icon shows it. */
export const SETTLE_MS = 2_000;

/** The stream's status and whether the server answers, as one state: offline wins. */
export function mergeLive(status: LiveStatus, showOffline: boolean): LiveState {
  if (status === "signed-out") return "hidden";
  if (showOffline || status === "offline") return "offline";
  if (status === "polling") return "polling";
  if (status === "connecting") return "reconnecting";
  return "live";
}

/** The state on screen. Connected (and signed out) show at once; anything else only once it has
 * lasted 2 seconds, because the wall screen reopens its stream on every room switch. */
export const liveState = createStore<LiveState>("live");
let settling: ReturnType<typeof setTimeout> | undefined;

export function followLive(): void {
  const next = mergeLive(liveStatus.get(), connection.get().showOffline);
  clearTimeout(settling);
  settling = undefined;
  if (next === "live" || next === "hidden" || next === liveState.get()) {
    liveState.set(next);
    return;
  }
  settling = setTimeout(() => {
    settling = undefined;
    liveState.set(next);
  }, SETTLE_MS);
}

liveStatus.subscribe(followLive);
connection.subscribe(followLive);
followLive();

export function useLiveState(): LiveState {
  return useStore(liveState);
}

/** Each state's icon, its name for a screen reader, and what a tap says. */
const GLYPHS: Record<
  Exclude<LiveState, "hidden">,
  { Icon: LucideIcon; name: Key; tone: string; says: Key }
> = {
  live: {
    Icon: Wifi,
    name: "ui.live.connected.aria",
    tone: "text-ink-soft",
    says: "ui.live.connected.toast",
  },
  reconnecting: {
    Icon: RefreshCw,
    name: "ui.live.reconnecting.aria",
    tone: "live-turn text-ink-soft",
    says: "ui.live.reconnecting.toast",
  },
  polling: {
    Icon: Clock,
    name: "ui.live.polling.aria",
    tone: "text-ink-soft",
    says: "ui.live.polling.toast",
  },
  offline: {
    Icon: WifiOff,
    name: "ui.live.offline.aria",
    tone: "text-ink",
    says: "ui.live.offline.toast",
  },
};

/** The icon alone, named in words for a screen reader (About → Connection). */
export function LiveStatusIcon() {
  const t = useT();
  const display = useShell() === "display";
  const state = useLiveState();
  if (state === "hidden") return null;
  const glyph = GLYPHS[state];
  const Icon = glyph.Icon;
  return (
    <span role="img" aria-label={t(glyph.name)} data-live={state} className="inline-flex shrink-0">
      <Icon
        aria-hidden="true"
        className={`${glyph.tone} ${display ? "size-8" : "size-6"}`}
        strokeWidth={2.25}
      />
    </span>
  );
}

/** The icon as a button (the wall's header, the phone's Calendar header), drawn only while
 * something is wrong: reconnecting, checking every 30 seconds, or offline. Connected draws
 * nothing and keeps no room for itself (ADR 0030). A tap says the state in words. */
export function LiveStatusButton() {
  const state = useLiveState();
  if (state === "hidden" || state === "live") return null;
  return (
    <Button
      variant="quiet"
      icon
      onClick={() => {
        showToast(t(GLYPHS[state].says));
      }}
    >
      <LiveStatusIcon />
    </Button>
  );
}
