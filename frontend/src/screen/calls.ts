/**
 * The screen's pages' calls to their own agent: its client, and what it said when it refused,
 * in the page's language when the page knows the sentence's key (ADR 0043).
 */
import { t, tSaid } from "../lib/lang";
import { screenClient } from "../lib/screenAgent";

export function noAnswer(): string {
  return t("screen.no_answer.error");
}

export function agent() {
  const client = screenClient();
  if (!client) throw new Error(noAnswer());
  return client;
}

/** A sentence the agent said: its English, and its key and values. */
export interface Said {
  message?: string | null;
  key?: string | null;
  params?: Record<string, string>;
}

/** What the agent said, in the page's language, or that it didn't answer. */
export function saying(what: Said | null | undefined): string {
  return what?.message ? tSaid(what.message, what.key, what.params) : noAnswer();
}

/** A refusal's sentence (its error envelope), in the page's language. */
export function said(error: unknown): string {
  return saying((error as { error?: Said } | undefined)?.error);
}
