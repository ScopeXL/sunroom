/**
 * The only way the app talks to the API: a typed openapi-fetch client (Dinner Bell's ADR 0018).
 *
 * * Mutations carry the CSRF header `X-Sunroom: 1` (PLAN §12.5).
 * * Every response feeds the server-clock offset (the display shows the server's time) and the
 *   reachability store.
 * * A non-JSON reply (e.g. a proxy's 502 HTML page) counts as "server unreachable".
 * * A refusal names its sentence's key and values beside the server's English (ADR 0043): the
 *   page says it in the family's language, and the English for a key this page doesn't know.
 */
import createClient, { type Middleware } from "openapi-fetch";

import { recordClockSample } from "../lib/clock";
import { markReachable, markUnreachable } from "../lib/connection";
import { getLanguage, isKey, t, type Params } from "../lib/lang";
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
    /** The sentence's key in lang/en.json (`api.…`, or the page's own), when one was named. */
    readonly key: string | null = null,
    /** The key's `{name}` values. */
    readonly params: Params = {},
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
    return new ApiError(0, "offline", t("app.offline.error"), false, [], null, "app.offline.error");
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(middleware);

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    key?: string;
    params?: Params;
    pin?: boolean;
    problems?: string[];
  };
}

/** Unwrap an openapi-fetch result: return data, or throw an ApiError with the server's message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const said = ((result.error ?? {}) as ErrorEnvelope).error;
    const message = said?.message;
    throw new ApiError(
      result.response.status,
      said?.code ?? "error",
      message ?? t("app.error.generic"),
      said?.pin === true,
      said?.problems ?? [],
      Number(result.response.headers.get("retry-after")) || null,
      said?.key ?? (message === undefined ? "app.error.generic" : null),
      said?.params ?? {},
    );
  }
  return result.data as T;
}

/** What went wrong, in the page's language: the sentence's key when this page knows it, else the
 * server's own English (a key from a newer server). */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return t("app.offline.error");
  return error.key !== null && isKey(error.key) ? t(error.key, error.params) : error.message;
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
