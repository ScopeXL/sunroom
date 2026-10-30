/**
 * Pair a display from Settings → Devices (UX §4): the code the wall screen shows, typed
 * here, on a phone or a computer. A computer has no More, so this is its way to pair; a phone
 * also has More → Pair a Display, and the screen's QR code opens that. Not on the wall itself.
 */
import { useId, useState } from "react";

import { errorMessage } from "../../api/client";
import { normalizeCode } from "../../lib/joinCode";
import { useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { NoCodeYet, PairCodeField, usePairDisplay } from "../phone/PairCode";

export function PairDisplaySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const form = useId();
  const [code, setCode] = useState("");
  const pair = usePairDisplay();
  const valid = normalizeCode(code);
  // Closed by any means, the sheet opens empty next time.
  const close = () => {
    setCode("");
    pair.reset();
    onClose();
  };
  return (
    <Sheet
      open={open}
      title={t("settings.devices.pair.title")}
      onClose={close}
      footer={
        <Button type="submit" form={form} block pending={pair.isPending} disabled={!valid}>
          {t("settings.devices.pair.action")}
        </Button>
      }
    >
      <form
        id={form}
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) pair.mutate(valid, { onSuccess: close });
        }}
      >
        <PairCodeField
          value={code}
          error={pair.isError ? errorMessage(pair.error) : null}
          onChange={setCode}
        />
        <NoCodeYet />
      </form>
    </Sheet>
  );
}
