import { useState } from "react";

import { useT } from "../../lib/lang";
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
  const t = useT();
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
        aria-label={t("settings.support.discord.aria")}
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
        aria-label={t("settings.support.discord.aria")}
        onClick={() => {
          setOpen(true);
        }}
      >
        {mark}
      </Button>
      <Sheet
        open={open}
        title={t("settings.support.discord.title")}
        onClose={close}
        footer={
          <Button block variant="secondary" onClick={close}>
            {t("app.action.done")}
          </Button>
        }
      >
        <div className="flex flex-col items-center gap-4 text-center">
          <p className={display ? "text-d-body" : "text-body"}>
            {t("settings.support.discord.lead")}
          </p>
          <QrCode
            value={DISCORD_URL}
            label={t("settings.support.discord.qr.aria")}
            className="size-72"
          />
          <p className={display ? "text-d-body" : "text-body"}>
            {t("settings.support.discord.scan")}
          </p>
        </div>
      </Sheet>
    </>
  );
}
