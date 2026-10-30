import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { formatTime } from "../../lib/dates";
import { useSettings, useUpdateSettings } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { Button } from "../../ui/Button";
import { LiveStatusIcon } from "../../ui/LiveStatus";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { Group, Row, Text } from "./parts";

function gigabytes(bytes: number): string {
  return t("settings.about.size.gb", { n: (bytes / 1024 ** 3).toFixed(1) });
}

/** Settings → About (UX §4): version, storage, how this device reaches Sunroom, and the rest. */
export function AboutPage() {
  const t = useT();
  const { data: diagnostics } = useQuery({
    queryKey: qk.diagnostics(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/admin/diagnostics"))),
  });
  return (
    <>
      <Group title={t("app.sunroom")}>
        <Row label={t("settings.about.version.label")}>
          <Text>
            {diagnostics
              ? `${diagnostics.version} (${diagnostics.revision.slice(0, 7)})`
              : __APP_VERSION__}
          </Text>
        </Row>
        <Row label={t("settings.about.timezone.label")}>
          <Text>{diagnostics?.timezone.replaceAll("_", " ") ?? ""}</Text>
        </Row>
      </Group>
      {diagnostics ? (
        <Group title={t("settings.about.storage.title")}>
          <Row label={t("settings.about.free_space.label")}>
            <Text>
              {t("settings.about.free_space.value", {
                free: gigabytes(diagnostics.storage.free_bytes),
                total: gigabytes(diagnostics.storage.total_bytes),
              })}
            </Text>
          </Row>
        </Group>
      ) : null}
      <Group title={t("settings.about.connection.title")}>
        <Row label={t("settings.about.live.label")}>
          <LiveStatusIcon />
        </Row>
        {diagnostics ? (
          <>
            <Row label={t("settings.about.url.label")}>
              <Text>{`${diagnostics.client.scheme}://${diagnostics.client.host}`}</Text>
            </Row>
            <Row label={t("settings.about.recent.label")} hint={t("settings.about.recent.hint")}>
              <Text>{diagnostics.recent_addresses.join(", ")}</Text>
            </Row>
          </>
        ) : null}
      </Group>
      <UpdatesGroup />
      <Group title={t("settings.about.small_print.title")}>
        <div className="flex flex-col gap-2 py-4">
          <Text>{t("settings.about.small_print.licence")}</Text>
          <Text soft>{t("settings.about.small_print.privacy")}</Text>
          <Text soft>{t("settings.about.small_print.weather")}</Text>
        </div>
      </Group>
    </>
  );
}

/** Updates (PLAN §13.6): off until a parent turns it on, because it asks GitHub. */
function UpdatesGroup() {
  const t = useT();
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const { data: status } = useQuery({
    queryKey: qk.update(),
    queryFn: async () => unwrap(await api.GET("/api/admin/update")),
  });
  const check = useMutation({
    mutationFn: async () => asParent(async () => unwrap(await api.POST("/api/admin/update/check"))),
    onSuccess: (fresh) => {
      queryClient.setQueryData(qk.update(), fresh);
    },
  });
  if (!settings || !status) return null;
  // `how` and `problem` are the server's words.
  const line = status.available
    ? t("settings.about.updates.available", { version: status.latest ?? "", how: status.how })
    : (status.problem ??
      (status.checked_at
        ? t("settings.about.updates.latest", {
            time: formatTime(new Date(status.checked_at)),
          })
        : null));
  return (
    <Group
      title={t("settings.about.updates.title")}
      note={
        status.locked ? t("settings.about.updates.locked.note") : t("settings.about.updates.note")
      }
    >
      <Switch
        label={t("settings.about.updates.daily.label")}
        checked={settings.update_check}
        disabled={status.locked}
        onChange={(value) => {
          update.mutate(
            { update_check: value },
            {
              onSuccess: () => {
                void queryClient.invalidateQueries({ queryKey: qk.update() });
              },
            },
          );
        }}
      />
      {status.enabled ? (
        <div
          className={`flex flex-wrap items-center justify-between gap-3 ${display ? "py-5" : "py-4"}`}
        >
          <div className="flex flex-col gap-1">
            {line ? (
              status.available ? (
                <p
                  role="status"
                  className={`bg-sun/25 font-semibold ${display ? "rounded-button-d px-5 py-3 text-d-body" : "rounded-button px-4 py-3 text-body"}`}
                >
                  {line}
                </p>
              ) : (
                <Text soft>{line}</Text>
              )
            ) : null}
            {check.isError ? <Text soft>{errorMessage(check.error)}</Text> : null}
          </div>
          <Button
            variant="secondary"
            pending={check.isPending}
            onClick={() => {
              check.mutate();
            }}
          >
            {t("settings.about.updates.check.action")}
          </Button>
        </div>
      ) : null}
    </Group>
  );
}
