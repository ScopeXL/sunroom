/** The household's live-update stream, opened by whichever shell is on screen (PLAN §11.5). */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { receiveKioskCommand } from "../shell/kioskCommands";
import { createEventHandler } from "./eventRouter";
import { LiveUpdates, liveStatus } from "./events";
import { announceRestart } from "./restart";
import { tellAgentUpdating } from "./screenAgent";
import { probeSession } from "./session";

let onSignedOut: () => void = () => undefined;

/** The router says what "signed out" means (it navigates); set once at startup. */
export function setSignedOutHandler(handler: () => void): void {
  onSignedOut = handler;
}

/** This device signed itself out (Settings → Devices). */
export function signedOutHere(): void {
  onSignedOut();
}

export function useLiveUpdates(enabled = true): void {
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    const live = new LiveUpdates({
      onEvent: createEventHandler(client, {
        onSignedOut: () => {
          onSignedOut();
        },
        onKioskCommand: receiveKioskCommand,
        onRestarting: (reason) => {
          announceRestart(reason);
          if (reason === "update") tellAgentUpdating();
        },
      }),
      onPoll: () => {
        void client.invalidateQueries();
      },
      probeSession,
    });
    live.start();
    // The page's root says what the stream is doing: a header shows its icon only when something
    // is wrong (ui/LiveStatus), so this is how a test knows the screen is hearing updates.
    const root = document.documentElement;
    const mark = () => {
      root.dataset.stream = liveStatus.get();
    };
    mark();
    const unmark = liveStatus.subscribe(mark);
    return () => {
      unmark();
      live.stop();
    };
  }, [client, enabled]);
}
