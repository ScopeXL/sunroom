import { useEffect } from "react";

import { ThisScreenPage } from "../../features/settings/ThisScreenPage";
import { whenIdle } from "../../lib/idle";
import { useT } from "../../lib/lang";
import type { ScreenState } from "../../lib/screenAgent";
import { Button } from "../../ui/Button";
import { go, openSunroom } from "../route";

/** Two quiet minutes, and the screen goes back to its Sunroom when it can (UX §1 idle). */
export const SETTINGS_IDLE_MS = 2 * 60_000;

/**
 * This Screen, on the screen's own pages: Settings → This Screen's twin, for when Sunroom can't
 * load. Its way back is to Sunroom (or to finding one), and it goes back by itself after two
 * quiet minutes when Sunroom answers.
 */
export function ScreenSettingsPage({ state }: { state: ScreenState }) {
  const t = useT();
  const back = state.sunroom?.reachable === true ? state.open_url : null;
  useEffect(() => {
    if (!back) return;
    return whenIdle(SETTINGS_IDLE_MS, () => {
      openSunroom(back);
    });
  }, [back]);
  return (
    <div className="flex w-full max-w-5xl flex-col gap-8 text-left">
      <h1 className="text-d-glance font-bold">{t("settings.this_screen.title")}</h1>
      <ThisScreenPage
        onForgot={() => {
          go("/find");
        }}
      />
      <div>
        {state.sunroom ? (
          <Button
            onClick={() => {
              if (back) openSunroom(back);
              else go("/cant-reach");
            }}
          >
            {t("screen.settings.back.action")}
          </Button>
        ) : (
          <Button
            onClick={() => {
              go("/find");
            }}
          >
            {t("screen.settings.find.action")}
          </Button>
        )}
      </div>
    </div>
  );
}
