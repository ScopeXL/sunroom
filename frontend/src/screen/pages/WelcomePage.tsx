import { useEffect, useId, useState } from "react";

import type { ScreenState } from "../../lib/screenAgent";
import { Brand } from "../../ui/Brand";
import { Button } from "../../ui/Button";
import { Choice, ChoiceGroup } from "../../ui/Choice";
import { afterWifi, go } from "../route";

/** A screen with neither a cable nor Wi-Fi, that can join Wi-Fi: a network before either way. */
export function needsWifi(state: ScreenState): boolean {
  return state.network.kind === "none" && state.capabilities.includes("wifi");
}

type Way = "/here" | "/find";

/**
 * Welcome: the first page of a screen with no Sunroom yet, and its two ways on as one choice
 * (ADR 0038, ADR 0042): Sunroom on this computer, or one that already runs somewhere else. Each
 * card says what it is and when to choose it, for a family that has never set up a server; a tap
 * chooses one (this computer from the start, where it can run Sunroom), and Continue goes that way.
 */
export function WelcomePage({ state }: { state: ScreenState }) {
  const chosen = state.sunroom !== null;
  const here = state.capabilities.includes("run_sunroom");
  const offline = needsWifi(state);
  const question = useId();
  const [picked, setPicked] = useState<Way>(here ? "/here" : "/find");
  const way: Way = here ? picked : "/find";
  useEffect(() => {
    // A screen that has its Sunroom has nothing to set up: it opens it.
    if (chosen) go("/opening", true);
  }, [chosen]);
  const onward = () => {
    if (offline) {
      afterWifi.set(way);
      go("/wifi");
    } else {
      go(way);
    }
  };
  return (
    <div className="flex w-full max-w-[110rem] flex-col items-center gap-8">
      <Brand size="entry" heading />
      <p id={question} className="text-d-glance font-semibold">
        Where will your family’s Sunroom run?
      </p>
      <ChoiceGroup
        labelledBy={question}
        value={way}
        onChange={(value) => {
          if (value === "/here" || value === "/find") setPicked(value);
        }}
        className={`grid w-full gap-6 portrait:grid-cols-1 ${here ? "landscape:grid-cols-2" : ""}`}
      >
        {here ? (
          <Choice value="/here" heading="On This Computer" lead="Run Sunroom right here.">
            <span className="block text-d-body">
              This computer keeps your family’s calendar, lists and photos, and every device opens
              Sunroom from it. Nothing else to set up.
            </span>
            <span className="block text-d-body text-ink-soft">
              Choose this if your family is new to Sunroom. Keep this computer on and connected to
              your home network.
            </span>
          </Choice>
        ) : null}
        <Choice
          value="/find"
          heading="Connect to a Sunroom"
          lead="Your family already runs Sunroom somewhere else."
        >
          <span className="block text-d-body">
            On a home server, a NAS, another computer or at a web address. This screen finds it on
            your network, or you type its address.
          </span>
          <span className="block text-d-body text-ink-soft">
            Choose this if someone already set Sunroom up.
          </span>
        </Choice>
      </ChoiceGroup>
      <Button onClick={onward} className="min-w-72">
        Continue
      </Button>
    </div>
  );
}
