import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { tSaid, useT } from "../../lib/lang";
import { runProgress, type ScreenState } from "../../lib/screenAgent";
import { useStore } from "../../lib/store";
import { Button } from "../../ui/Button";
import { Digits } from "../../ui/Digits";
import { agent, said } from "../calls";
import { go } from "../route";

/**
 * Setting Up Sunroom: Sunroom on this computer (ADR 0038), from the tap on Welcome until it
 * opens. The run starts as the page opens (the tap was Continue, On This Computer chosen); a run
 * already going is joined, and one that stopped says why, with Try Again.
 */
export function HerePage({ state }: { state: ScreenState }) {
  const t = useT();
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
  const stopped = progress?.key === "agent.local.step.stopped";
  const problem = run.isError
    ? run.error.message
    : stopped && progress.message
      ? tSaid(progress.message, progress.message_key, progress.message_params)
      : null;
  const asks = state.platform === "macos" || state.platform === "windows";
  return (
    <div className="flex w-full max-w-3xl flex-col gap-6 text-left">
      <h1 className="text-d-glance font-bold">{t("screen.here.title")}</h1>
      <p className="text-d-body">{t("screen.here.lead")}</p>
      {problem ? null : (
        <p className="text-d-body font-semibold" role="status">
          {progress === null ? (
            t("screen.here.getting_ready")
          ) : progress.step.endsWith("…") ? (
            <>
              {tSaid(progress.step, progress.key)} <Digits value={`${String(progress.percent)}%`} />
            </>
          ) : (
            tSaid(progress.step, progress.key)
          )}
        </p>
      )}
      {asks && !problem ? (
        <p className="text-d-body text-ink-soft">{t("screen.here.allow_hint")}</p>
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
            {t("app.action.try_again")}
          </Button>
        ) : null}
        <Button
          variant="quiet"
          onClick={() => {
            go("/");
          }}
        >
          {t("app.action.back")}
        </Button>
      </div>
    </div>
  );
}
