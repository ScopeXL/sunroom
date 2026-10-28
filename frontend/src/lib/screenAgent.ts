/**
 * Sunroom Screen: the agent beside a wall screen's browser (ADR 0035, docs/M7.md T3).
 *
 * Its launcher opens `/display?dimmer=…&screen=<port>`, and only that document's policy lets
 * the page reach `http://127.0.0.1:<port>` (the server widens its `connect-src`). So the port is
 * read once, when the app starts on /display, and kept in memory only: a page loaded without the
 * parameter has the plain policy, and remembering the port would only produce blocked calls.
 * Nothing calls the agent without it, so a laptop on /display never meets a local-network
 * prompt. A fresh reload (an update, the nightly one) goes back to the launcher's address
 * (`screenReloadUrl`), which brings the policy and the port back; the wall then returns to the
 * room it was in by itself (ADR 0030).
 *
 * The screen's own pages (`src/screen`, served by the agent) use the same client and hooks on
 * their own origin: `noteOwnScreenAgent()` at their start.
 */
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import createClient, { type Client, type Middleware } from "openapi-fetch";
import { useEffect } from "react";

import { qk } from "../api/keys";
import type { components, paths } from "../api/screen-schema";
import { createStore } from "./store";
import { showToast } from "./toast";

export type ScreenState = components["schemas"]["ScreenStateOut"];
export type ScreenCapability = components["schemas"]["ScreenCapability"];
export type ScreenWifi = components["schemas"]["ScreenWifiOut"];
export type ScreenFound = components["schemas"]["ScreenFoundOut"];
export type ScreenAbout = components["schemas"]["ScreenAboutOut"];
export type ScreenScan = components["schemas"]["ScreenScanOut"];
export type ScreenClient = Client<paths>;

const POLL_MS = 30_000;

let port: number | null = null;
let noted = false;
let own = false;
let client: ScreenClient | null = null;

/** Read `?screen=` once, at the app's start: a port from 1024 to 65535, on /display only. */
export function noteScreenAgent(pathname: string, search: string): number | null {
  if (noted) return port;
  noted = true;
  if (pathname !== "/display") return port;
  const asked = new URLSearchParams(search).getAll("screen");
  const value = asked.length === 1 ? asked[0] : undefined;
  if (value === undefined || !/^\d{4,5}$/.test(value)) return port;
  const number = Number(value);
  port = number >= 1024 && number <= 65535 ? number : null;
  return port;
}

export function screenAgentPort(): number | null {
  return port;
}

/** The screen's own pages: the agent that serves them, on their own origin. */
export function noteOwnScreenAgent(): void {
  own = true;
  noted = true;
}

/** Whether this page has an agent to talk to: its own, or the wall's named one. */
export function screenAgentPresent(): boolean {
  return own || port !== null;
}

/** Tests only: as if the app had just started. */
export function forgetScreenAgent(): void {
  port = null;
  noted = false;
  own = false;
  client = null;
}

/** Every change carries `X-Sunroom-Screen: 1`, which the agent asks for (and no form can send). */
const changes: Middleware = {
  onRequest({ request }) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set("X-Sunroom-Screen", "1");
    }
    return request;
  },
};

/** A client for an agent at `baseUrl` (the pages' own origin, for the screen's own pages). */
export function createScreenClient(baseUrl: string): ScreenClient {
  const made = createClient<paths>({ baseUrl });
  made.use(changes);
  return made;
}

function agentBase(): string | null {
  // The pages' own origin, written out: a Request needs an absolute address outside a browser.
  if (own) return window.location.origin;
  return port === null ? null : `http://127.0.0.1:${String(port)}`;
}

/**
 * Leave Sunroom for one of Sunroom Screen's own pages (the wall's Change Address goes to Where Is
 * Your Sunroom?): the agent no longer restarts the browser for an address, so the page that asked
 * moves itself (ADR 0042). Nothing happens without an agent.
 */
export function openScreenPage(path: "/find"): void {
  const base = agentBase();
  if (base !== null) window.location.assign(`${base}${path}`);
}

/** This page's agent: the wall's, when the launcher named one, or the pages' own. */
export function screenClient(): ScreenClient | null {
  const base = agentBase();
  if (base === null) return null;
  client ??= createScreenClient(base);
  return client;
}

/**
 * Right after the wall pairs (or sets Sunroom up): Sunroom Screen has its browser write the
 * pairing to disk now, rather than within 30 s, so a restart straight after keeps it (ADR 0040).
 * Nothing to do without an agent, and nothing to say if it doesn't answer.
 */
export function keepPairing(): void {
  const agent = screenClient();
  if (agent === null) return;
  agent.POST("/api/screen/keep-pairing").catch(() => undefined);
}

/** Where a fresh reload goes on a screen with an agent: the launcher's own address. */
export function screenReloadUrl(dimmer: string): string | null {
  return port === null ? null : `/display?dimmer=${dimmer}&screen=${String(port)}`;
}

/**
 * Sunroom Screen is removing itself (This Screen's Uninstall, ADR 0042): the app shows only its
 * cover from then on, whatever the route does as the screen is unpaired under it, until the
 * browser closes.
 */
export const uninstalling = createStore(false);

/** An update's progress, from the agent's event stream (`update.progress`). */
export const screenProgress = createStore<{ percent: number; step: string } | null>(null);

/** Sunroom starting on this computer (`run.progress`, ADR 0038): a run that stopped says why. */
export const runProgress = createStore<{
  percent: number;
  step: string;
  message?: string | null;
} | null>(null);

/** The agent's state; throws when there is no agent here or it doesn't answer. */
export async function fetchScreenState(): Promise<ScreenState> {
  const agent = screenClient();
  if (!agent) throw new Error("No screen agent here.");
  const { data, error } = await agent.GET("/api/screen");
  if (error !== undefined) throw new Error("The screen didn't answer.");
  return data;
}

/** The agent's state, polled every 30 s (and kept current by `useScreenAgentEvents`); `null`
 * when this page has no agent or it has never answered. Once it has, its last answer stays
 * through a moment without one (the agent restarts itself to finish an update). */
export function useScreenAgent(): ScreenState | null {
  const present = screenAgentPresent();
  const { data, isError } = useQuery({
    queryKey: qk.screen.state(),
    queryFn: fetchScreenState,
    enabled: present,
    refetchInterval: POLL_MS,
    retry: 1,
  });
  if (!present || (isError && data === undefined)) return null;
  return data ?? null;
}

/** Follow the agent's event stream (mounted once, by the display shell). */
export function useScreenAgentEvents(): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    const base = agentBase();
    if (base === null || typeof EventSource === "undefined") return;
    const source = new EventSource(`${base}/api/screen/events`);
    const unlisten = listen(source, queryClient);
    return () => {
      unlisten();
      source.close();
    };
  }, [queryClient]);
}

/** What the stream says, into the query cache, the progress stores and the toasts. */
export function listen(source: EventSource, queryClient: QueryClient): () => void {
  const handlers: Record<string, (data: unknown) => void> = {
    state: (data) => {
      queryClient.setQueryData(qk.screen.state(), data);
    },
    "update.progress": (data) => {
      const progress = data as { percent: number; step: string };
      screenProgress.set(progress.percent >= 100 ? null : progress);
    },
    "run.progress": (data) => {
      runProgress.set(data as { percent: number; step: string; message?: string | null });
    },
    "discovery.started": () => {
      queryClient.setQueryData<ScreenScan>(qk.screen.sunrooms(), { scanning: true, found: [] });
    },
    "discovery.found": (data) => {
      const found = data as ScreenFound;
      queryClient.setQueryData<ScreenScan>(qk.screen.sunrooms(), (scan) => ({
        scanning: true,
        found: [...(scan?.found ?? []).filter((known) => known.url !== found.url), found],
      }));
    },
    "discovery.done": () => {
      queryClient.setQueryData<ScreenScan>(qk.screen.sunrooms(), (scan) => ({
        scanning: false,
        found: scan?.found ?? [],
      }));
    },
    toast: (data) => {
      const message = (data as { message?: unknown }).message;
      if (typeof message === "string" && message) showToast(message);
    },
  };
  const listeners = Object.entries(handlers).map(([name, handle]) => {
    const listener = (event: MessageEvent<string>) => {
      handle(JSON.parse(event.data));
    };
    source.addEventListener(name, listener);
    return [name, listener] as const;
  });
  return () => {
    for (const [name, listener] of listeners) source.removeEventListener(name, listener);
  };
}

/** "The Sample Family's Sunroom", or plain "Sunroom" without a name to go by. */
export function sunroomName(name: string | null | undefined): string {
  const trimmed = name?.trim();
  if (!trimmed || /^(home|our home)$/i.test(trimmed)) return "Sunroom";
  return `${trimmed}${trimmed.endsWith("s") ? "’" : "’s"} Sunroom`;
}
