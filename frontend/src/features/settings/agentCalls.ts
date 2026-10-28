/**
 * This Screen's calls to Sunroom Screen, the agent beside the wall's browser (ADR 0035): its
 * answer, or what it said when it refused, in its own plain sentence.
 */
import { screenClient } from "../../lib/screenAgent";

export const NO_ANSWER = "This screen didn’t answer. Try again in a moment.";

/** A refusal from the agent: its message is the agent's own plain sentence. */
export class Refusal extends Error {}

export function refusal(error: unknown): string {
  return error instanceof Refusal ? error.message : NO_ANSWER;
}

/** The agent's answer, or a Refusal with what it said (its error envelope). */
export function answer<T>(result: { data?: T; error?: unknown }): T {
  if (result.error !== undefined) {
    const said = (result.error as { error?: { message?: string } }).error?.message;
    throw new Refusal(said ?? NO_ANSWER);
  }
  return result.data as T;
}

export function agent() {
  const client = screenClient();
  if (!client) throw new Refusal(NO_ANSWER);
  return client;
}
