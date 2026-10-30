/**
 * A new Sunroom on the server (ADR 0028): the live stream's hello names the server's version.
 * When it isn't the version this page was built from, the page says so and reloads itself
 * fresh, with no service worker and no cached files in the way, so the new build comes straight
 * from the server. Once per server version, so a proxy still serving the old page can't make it
 * loop; and not while someone is in the middle of something, for 10 minutes at most. The phone's
 * "New version" pill and the wall's 3 AM rule stay for a screen that has no stream.
 */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { rememberedDimmer } from "./dimmer";
import { editorOpen, idleHolds } from "./displayState";
import { t } from "./lang";
import { screenReloadUrl } from "./screenAgent";
import { createStore, useStore } from "./store";
import { showToast } from "./toast";

export const REFRESH_AFTER_MS = 4000;
export const RECHECK_MS = 5000;
export const WAIT_AT_MOST_MS = 10 * 60_000;
const RELOADED_KEY = "sunroom.reloadedFor";

/** The server's version when it isn't this build's; null when they match or it isn't known. */
export const serverVersion = createStore<string | null>(null);

/** Every hello calls this with the version it names (lib/events). */
export function announceServerVersion(version: unknown): void {
  if (typeof version !== "string" || !version) return;
  serverVersion.set(version === __APP_VERSION__ ? null : version);
}

function reloadedFor(): string | null {
  try {
    return sessionStorage.getItem(RELOADED_KEY);
  } catch {
    return null;
  }
}

function rememberReload(version: string): void {
  try {
    sessionStorage.setItem(RELOADED_KEY, version);
  } catch {
    // No session storage: at worst, one more reload.
  }
}

function reloadPage(): void {
  // A wall run by Sunroom Screen goes back to its launcher's address, which brings back the
  // agent's port and the policy that lets the page reach it (lib/screenAgent); the wall then
  // returns to the room it was in by itself (ADR 0030).
  const launcher = screenReloadUrl(rememberedDimmer());
  if (launcher) window.location.replace(launcher);
  else window.location.reload();
}

/**
 * Reload with nothing old in the way: every service worker unregistered and its caches deleted,
 * so the page and its files come from the server. The address (the wall's ?dimmer=…) stays, or
 * on a wall run by Sunroom Screen, its launcher's address.
 */
export async function reloadFresh(reload: () => void = reloadPage): Promise<void> {
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  } catch {
    // No service worker here: the reload asks the server anyway.
  }
  try {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key)));
  } catch {
    // No cache storage (a page that isn't a secure context): nothing to clear.
  }
  reload();
}

/** Someone is in the middle of something: an editor, a routine, a sheet, a save on its way. */
export function busy(queryClient: QueryClient): boolean {
  return (
    editorOpen() ||
    idleHolds.get() > 0 ||
    document.querySelector("dialog:modal") !== null ||
    queryClient.isMutating() > 0
  );
}

/** Both shells mount this: when the server is a new version, say so and refresh. */
export function useServerUpdate(refresh: () => Promise<void> = reloadFresh): void {
  const version = useStore(serverVersion);
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!version || reloadedFor() === version) return;
    showToast(t("app.updated.toast", { version }));
    const started = Date.now();
    const attempt = () => {
      if (busy(queryClient) && Date.now() - started < WAIT_AT_MOST_MS) {
        timer = setTimeout(attempt, RECHECK_MS);
        return;
      }
      rememberReload(version);
      void refresh();
    };
    let timer = setTimeout(attempt, REFRESH_AFTER_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [version, queryClient, refresh]);
}
