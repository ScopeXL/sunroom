import { useEffect } from "react";

import { useT } from "../../lib/lang";
import { sunroomName, type ScreenState } from "../../lib/screenAgent";
import { Button } from "../../ui/Button";
import { SunMark } from "../../ui/SunMark";
import { go, openSunroom } from "../route";

/** Two minutes without an answer, and the screen says it can't reach its Sunroom. */
export const OPENING_GIVES_UP_MS = 2 * 60_000;

/** Opening The Sample Family's Sunroom…: the sun breathing until Sunroom answers. */
export function OpeningPage({ state }: { state: ScreenState }) {
  const t = useT();
  const sunroom = state.sunroom;
  const ready = sunroom?.reachable === true ? state.open_url : null;
  useEffect(() => {
    if (!sunroom) {
      go("/find", true);
      return;
    }
    if (ready) {
      openSunroom(ready);
      return;
    }
    const timer = setTimeout(() => {
      go("/cant-reach", true);
    }, OPENING_GIVES_UP_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [sunroom, ready]);
  return (
    <>
      <SunMark className="sun-breathe size-40" decorative />
      <h1 className="text-d-glance font-bold" aria-live="polite">
        {t("screen.opening.title", { name: sunroomName(sunroom?.name) })}
      </h1>
      <Button
        variant="quiet"
        onClick={() => {
          go("/settings");
        }}
      >
        {t("settings.this_screen.title")}
      </Button>
    </>
  );
}
