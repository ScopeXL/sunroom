import { useEffect, useId, useState } from "react";

import { useT } from "../../lib/lang";
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
  const t = useT();
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
        {t("screen.welcome.question")}
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
          <Choice
            value="/here"
            heading={t("screen.welcome.here.title")}
            lead={t("screen.welcome.here.lead")}
          >
            <span className="block text-d-body">{t("screen.welcome.here.body")}</span>
            <span className="block text-d-body text-ink-soft">{t("screen.welcome.here.hint")}</span>
          </Choice>
        ) : null}
        <Choice
          value="/find"
          heading={t("screen.welcome.find.title")}
          lead={t("screen.welcome.find.lead")}
        >
          <span className="block text-d-body">{t("screen.welcome.find.body")}</span>
          <span className="block text-d-body text-ink-soft">{t("screen.welcome.find.hint")}</span>
        </Choice>
      </ChoiceGroup>
      <Button onClick={onward} className="min-w-72">
        {t("app.action.continue")}
      </Button>
    </div>
  );
}
