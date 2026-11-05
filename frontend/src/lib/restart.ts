/**
 * Sunroom running itself again (ADR 0034: after a restore from Settings → Backup). The live
 * stream says `server.restarting`; every page then says so, waits until the server has gone and
 * come back, and reloads fresh. The restore signed everyone out, so a phone lands on sign-in and
 * a wall screen on its pair code: never a dead end. Until the server is back the page stays as
 * it is, however long that takes.
 */
import { useEffect } from "react";

import { t } from "./lang";
import { showToast } from "./toast";
import { createStore, useStore } from "./store";
import { reloadFresh } from "./update";

/** Why the server is restarting ("restore", "update"), once it said so; null otherwise. */
export const restarting = createStore<string | null>(null);

/** The page that asked for the restart says so itself, in its own sheet: no toast there too. */
let askedHere = false;
/** One wait per page, however often the wall remounts its shell meanwhile. */
let waiting = false;

export function announceRestart(reason: string): void {
  if (restarting.get() === null) restarting.set(reason);
}

/** Set before a restart is asked for on this page (its frame can come before the answer), and
 * cleared again when the server says no. */
export function askingHere(asking: boolean): void {
  askedHere = asking;
}

/** A test's clean slate. */
export function forgetRestart(): void {
  askedHere = false;
  waiting = false;
  restarting.set(null);
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

export interface WaitOptions {
  /** First wait for the server to go away (health not "ok", or no answer), then for it back. */
  afterGoingAway?: boolean;
  /** If it never seems to go within this long, it restarted between two looks: wait for "ok". */
  goneWithinMs?: number;
  everyMs?: number;
  forMs?: number;
  fetcher?: typeof fetch;
  pause?: (ms: number) => Promise<void>;
  now?: () => number;
}

/** Polls `GET /api/health` until the server answers "ok" again. False when `forMs` runs out. */
export async function waitForServer({
  afterGoingAway = false,
  goneWithinMs = 15_000,
  everyMs = 1000,
  forMs = 180_000,
  fetcher = (input, init) => fetch(input, init),
  pause = sleep,
  now = () => Date.now(),
}: WaitOptions = {}): Promise<boolean> {
  const started = now();
  let gone = !afterGoingAway;
  for (;;) {
    let up: boolean;
    try {
      up = (await fetcher("/api/health", { cache: "no-store" })).ok;
    } catch {
      up = false; // the server, or the way to it, isn't there
    }
    if (!gone && (!up || now() - started >= goneWithinMs)) gone = true;
    if (gone && up) return true;
    if (now() - started >= forMs) return false;
    await pause(everyMs);
  }
}

/** An update pulls its image first, so the server may stay a good while before it goes. */
const UPDATE_GOES_WITHIN_MS = 180_000;

/**
 * Both shells mount this: when the server says it is restarting, say so, wait, and reload. An
 * update says so in the quiet pill instead (ui/StatusLayer), and signs no one out.
 */
export function useServerRestart(refresh: () => Promise<void> = reloadFresh): void {
  const reason = useStore(restarting);
  useEffect(() => {
    if (!reason || waiting) return;
    waiting = true;
    const update = reason === "update";
    if (!askedHere && !update) showToast(t("app.restarting.toast"));
    void waitForServer({
      afterGoingAway: true,
      forMs: Number.POSITIVE_INFINITY,
      ...(update ? { goneWithinMs: UPDATE_GOES_WITHIN_MS } : {}),
    }).then(() => refresh());
  }, [reason, refresh]);
}
