import { useState } from "react";

import { useT, type Key } from "../../lib/lang";
import { Button, ButtonLink } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";

/** What Download offers (UX §4 Backup, ADR 0034): the server makes each copy fresh, now. Its
 * words are keys, said where they're shown. */
const CHOICES: readonly { label: Key; href: string; detail: Key }[] = [
  {
    label: "settings.backup.download.data.action",
    href: "/api/admin/backups/data.db",
    detail: "settings.backup.download.data.detail",
  },
  {
    label: "settings.backup.download.photos.action",
    href: "/api/admin/backups/full.zip",
    detail: "settings.backup.download.photos.detail",
  },
];

/**
 * "Download Which?" (the shape of "Change Which?"): Data Only or Data & Photos. Each is a plain
 * link, so the browser saves the file itself, however big it is; after a tap the sheet says the
 * download started and offers Close.
 */
export function DownloadSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const [started, setStarted] = useState(false);
  // Opened again, it asks again.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setStarted(false);
  }
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  return (
    <Sheet open={open} title={t("settings.backup.download.which.title")} onClose={onClose}>
      <div className="flex flex-col gap-5 pb-2">
        {CHOICES.map((choice) => (
          <div key={choice.href} className="flex flex-col gap-2">
            <ButtonLink
              block
              variant="secondary"
              href={choice.href}
              download
              onClick={() => {
                setStarted(true);
              }}
            >
              {t(choice.label)}
            </ButtonLink>
            <p className={soft}>{t(choice.detail)}</p>
          </div>
        ))}
        {started ? (
          <>
            <p role="status" className={display ? "text-d-body" : "text-body"}>
              {t("settings.backup.download.started")}
            </p>
            <Button variant="secondary" onClick={onClose}>
              {t("app.action.close")}
            </Button>
          </>
        ) : null}
      </div>
    </Sheet>
  );
}
