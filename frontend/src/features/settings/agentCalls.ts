/**
 * This Screen's calls to Sunroom Screen, the agent beside the wall's browser (ADR 0035): its
 * answer, or what it said when it refused, in its own plain sentence.
 */
import { t } from "../../lib/lang";
import { screenClient } from "../../lib/screenAgent";

/** What a call that never reached the agent says, in the page's language as it is now. */
function noAnswer(): string {
  return t("settings.this_screen.no_answer.error");
}

/** A refusal from the agent: its message is the agent's own plain sentence. */
export class Refusal extends Error {}

export function refusal(error: unknown): string {
  return error instanceof Refusal ? error.message : noAnswer();
}

/** The agent's answer, or a Refusal with what it said (its error envelope). */
export function answer<T>(result: { data?: T; error?: unknown }): T {
  if (result.error !== undefined) {
    const said = (result.error as { error?: { message?: string } }).error?.message;
    throw new Refusal(said ?? noAnswer());
  }
  return result.data as T;
}

export function agent() {
  const client = screenClient();
  if (!client) throw new Refusal(noAnswer());
  return client;
}
