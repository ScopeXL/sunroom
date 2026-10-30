/**
 * The only way the app talks to the API: a typed openapi-fetch client (Dinner Bell's ADR 0018).
 *
 * * Mutations carry the CSRF header `X-Sunroom: 1` (PLAN §12.5).
 * * Every response feeds the server-clock offset (the display shows the server's time) and the
 *   reachability store.
 * * A non-JSON reply (e.g. a proxy's 502 HTML page) counts as "server unreachable".
 */
import createClient, { type Middleware } from "openapi-fetch";

import { recordClockSample } from "../lib/clock";
import { markReachable, markUnreachable } from "../lib/connection";
import { getLanguage, t } from "../lib/lang";
import type { paths } from "./schema";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    /** A parent-only action the parent PIN can unlock on this device. */
    readonly pin = false,
    readonly problems: string[] = [],
    /** Seconds until another try is allowed (429). */
    readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const sentAt = new WeakMap<Request, number>();

const middleware: Middleware = {
  onRequest({ request }) {
    sentAt.set(request, Date.now());
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set("X-Sunroom", "1");
    }
    return request;
  },
  onResponse({ request, response }) {
    const serverTime = Number(response.headers.get("X-Server-Time-Ms"));
    const started = sentAt.get(request);
    if (started !== undefined && serverTime) recordClockSample(started, Date.now(), serverTime);
    const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
    if (response.status >= 502 && !isJson) {
      markUnreachable();
    } else {
      markReachable();
    }
    return response;
  },
  onError() {
    markUnreachable();
    return new ApiError(0, "offline", t("app.offline.error"));
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(middleware);

interface ErrorEnvelope {
  error?: { code?: string; message?: string; pin?: boolean; problems?: string[] };
}

/** Unwrap an openapi-fetch result: return data, or throw an ApiError with the server's message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const envelope = (result.error ?? {}) as ErrorEnvelope;
    throw new ApiError(
      result.response.status,
      envelope.error?.code ?? "error",
      envelope.error?.message ?? t("app.error.generic"),
      envelope.error?.pin === true,
      envelope.error?.problems ?? [],
      Number(result.response.headers.get("retry-after")) || null,
    );
  }
  return result.data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return t("app.offline.error");
}

/** "Not saved — you're offline. Try again when you have signal." (UX §2): what a setting that
 * saves itself says when the save is refused, with the server's own sentence after the dash. */
export function notSaved(error: unknown): string {
  const why = errorMessage(error);
  // In English a sentence's first letter drops to lower case after the dash ("PIN…" and "I…"
  // don't); another language's message says it its own way (docs/LANGUAGES.md).
  const lower = getLanguage() === "en" && /^[A-Z][a-z']/.test(why) && !why.startsWith("I ");
  return t("app.not_saved", { why: lower ? why.charAt(0).toLowerCase() + why.slice(1) : why });
}

/**
 * Who tapped, on the wall screen (PLAN §12.3): the person whose avatar or column it was. Spread
 * into a request's options; the server ignores it from phones, which act as their own person.
 */
export function asMember(memberId: string | null | undefined): {
  headers?: Record<string, string>;
} {
  return memberId ? { headers: { "X-Sunroom-Member": memberId } } : {};
}
