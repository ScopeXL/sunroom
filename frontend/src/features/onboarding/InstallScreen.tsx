import { useNavigate, useSearch } from "@tanstack/react-router";
import { EllipsisVertical } from "lucide-react";
import type { ReactNode } from "react";

import { tRich, useT } from "../../lib/lang";
import { isAndroid, isIOS, skipInstallGuide } from "../../lib/platform";
import { SunMark } from "../../ui/SunMark";
import { Button } from "../../ui/Button";
import {
  ChromeBarArt,
  ChromeMenuArt,
  HomeScreenArt,
  SafariBarArt,
  ShareSheetArt,
} from "./InstallArt";

/** The steps, in order. Safari stops announcing a list once its markers are hidden, so
 * role="list" keeps it one for VoiceOver. */
function Steps({ children }: { children: ReactNode }) {
  return (
    <ol role="list" className="rounded-chip border border-line bg-surface">
      {children}
    </ol>
  );
}

/** One step: the drawing (decorative), its number, and what to do. */
function Step({ number, art, children }: { number: number; art: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-center gap-4 border-b border-line p-4 last:border-b-0">
      {art}
      <div className="min-w-0 text-body">
        <p className="text-row font-bold text-ink">{number}</p>
        <p className="mt-1">{children}</p>
      </div>
    </li>
  );
}

/** A button that is only dots on screen: shown as the dots, read aloud as words. */
function Dots({ shown, spoken }: { shown: ReactNode; spoken: ReactNode }) {
  return (
    <>
      <strong aria-hidden="true">{shown}</strong>
      <span className="sr-only">{spoken}</span>
    </>
  );
}

/** "Put Sunroom on your home screen" (UX §5 "Install the app"; PLAN §13.8: on an iPhone any
 * home-screen site opens as a web app, even over plain HTTP). */
export function InstallScreen() {
  const t = useT();
  const navigate = useNavigate();
  const { from } = useSearch({ from: "/public/install" });
  const beforeSignIn = from !== "more";

  return (
    <main className="mx-auto w-full max-w-md px-4 pt-[calc(env(safe-area-inset-top)+32px)] pb-12">
      <SunMark className="mb-6 size-16" />
      <h1 className="text-title font-bold">{t("setup.install.title")}</h1>
      <p className="mt-2 mb-6 text-body text-ink-soft">{t("setup.install.lead")}</p>

      {isIOS() ? (
        <>
          <Steps>
            <Step number={1} art={<SafariBarArt />}>
              {tRich("setup.install.ios.share", {
                b: (words) => <strong>{words}</strong>,
                dots: (words) => <Dots shown="•••" spoken={words} />,
              })}
            </Step>
            <Step number={2} art={<ShareSheetArt />}>
              {tRich("setup.install.ios.add", { b: (words) => <strong>{words}</strong> })}
            </Step>
            <Step number={3} art={<HomeScreenArt kind="iphone" />}>
              {t("setup.install.open")}
            </Step>
          </Steps>
          <p className="mt-4 text-secondary text-ink-soft">{t("setup.install.ios.sign_in")}</p>
        </>
      ) : isAndroid() ? (
        <Steps>
          <Step number={1} art={<ChromeBarArt />}>
            {tRich("setup.install.android.menu", {
              dots: (words) => (
                <Dots
                  // The ⋮ character isn't in the app's font, and fallback fonts draw it thin. The
                  // icon's box is wider than its dots, so the margins pull the words back in.
                  shown={
                    <EllipsisVertical
                      strokeWidth={3}
                      className="-mx-[0.3em] inline size-[1em] align-[-0.125em]"
                    />
                  }
                  spoken={words}
                />
              ),
            })}
          </Step>
          <Step number={2} art={<ChromeMenuArt />}>
            {tRich("setup.install.android.install", { b: (words) => <strong>{words}</strong> })}
          </Step>
          <Step number={3} art={<HomeScreenArt kind="android" />}>
            {t("setup.install.open")}
          </Step>
        </Steps>
      ) : (
        <p className="rounded-chip border border-line bg-surface p-4 text-body">
          {t("setup.install.elsewhere")}
        </p>
      )}

      <div className="mt-8">
        {beforeSignIn ? (
          <Button
            variant="secondary"
            block
            onClick={() => {
              skipInstallGuide();
              void navigate({ to: "/sign-in" });
            }}
          >
            {t("setup.install.continue.action")}
          </Button>
        ) : (
          <Button
            variant="secondary"
            block
            onClick={() => {
              void navigate({ to: "/more" });
            }}
          >
            {t("app.action.back")}
          </Button>
        )}
      </div>
    </main>
  );
}
