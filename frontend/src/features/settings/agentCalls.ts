/**
 * This Screen's calls to Sunroom Screen, the agent beside the wall's browser (ADR 0035): its
 * answer, or what it said when it refused, in its own plain sentence.
 */
import { t, tSaid } from "../../lib/lang";
import { screenClient } from "../../lib/screenAgent";

/** What a call that never reached the agent says, in the page's language as it is now. */
function noAnswer(): string {
  return t("settings.this_screen.no_answer.error");
}

/** A refusal from the agent: its own plain sentence, in the page's language when the page knows
 * its key (ADR 0043). */
export class Refusal extends Error {}

export function refusal(error: unknown): string {
  return error instanceof Refusal ? error.message : noAnswer();
}

/** The agent's answer, or a Refusal with what it said (its error envelope). */
export function answer<T>(result: { data?: T; error?: unknown }): T {
  if (result.error !== undefined) {
    const said = (
      result.error as {
        error?: { message?: string; key?: string | null; params?: Record<string, string> };
      }
    ).error;
    throw new Refusal(said?.message ? tSaid(said.message, said.key, said.params) : noAnswer());
  }
  return result.data as T;
}

export function agent() {
  const client = screenClient();
  if (!client) throw new Refusal(noAnswer());
  return client;
}

/** Reinstall…: Sunroom Screen at the version it runs, set up again the way the installer does
 * (ADR 0044); its steps and how it ended arrive like an update's. */
export async function reinstall(): Promise<void> {
  answer(await agent().POST("/api/screen/reinstall"));
}
