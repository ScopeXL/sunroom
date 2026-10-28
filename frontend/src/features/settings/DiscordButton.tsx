import { useState } from "react";

import { Button, ButtonLink } from "../../ui/Button";
import { DiscordMark } from "../../ui/DiscordMark";
import { QrCode } from "../../ui/QrCode";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { DISCORD_URL } from "./support";

/**
 * The Sunroom Discord in Settings' header (the wall's header, a phone's title bar; ADR 0042):
 * Discord's mark alone, named "Sunroom's Discord". A device opens it in a new tab; a paired
 * screen opens no other website, so it shows a code to scan instead.
 */
export function DiscordButton({ kiosk }: { kiosk: boolean }) {
  const display = useShell() === "display";
  const [open, setOpen] = useState(false);
  const mark = <DiscordMark className={display ? "size-8" : "size-6"} />;
  if (!kiosk) {
    return (
      <ButtonLink
        variant="secondary"
        icon
        href={DISCORD_URL}
        target="_blank"
        rel="noreferrer noopener"
        aria-label="Sunroom's Discord"
      >
        {mark}
      </ButtonLink>
    );
  }
  const close = () => {
    setOpen(false);
  };
  return (
    <>
      <Button
        variant="secondary"
        icon
        aria-label="Sunroom's Discord"
        onClick={() => {
          setOpen(true);
        }}
      >
        {mark}
      </Button>
      <Sheet
        open={open}
        title="Join the Sunroom Discord"
        onClose={close}
        footer={
          <Button block variant="secondary" onClick={close}>
            Done
          </Button>
        }
      >
        <div className="flex flex-col items-center gap-4 text-center">
          <p className={display ? "text-d-body" : "text-body"}>
            Help, ideas and what's new, from the people who make Sunroom and the families who use
            it.
          </p>
          <QrCode
            value={DISCORD_URL}
            label="A code that opens the Sunroom Discord"
            className="size-72"
          />
          <p className={display ? "text-d-body" : "text-body"}>Scan this with your phone.</p>
        </div>
      </Sheet>
    </>
  );
}
