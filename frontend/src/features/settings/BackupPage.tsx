import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { useSettings, useUpdateSettings, type SettingsChange } from "../../lib/household";
import { asParent } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Button, ButtonLink, FileButton } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { Stepper } from "../../ui/Stepper";
import { Switch } from "../../ui/Switch";
import {
  copyDay,
  copyDetail,
  copyWhen,
  daysWords,
  weeksWords,
  type BackupCopy,
} from "./backupWords";
import { DownloadSheet } from "./DownloadSheet";
import { EraseSheet } from "./EraseSheet";
import { Group, Row, Text } from "./parts";
import { RestoreSheet } from "./RestoreSheet";

/**
 * Settings → Backup (UX §4; PLAN §13.7; ADR 0034): the nightly copies and how many stay, every
 * copy on the server, a download made now (Data Only or Data & Photos), the household's data to
 * take away, and Start Over. What saves a file, removes a copy or erases everything goes by what
 * the device is, not its size: a laptop has them; a paired screen (which has no files, and which
 * a child can reach) sees the backups and the copies, and says nothing about the rest.
 */
export function BackupPage() {
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  // A paired screen shows only what it can do (UX §2 "Devices and screens"): no file buttons, and
  // nothing until the session says which this is.
  const own = session !== undefined && session?.device_kind !== "kiosk";
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const [exporting, setExporting] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [choosing, setChoosing] = useState(false);
  // The copy Remove This Copy? asks about; kept while the sheet slides away.
  const [removing, setRemoving] = useState<BackupCopy | null>(null);
  const [asking, setAsking] = useState(false);
  const [restoring, setRestoring] = useState<File | null>(null);
  const { data: status, error } = useQuery({
    queryKey: qk.backups(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/admin/backups"))),
  });
  // How the last restore went: one that didn't go through says why (ADR 0034).
  const { data: restoreState } = useQuery({
    queryKey: qk.restore(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/admin/restore"))),
    enabled: own,
  });
  const run = useMutation({
    mutationFn: () => asParent(async () => unwrap(await api.POST("/api/admin/backups/run"))),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.backups() });
      showToast("Backed up");
    },
  });
  const remove = useMutation({
    mutationFn: (copy: BackupCopy) =>
      asParent(async () => {
        unwrap(
          await api.DELETE("/api/admin/backups/{name}", { params: { path: { name: copy.name } } }),
        );
      }),
    onSuccess: async (_done, copy) => {
      setAsking(false);
      showToast(`Removed the copy from ${copyDay(copy.made_at)}`);
      await queryClient.invalidateQueries({ queryKey: qk.backups() });
    },
  });
  // Saved as it changes; the status then says again whether the newest copy is behind.
  const change = (body: SettingsChange) => {
    update.mutate(body, {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: qk.backups() });
      },
    });
  };

  const exportAll = async () => {
    setExporting(true);
    try {
      const data = await asParent(async () => unwrap(await api.GET("/api/export")));
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `sunroom-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    } finally {
      setExporting(false);
    }
  };

  const nightly = settings?.backups_enabled ?? status?.enabled ?? true;
  const busy = (status?.busy ?? false) || run.isPending;
  const block = display ? "py-5" : "py-4";
  const body = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  return (
    <>
      <Group
        title="Backups"
        note={
          own
            ? "A checked copy of the data is kept on the server. Photos are files beside it: only Data & Photos has them."
            : "A checked copy of the data is kept on the server."
        }
        action={
          <Button
            variant="secondary"
            pending={run.isPending}
            onClick={() => {
              run.mutate();
            }}
          >
            Back Up Now
          </Button>
        }
      >
        <Row
          label="Last backup"
          hint={status?.last_error ? `The last try failed: ${status.last_error}` : undefined}
        >
          <Text>
            {status?.last_success_at
              ? copyWhen(status.last_success_at)
              : nightly
                ? "Not yet. The first runs tonight."
                : "Not yet."}
          </Text>
        </Row>
        {status?.stale ? (
          <div className="py-4">
            <Text>The newest backup is over a week old. Try Back Up Now, and check the log.</Text>
          </div>
        ) : null}
        {settings ? (
          <Switch
            label="Nightly backups"
            hint="A copy every night at 3:30."
            checked={settings.backups_enabled}
            onChange={(backups_enabled) => {
              change({ backups_enabled });
            }}
          />
        ) : null}
        {settings?.backups_enabled ? (
          <>
            <Row label="Daily copies to keep">
              <Stepper
                label="Daily copies to keep"
                value={settings.backups_keep_daily}
                min={1}
                max={30}
                words={daysWords}
                onChange={(backups_keep_daily) => {
                  change({ backups_keep_daily });
                }}
              />
            </Row>
            <Row label="Weekly copies to keep" hint="The newest copy of each earlier week.">
              <Stepper
                label="Weekly copies to keep"
                value={settings.backups_keep_weekly}
                min={0}
                max={12}
                words={weeksWords}
                onChange={(backups_keep_weekly) => {
                  change({ backups_keep_weekly });
                }}
              />
            </Row>
          </>
        ) : null}
      </Group>
      <Group
        title="Copies on the Server"
        note={own && busy && status?.files.length ? "A backup is being written." : undefined}
      >
        {!status ? null : status.files.length ? (
          status.files.map((copy) => (
            <Row key={copy.name} label={copyWhen(copy.made_at)} hint={copyDetail(copy)}>
              {own ? (
                <>
                  <ButtonLink
                    variant="secondary"
                    href={`/api/admin/backups/${encodeURIComponent(copy.name)}`}
                    download
                    aria-label={`Download the copy from ${copyWhen(copy.made_at)}`}
                  >
                    Download
                  </ButtonLink>
                  <Button
                    variant="quiet-danger"
                    disabled={busy}
                    aria-label={`Remove the copy from ${copyWhen(copy.made_at)}`}
                    onClick={() => {
                      remove.reset();
                      setRemoving(copy);
                      setAsking(true);
                    }}
                  >
                    Remove
                  </Button>
                </>
              ) : null}
            </Row>
          ))
        ) : (
          <div className={block}>
            <Text soft>
              {nightly
                ? "No copies yet. The first nightly copy comes tonight."
                : "No copies yet. Back Up Now makes one."}
            </Text>
          </div>
        )}
      </Group>
      {own ? (
        <Group title="Download" note="Save a copy on this device.">
          <div className={block}>
            <Button
              variant="secondary"
              onClick={() => {
                setChoosing(true);
              }}
            >
              Download…
            </Button>
          </div>
        </Group>
      ) : null}
      {own ? (
        <Group
          title="Restore from a File"
          note="Put back a copy you downloaded: a .db, or a zip with photos. Everything on the server is replaced, every device signs in again, and wall screens show a pair code."
        >
          {restoreState?.last && !restoreState.last.ok ? (
            <div className={block}>
              <p role="alert" className={`${body} font-semibold text-alert`}>
                {`The last restore didn't go through: ${restoreState.last.problem ?? "Sunroom didn't say why."}`}
              </p>
            </div>
          ) : null}
          <div className={block}>
            <FileButton
              accept=".db,.zip,application/zip,application/vnd.sqlite3"
              onFile={setRestoring}
            >
              Choose a File…
            </FileButton>
          </div>
        </Group>
      ) : null}
      {own ? (
        <Group
          title="Take Your Data with You"
          note="One file anyone can open and read: everything you added (people, calendars and events, lists, tasks, meals, countdowns and settings) as plain text (JSON), for your own records or for moving on. Sunroom can't restore from it; Download is for that."
        >
          <div className={block}>
            <Button
              variant="secondary"
              pending={exporting}
              onClick={() => {
                void exportAll();
              }}
            >
              Export
            </Button>
          </div>
        </Group>
      ) : null}
      {own ? (
        <Group
          title="Start Over"
          note="Erase everything Sunroom knows and set it up again from the start."
        >
          <div className={block}>
            <Button
              variant="quiet-danger"
              onClick={() => {
                setErasing(true);
              }}
            >
              Erase Everything…
            </Button>
          </div>
        </Group>
      ) : null}
      <RestoreSheet
        file={restoring}
        onClose={() => {
          setRestoring(null);
        }}
      />
      <DownloadSheet
        open={choosing}
        onClose={() => {
          setChoosing(false);
        }}
      />
      {/* Asks once, because no Undo can bring a copy back. */}
      <Sheet
        open={asking}
        title="Remove This Copy?"
        onClose={() => {
          setAsking(false);
        }}
      >
        {removing ? (
          <div className="flex flex-col gap-4 pb-2">
            <p className={body}>{`The copy from ${copyWhen(removing.made_at)} goes for good.`}</p>
            <p className={soft}>{copyDetail(removing)}</p>
            <div className="flex flex-wrap gap-3">
              <Button
                variant="danger"
                pending={remove.isPending}
                onClick={() => {
                  remove.mutate(removing);
                }}
              >
                Remove
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setAsking(false);
                }}
              >
                Keep It
              </Button>
            </div>
            {remove.isError ? (
              <p role="alert" className="font-semibold text-alert">
                {errorMessage(remove.error)}
              </p>
            ) : null}
          </div>
        ) : null}
      </Sheet>
      <EraseSheet
        open={erasing}
        onClose={() => {
          setErasing(false);
        }}
      />
      {(error ?? run.error) ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(error ?? run.error)}
        </p>
      ) : null}
    </>
  );
}
