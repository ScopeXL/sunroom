import { useEffect, type ReactNode } from "react";

import { zonedParts } from "../lib/dates";
import { watchActivity } from "../lib/idle";
import { watchKeyboardFields } from "../lib/keyboard";
import { useFollowLanguage, useT } from "../lib/lang";
import { MotionProvider } from "../lib/motion";
import { watchPointer } from "../lib/pointer";
import { useScreenAgent, useScreenAgentEvents, type ScreenState } from "../lib/screenAgent";
import { useStore } from "../lib/store";
import { applyAppearance } from "../lib/theme";
import { useMinute } from "../lib/time";
import { KeyboardHost } from "../ui/Keyboard";
import { ShellContext } from "../ui/shell";
import { ToastRegion } from "../ui/ToastRegion";
import { CantReachPage } from "./pages/CantReachPage";
import { FindPage } from "./pages/FindPage";
import { HerePage } from "./pages/HerePage";
import { OpeningPage } from "./pages/OpeningPage";
import { ScreenSettingsPage } from "./pages/ScreenSettingsPage";
import { WelcomePage } from "./pages/WelcomePage";
import { WifiPage } from "./pages/WifiPage";
import { followHistory, route, type ScreenPath } from "./route";

/**
 * The screen's own pages (ADR 0035, UX §4 "The screen's own pages"): what a wall run by Sunroom
 * Screen shows before it has a Sunroom, while it opens one, and when it can't. The wall's own
 * shell in every way that shows: its tokens, Lexend, its keyboard docked across the bottom, its
 * toasts, its sizes and tap targets. The theme follows the time of day (dark from 7 PM to 7 AM),
 * as a wall with no household settings does.
 */
function ScreenFrame({ children }: { children: ReactNode }) {
  const { hour, minute } = zonedParts(useMinute());
  const minuteOfDay = hour * 60 + minute;
  useEffect(() => {
    applyAppearance(
      {
        theme: "auto",
        daylightTint: true,
        textSize: "standard",
        reduceMotion: false,
        display: true,
      },
      minuteOfDay,
    );
  }, [minuteOfDay]);
  useEffect(() => {
    const stopActivity = watchActivity();
    const stopKeyboard = watchKeyboardFields();
    const stopPointer = watchPointer();
    const stopHistory = followHistory();
    return () => {
      stopActivity();
      stopKeyboard();
      stopPointer();
      stopHistory();
    };
  }, []);
  return (
    <ShellContext.Provider value="display">
      <MotionProvider reduceMotion={false}>
        {/* No rail and no Today panel: the toasts sit across the whole screen. */}
        <main
          data-shell="display"
          className="flex min-h-dvh flex-col items-center justify-center gap-8 bg-wall px-10 py-12 pb-[calc(var(--osk-h,0px)+48px)] text-center text-ink [--panel-w:0px] [--rail-w:0px]"
        >
          {children}
        </main>
        <ToastRegion display railSide="left" panelShown={false} />
        <KeyboardHost rail={null} />
      </MotionProvider>
    </ShellContext.Provider>
  );
}

function Page({ path, state }: { path: ScreenPath; state: ScreenState }) {
  switch (path) {
    case "/here":
      return <HerePage state={state} />;
    case "/wifi":
      return <WifiPage state={state} />;
    case "/find":
      return <FindPage state={state} />;
    case "/opening":
      return <OpeningPage state={state} />;
    case "/cant-reach":
      return <CantReachPage state={state} />;
    case "/settings":
      return <ScreenSettingsPage state={state} />;
    case "/":
      return <WelcomePage state={state} />;
  }
}

export function ScreenApp() {
  const t = useT();
  useScreenAgentEvents();
  const state = useScreenAgent();
  // The household's language, once this screen's Sunroom has said it (ADR 0043); before that
  // the browser's, as the page started.
  useFollowLanguage(state?.sunroom?.language);
  const path = useStore(route);
  return (
    <ScreenFrame>
      {state ? (
        <Page path={path} state={state} />
      ) : (
        <p className="text-d-body text-ink-soft">{t("screen.starting")}</p>
      )}
    </ScreenFrame>
  );
}
