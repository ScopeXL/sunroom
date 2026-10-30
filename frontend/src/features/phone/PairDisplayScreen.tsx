import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { codeFromHash, normalizeCode } from "../../lib/joinCode";
import { useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { Button } from "../../ui/Button";
import { Screen } from "../../ui/Screen";
import { NoCodeYet, PairCodeField, usePairDisplay } from "./PairCode";

/**
 * Pair a display (UX §5): type the code the wall screen shows (or scan its QR code, which opens
 * /pair#CODE here). The screen moves on by itself once it's paired.
 */
export function PairDisplayScreen() {
  const t = useT();
  const [code, setCode] = useState(() => codeFromHash(window.location.hash) ?? "");
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, "", "/pair");
  }, []);
  const { data: devices = [] } = useQuery({
    queryKey: qk.devices(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/auth/devices"))),
  });
  const pair = usePairDisplay();
  const valid = normalizeCode(code);
  const screens = devices.filter((device) => device.kind === "kiosk");
  return (
    <Screen title={t("phone.pair.title")} back="/more">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) {
            pair.mutate(valid, {
              onSuccess: () => {
                setCode("");
              },
            });
          }
        }}
      >
        <PairCodeField
          value={code}
          error={pair.isError ? errorMessage(pair.error) : null}
          onChange={setCode}
        />
        <Button type="submit" block pending={pair.isPending} disabled={!valid}>
          {t("phone.pair.action")}
        </Button>
        <NoCodeYet />
      </form>
      {screens.length > 0 ? (
        <section className="mt-8">
          <h2 className="mb-2 text-row font-bold">{t("phone.pair.screens.title")}</h2>
          <ul className="divide-y divide-line rounded-chip border border-line bg-surface px-4">
            {screens.map((screen) => (
              <li key={screen.id} className="flex min-h-14 items-center text-body font-semibold">
                {screen.label}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Screen>
  );
}
