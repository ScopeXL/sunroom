import { useEffect } from "react";

import type { ScreenState } from "../../lib/screenAgent";
import { Brand } from "../../ui/Brand";
import { Button } from "../../ui/Button";
import { Choice } from "../../ui/Choice";
import { afterWifi, go } from "../route";

/** A screen with neither a cable nor Wi-Fi, that can join Wi-Fi: a network before either way. */
export function needsWifi(state: ScreenState): boolean {
  return state.network.kind === "none" && state.capabilities.includes("wifi");
}

/**
 * Welcome: the first page of a screen with no Sunroom yet, and its two ways on, side by side
 * (ADR 0038): Sunroom on this computer, or one that already runs somewhere else. Each says what
 * it is and when to choose it, for a family that has never set up a server.
 */
export function WelcomePage({ state }: { state: ScreenState }) {
  const chosen = state.sunroom !== null;
  const here = state.capabilities.includes("run_sunroom");
  const offline = needsWifi(state);
  useEffect(() => {
    // A screen that has its Sunroom has nothing to set up: it opens it.
    if (chosen) go("/opening", true);
  }, [chosen]);
  const onward = (path: "/here" | "/find") => {
    if (offline) {
      afterWifi.set(path);
      go("/wifi");
    } else {
      go(path);
    }
  };
  return (
    <div className="flex w-full max-w-[110rem] flex-col items-center gap-8">
      <Brand size="entry" heading />
      <p className="text-d-glance font-semibold">Where will your family’s Sunroom run?</p>
      <div
        className={`grid w-full gap-6 portrait:grid-cols-1 ${here ? "landscape:grid-cols-2" : ""}`}
      >
        {here ? (
          <Choice
            heading="On This Computer"
            lead="Sunroom runs right here."
            action={
              <Button
                onClick={() => {
                  onward("/here");
                }}
              >
                Run Sunroom Here
              </Button>
            }
          >
            <p className="text-d-body">
              This computer keeps your family’s calendar, lists and photos, and everyone’s phones
              open Sunroom from it. There’s nothing else to set up.
            </p>
            <p className="text-d-body text-ink-soft">
              Choose this if your family is new to Sunroom. Keep this computer on and connected to
              your home’s network.
            </p>
          </Choice>
        ) : null}
        <Choice
          heading="On Another Computer"
          lead="Your family already has a Sunroom."
          action={
            <Button
              variant={here ? "secondary" : "primary"}
              onClick={() => {
                onward("/find");
              }}
            >
              Find Your Sunroom
            </Button>
          }
        >
          <p className="text-d-body">
            It runs somewhere else, such as a home server, a NAS, another computer or a website, and
            this screen shows it.
          </p>
          <p className="text-d-body text-ink-soft">
            Choose this if someone already set Sunroom up. This screen looks for it on your network,
            or you type its address.
          </p>
        </Choice>
      </div>
    </div>
  );
}
