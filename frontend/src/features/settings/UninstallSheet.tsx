import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { asParent } from "../../lib/parent";
import { uninstalling } from "../../lib/screenAgent";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Brand } from "../../ui/Brand";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { Switch } from "../../ui/Switch";
import { ShellContext } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { agent, answer, refusal, Refusal } from "./agentCalls";

/** The wall left showing the cover this long means the uninstaller never closed it. */
const STUCK_AFTER_MS = 60_000;

/**
 * Uninstall Sunroom Screen? (ADR 0042), from This Screen's Remove group: what goes, and where
 * Sunroom runs on this computer as a program, a switch (on at first) that takes Sunroom and the
 * family's data too, which needs the household password, as Erase Everything does. Then, in
 * order: the password checked, Sunroom Screen told to uninstall itself (it answers at once, and
 * a moment later starts its uninstaller and quits, which closes the browser), and this screen
 * unpaired. The agent goes before the unpairing, so a refusal leaves the screen as it was.
 */
export function UninstallSheet({
  open,
  sunroomHere,
  onClose,
  onStarted,
}: {
  open: boolean;
  /** Sunroom runs on this computer as a program (the agent's `remove_sunroom`). */
  sunroomHere: boolean;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [alsoSunroom, setAlsoSunroom] = useState(true);
  const [password, setPassword] = useState("");
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const sunroom = sunroomHere && alsoSunroom;
  const go = useMutation({
    mutationFn: async () => {
      if (sunroom) {
        await asParent(async () => {
          const checked = await api.POST("/api/admin/password/check", { body: { password } });
          unwrap(checked);
        });
      }
      answer(await agent().POST("/api/screen/uninstall", { body: { sunroom } }));
      if (session) {
        // Its device goes with it (the cookie too); it never comes back to Devices as a
        // screen nobody can see.
        await api
          .DELETE("/api/auth/devices/{device_id}", {
            params: { path: { device_id: session.device_id } },
          })
          .catch(() => undefined);
      }
    },
    onSuccess: () => {
      showToast("Uninstalling…");
      uninstalling.set(true);
      onStarted();
    },
  });
  const why = go.isError
    ? go.error instanceof Refusal
      ? refusal(go.error)
      : errorMessage(go.error)
    : null;
  return (
    <Sheet open={open} title="Uninstall Sunroom Screen?" onClose={onClose}>
      <div className="flex flex-col gap-5 pb-2">
        <ul className="flex list-disc flex-col gap-2 pl-8 text-d-body">
          <li>This screen is unpaired and stops showing Sunroom.</li>
          <li>Sunroom Screen and its settings are removed from this computer.</li>
        </ul>
        {sunroomHere ? (
          <Switch
            label="Also remove Sunroom and the family’s data from this computer"
            hint="Everything the family added goes with it. A backup downloaded from Settings → Backup on another device can bring it back later."
            checked={alsoSunroom}
            onChange={setAlsoSunroom}
          />
        ) : null}
        {sunroom ? (
          <TextField
            label="Household password"
            type="password"
            layout="password"
            autoCapitalize="none"
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              go.reset();
            }}
          />
        ) : null}
        {why ? (
          <p role="alert" className="text-d-secondary font-semibold text-alert">
            {why}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button
            variant="danger"
            pending={go.isPending}
            disabled={sunroom && !password}
            onClick={() => {
              go.mutate();
            }}
          >
            Uninstall
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

/**
 * The whole wall while Sunroom Screen removes itself (the router shows it instead of any page
 * once `uninstalling` is set): nothing else to tap, then the browser closes. Should it still be
 * here a minute later, the uninstaller didn't run: the screen is unpaired, and Start Over
 * reloads it, so this is never a dead end (CLAUDE.md, hard rule 8).
 */
export function Uninstalling() {
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setStuck(true);
    }, STUCK_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, []);
  return (
    <ShellContext.Provider value="display">
      <main className="flex min-h-dvh flex-col items-center justify-center gap-8 bg-wall px-10 text-center">
        <Brand size="entry" />
        {stuck ? (
          <>
            <p role="status" className="max-w-3xl text-d-body">
              Sunroom Screen didn’t finish removing itself. Start over, then try again from Settings
              → This Screen.
            </p>
            <Button
              className="min-w-72"
              onClick={() => {
                window.location.reload();
              }}
            >
              Start Over
            </Button>
          </>
        ) : (
          <p role="status" className="max-w-3xl text-d-body">
            Sunroom Screen is being removed. This screen closes in a moment.
          </p>
        )}
      </main>
    </ShellContext.Provider>
  );
}
