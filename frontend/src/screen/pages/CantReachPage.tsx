import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useT } from "../../lib/lang";
import { sunroomName, type ScreenState } from "../../lib/screenAgent";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { agent, noAnswer, said, saying } from "../calls";
import { go, openSunroom } from "../route";

/**
 * Can't Reach The Sample Family's Sunroom: the agent shows it when the browser has shown no
 * Sunroom for two minutes. It goes back by itself the moment Sunroom answers (the agent asks
 * every 10 seconds); meanwhile everything that might help is one tap away.
 */
export function CantReachPage({ state }: { state: ScreenState }) {
  const t = useT();
  const sunroom = state.sunroom;
  const name = sunroomName(sunroom?.name);
  const back = sunroom?.reachable === true ? state.open_url : null;
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    if (!sunroom) go("/find", true);
    else if (back) openSunroom(back);
  }, [sunroom, back]);
  const tryAgain = useMutation({
    mutationFn: async () => {
      if (!sunroom) throw new Error(noAnswer());
      const { data, error } = await agent().POST("/api/screen/sunroom/check", {
        body: { url: sunroom.url },
      });
      if (error !== undefined) throw new Error(said(error));
      if (!data.ok) throw new Error(saying(data));
    },
    onSuccess: () => {
      if (state.open_url) openSunroom(state.open_url);
    },
  });
  const restart = useMutation({
    mutationFn: async () => {
      const { error } = await agent().POST("/api/screen/restart");
      if (error !== undefined) throw new Error(said(error));
    },
    onSuccess: () => {
      showToast(t("screen.cant_reach.restarting.toast"));
    },
    onError: (error) => {
      showToast(error.message);
    },
  });
  const forget = useMutation({
    mutationFn: async () => {
      const { error } = await agent().DELETE("/api/screen/sunroom");
      if (error !== undefined) throw new Error(said(error));
    },
    onSuccess: () => {
      setAsking(false);
      go("/find");
    },
  });
  const can = (capability: ScreenState["capabilities"][number]) =>
    state.capabilities.includes(capability);
  return (
    <div className="flex w-full max-w-4xl flex-col items-center gap-8">
      <h1 className="text-d-glance font-bold">{t("screen.cant_reach.title", { name })}</h1>
      <p className="text-d-body text-ink-soft" role="status">
        {t(sunroom?.updating ? "screen.cant_reach.updating" : "screen.cant_reach.away")}
      </p>
      {tryAgain.isError ? (
        <p role="alert" className="text-d-body font-semibold text-alert">
          {tryAgain.error.message}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-center gap-3">
        <Button
          pending={tryAgain.isPending}
          onClick={() => {
            tryAgain.mutate();
          }}
        >
          {t("app.action.try_again")}
        </Button>
        {can("wifi") ? (
          <Button
            variant="secondary"
            onClick={() => {
              go("/wifi");
            }}
          >
            {t("screen.cant_reach.wifi.action")}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => {
            setAsking(true);
          }}
        >
          {t("screen.cant_reach.change.action")}
        </Button>
        {can("restart") ? (
          <Button
            variant="secondary"
            pending={restart.isPending}
            onClick={() => {
              restart.mutate();
            }}
          >
            {t("screen.cant_reach.restart.action")}
          </Button>
        ) : null}
      </div>
      <Sheet
        open={asking}
        title={t("screen.cant_reach.change.title")}
        onClose={() => {
          setAsking(false);
        }}
      >
        <div className="flex flex-col gap-5 pb-2 text-left">
          <p className="text-d-body">{t("screen.cant_reach.change.body", { name })}</p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="danger"
              pending={forget.isPending}
              onClick={() => {
                forget.mutate();
              }}
            >
              {t("screen.cant_reach.change.action")}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setAsking(false);
              }}
            >
              {t("app.action.cancel")}
            </Button>
          </div>
        </div>
      </Sheet>
    </div>
  );
}
