import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { asParent } from "../../lib/parent";
import { reloadFresh } from "../../lib/update";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";

/**
 * Erase everything (UX §4 Settings → Backup → Start Over; ADR 0029), one of the few things that
 * asks first, because no Undo covers it. Two steps: keep a copy (the whole household as a zip,
 * photos included, or "I have a copy"), then the household password. The server keeps a copy of
 * the database itself before it erases; the photos are what only the zip saves. Afterwards this
 * device reloads fresh and lands on setup, like every other device and screen.
 */
export function EraseSheet({
  open,
  onClose,
  reload = reloadFresh,
}: {
  open: boolean;
  onClose: () => void;
  /** What to do once everything is gone (tests stand in for the reload). */
  reload?: () => Promise<void>;
}) {
  const display = useShell() === "display";
  const [step, setStep] = useState<"copy" | "password">("copy");
  const [downloading, setDownloading] = useState(false);
  const [password, setPassword] = useState("");
  // Opened again, it starts over: the first step, and nothing typed.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setStep("copy");
      setDownloading(false);
      setPassword("");
    }
  }
  const erase = useMutation({
    mutationFn: () =>
      asParent(async () => unwrap(await api.POST("/api/admin/erase", { body: { password } }))),
    onSuccess: () => reload(),
  });
  const body = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  return (
    <Sheet open={open} title="Erase Everything?" step={step} onClose={onClose}>
      {step === "copy" ? (
        <div className="flex flex-col gap-4">
          <p className={`${body} font-semibold`}>Keep a copy first?</p>
          <p className={body}>
            This removes every person, calendar, event, list, task, meal, countdown, photo and
            setting, and signs out every device and screen. A copy of today's database stays on the
            server in backups/pre-erase, but photos are deleted for good.
          </p>
          <div className="flex flex-wrap gap-3">
            {/* A plain link: the browser saves the file itself, however big it is. */}
            <a
              href="/api/admin/backups/full.zip"
              download
              onClick={() => {
                setDownloading(true);
              }}
              className={`press inline-flex items-center border-2 border-line bg-surface font-semibold ${
                display
                  ? "min-h-tap rounded-button-d px-7 text-d-body"
                  : "min-h-11 rounded-button px-5 text-body"
              }`}
            >
              Download Everything
            </a>
            <Button
              variant="secondary"
              onClick={() => {
                setStep("password");
              }}
            >
              I Have a Copy
            </Button>
          </div>
          {downloading ? (
            <p role="status" className={soft}>
              The download has started. Continue once it's saved.
            </p>
          ) : null}
        </div>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (password && !erase.isPending) erase.mutate();
          }}
        >
          <p className={body}>
            Type the household password to erase everything and start Sunroom over.
          </p>
          <TextField
            label="Household password"
            type="password"
            layout="password"
            autoCapitalize="none"
            autoComplete="current-password"
            value={password}
            error={erase.isError ? errorMessage(erase.error) : null}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
          <div className="flex flex-wrap gap-3">
            <Button
              type="submit"
              variant="danger"
              pending={erase.isPending || erase.isSuccess}
              disabled={!password}
            >
              Erase Everything
            </Button>
            <Button variant="secondary" onClick={onClose}>
              Keep Everything
            </Button>
          </div>
        </form>
      )}
    </Sheet>
  );
}
