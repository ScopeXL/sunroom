import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { runProgress, screenClient, type ScreenState } from "../../lib/screenAgent";
import { useStore } from "../../lib/store";
import { Button } from "../../ui/Button";
import { Digits } from "../../ui/Digits";
import { go } from "../route";

const NO_ANSWER = "This screen didn’t answer. Try again in a moment.";

function agent() {
  const client = screenClient();
  if (!client) throw new Error(NO_ANSWER);
  return client;
}

/** The agent's plain sentence for a refusal, or that it didn't answer. */
function said(error: unknown): string {
  const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
  return message ?? NO_ANSWER;
}

/**
 * Setting Up Sunroom: Sunroom on this computer (ADR 0038), from the tap on Welcome until it
 * opens. The run starts as the page opens (the tap was Run Sunroom Here); a run already going is
 * joined, and one that stopped says why, with Try Again.
 */
export function HerePage({ state }: { state: ScreenState }) {
  const progress = useStore(runProgress);
  const chosen = state.sunroom !== null;
  const run = useMutation({
    mutationFn: async () => {
      runProgress.set(null);
      const { error } = await agent().POST("/api/screen/run-sunroom");
      if (error !== undefined) throw new Error(said(error));
    },
  });
  const started = useRef(false);
  const { mutate } = run;
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    mutate();
  }, [mutate]);
  useEffect(() => {
    // Running here, or chosen meanwhile: open it.
    if (chosen) go("/opening", true);
  }, [chosen]);
  const stopped = progress?.step === "Stopped";
  const problem = run.isError ? run.error.message : stopped ? progress.message : null;
  const asks = state.platform === "macos" || state.platform === "windows";
  return (
    <div className="flex w-full max-w-3xl flex-col gap-6 text-left">
      <h1 className="text-d-glance font-bold">Setting Up Sunroom</h1>
      <p className="text-d-body">
        Sunroom is being set up on this computer. It takes a few minutes, and this screen opens it
        when it’s ready.
      </p>
      {problem ? null : (
        <p className="text-d-body font-semibold" role="status">
          {progress === null ? (
            "Getting ready…"
          ) : progress.step.endsWith("…") ? (
            <>
              {progress.step} <Digits value={`${String(progress.percent)}%`} />
            </>
          ) : (
            progress.step
          )}
        </p>
      )}
      {asks && !problem ? (
        <p className="text-d-body text-ink-soft">
          If this computer asks whether Sunroom may accept connections, choose Allow, so your
          family’s devices can reach it.
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-d-body font-semibold text-alert">
          {problem}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-4">
        {problem ? (
          <Button
            pending={run.isPending}
            onClick={() => {
              run.mutate();
            }}
          >
            Try Again
          </Button>
        ) : null}
        <Button
          variant="quiet"
          onClick={() => {
            go("/");
          }}
        >
          Back
        </Button>
      </div>
    </div>
  );
}
