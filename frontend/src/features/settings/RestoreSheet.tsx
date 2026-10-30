import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { t, useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { announceRestart, askingHere } from "../../lib/restart";
import { uploadBackup, type RestoreSummary } from "../../lib/restoreUpload";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { copyWhen } from "./backupWords";

/** How long the restart may take before the sheet says to look at the server. */
export const COME_BACK_WITHIN_MS = 180_000;

type Step = "sending" | "refused" | "summary" | "password" | "restarting";

/** "sunroom-2026-10-07.zip, made Wed, Oct 7, 3:00 PM by Sunroom 0.11.0." */
export function madeWords(summary: RestoreSummary): string {
  const file = summary.file_name;
  const version = summary.app_version;
  if (summary.created_at) {
    const when = copyWhen(summary.created_at);
    return version
      ? t("settings.backup.restore.made_by", { file, when, version })
      : t("settings.backup.restore.made", { file, when });
  }
  return version
    ? t("settings.backup.restore.from", { file, version })
    : t("settings.backup.restore.file", { file });
}

/** "It holds 4 people, 12 events, 3 lists and 6 photos." (a .db holds no photos) */
export function holdsWords(summary: RestoreSummary): string {
  const rows = summary.row_counts;
  const counts = {
    people: rows.members ?? 0,
    events: rows.events ?? 0,
    lists: rows.lists ?? 0,
  };
  return summary.kind === "zip"
    ? t("settings.backup.restore.holds_photos", { ...counts, photos: summary.photo_files })
    : t("settings.backup.restore.holds", counts);
}

/**
 * Restore from a File? (UX §4 Backup, ADR 0034). The file goes to the server with its progress
 * shown, comes back as what it holds, and is restored only with the household password; then
 * Sunroom runs itself again and every page reloads (lib/restart, which this page waits on too).
 * Closing before that forgets the file on the server.
 */
export function RestoreSheet({
  file,
  onClose,
  upload = uploadBackup,
}: {
  /** The file chosen; null keeps the sheet closed. */
  file: File | null;
  onClose: () => void;
  upload?: typeof uploadBackup;
}) {
  const t = useT();
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>("sending");
  const [progress, setProgress] = useState(0);
  const [summary, setSummary] = useState<RestoreSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [slow, setSlow] = useState(false);
  const request = useRef<XMLHttpRequest | null>(null);
  // Another file chosen: everything starts over.
  const [shown, setShown] = useState(file);
  if (file !== shown) {
    setShown(file);
    if (file) {
      setStep("sending");
      setProgress(0);
      setSummary(null);
      setProblem(null);
      setPassword("");
      setSlow(false);
    }
  }

  // A file chosen: send it.
  useEffect(() => {
    if (!file) return;
    const sending = new XMLHttpRequest();
    request.current = sending;
    asParent(() => upload(file, setProgress, sending)).then(
      (staged) => {
        setSummary(staged);
        setStep("summary");
      },
      (error: unknown) => {
        if (error instanceof ApiError && error.code === "aborted") return;
        setProblem(errorMessage(error));
        setStep("refused");
      },
    );
    return () => {
      sending.abort();
    };
  }, [file, upload]);

  // Restarting: if Sunroom isn't back in three minutes, say where to look.
  useEffect(() => {
    if (step !== "restarting") return;
    const timer = setTimeout(() => {
      setSlow(true);
    }, COME_BACK_WITHIN_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [step]);

  const apply = useMutation({
    mutationFn: async () => {
      askingHere(true);
      try {
        return await asParent(async () =>
          unwrap(await api.POST("/api/admin/restore/apply", { body: { password } })),
        );
      } catch (error) {
        askingHere(false);
        throw error;
      }
    },
    onSuccess: () => {
      setStep("restarting");
      announceRestart("restore");
    },
  });

  const close = () => {
    if (step === "sending") request.current?.abort();
    if (step === "sending" || step === "summary" || step === "password") {
      // Keep Everything: the server forgets the file.
      void asParent(async () => {
        unwrap(await api.DELETE("/api/admin/restore"));
      })
        .catch(() => undefined)
        .then(() => queryClient.invalidateQueries({ queryKey: qk.restore() }));
    }
    onClose();
  };

  const body = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const percent = Math.round(progress * 100);
  return (
    <Sheet
      open={file !== null}
      title={t("settings.backup.restore.sheet.title")}
      step={step}
      onClose={close}
    >
      {step === "sending" ? (
        <div className="flex flex-col gap-4 pb-2">
          <div
            role="progressbar"
            aria-label={t("settings.backup.restore.sending.aria")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-3 overflow-hidden rounded-full bg-line"
          >
            <div className="h-full bg-ink" style={{ width: `${String(percent)}%` }} />
          </div>
          <p role="status" className={body}>
            {t("settings.backup.restore.sending", { percent })}
          </p>
        </div>
      ) : null}
      {step === "refused" ? (
        <div className="flex flex-col gap-4 pb-2">
          <p role="alert" className={`${body} font-semibold text-alert`}>
            {problem}
          </p>
          <div>
            <Button variant="secondary" onClick={close}>
              {t("app.action.close")}
            </Button>
          </div>
        </div>
      ) : null}
      {step === "summary" && summary ? (
        <div className="flex flex-col gap-4 pb-2">
          <p className={`${body} font-semibold`}>{madeWords(summary)}</p>
          <p className={body}>{holdsWords(summary)}</p>
          {summary.needs_upgrade ? (
            <p className={body}>{t("settings.backup.restore.upgrade")}</p>
          ) : null}
          {summary.kind === "db" ? (
            <p className={body}>{t("settings.backup.restore.photos_stay")}</p>
          ) : null}
          <p className={soft}>{t("settings.backup.restore.kept")}</p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="secondary"
              onClick={() => {
                setStep("password");
              }}
            >
              {t("settings.backup.restore.copy.action")}
            </Button>
            <Button variant="secondary" onClick={close}>
              {t("settings.backup.keep_everything.action")}
            </Button>
          </div>
        </div>
      ) : null}
      {step === "password" ? (
        <form
          className="flex flex-col gap-4 pb-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (password && !apply.isPending) apply.mutate();
          }}
        >
          <p className={body}>{t("settings.backup.restore.password.lead")}</p>
          <TextField
            label={t("settings.backup.password.label")}
            type="password"
            layout="password"
            autoCapitalize="none"
            autoComplete="current-password"
            value={password}
            error={apply.isError ? errorMessage(apply.error) : null}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
          <div className="flex flex-wrap gap-3">
            <Button type="submit" variant="danger" pending={apply.isPending} disabled={!password}>
              {t("settings.backup.restore.action")}
            </Button>
            <Button variant="secondary" onClick={close}>
              {t("settings.backup.keep_everything.action")}
            </Button>
          </div>
        </form>
      ) : null}
      {step === "restarting" ? (
        <div className="flex flex-col gap-4 pb-2">
          <p role="status" className={body}>
            {t("settings.backup.restore.restarting")}
          </p>
          {slow ? (
            <p role="alert" className={`${body} font-semibold`}>
              {t("settings.backup.restore.slow")}
            </p>
          ) : null}
        </div>
      ) : null}
    </Sheet>
  );
}
