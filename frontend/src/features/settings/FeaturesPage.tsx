import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import type { components } from "../../api/schema";
import { usePlugins } from "../../lib/household";
import { useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { Button } from "../../ui/Button";
import { ListRowLink } from "../../ui/ListRow";
import { Switch } from "../../ui/Switch";
import type { PluginModule } from "../registry";
import { usePluginModules } from "../usePluginModules";
import { Group, Text } from "./parts";
import { PluginSettingsForm } from "./PluginSettingsForm";

type PluginInfo = components["schemas"]["PluginOut"];

/** Under an enabled plugin's switch: rows to its own Settings pages when it has them, else its
 * fields from the spec; then whatever the plugin draws itself. */
function PluginFields({ plugin, modules }: { plugin: PluginInfo; modules: PluginModule[] }) {
  const t = useT();
  const module = modules.find((candidate) => candidate.id === plugin.id);
  const pages = module?.settingsPages ?? [];
  const Own = module?.settings?.features;
  return (
    <>
      {pages.length > 0 ? (
        pages.map((page) => (
          <ListRowLink
            key={page.key}
            to="/settings/$page"
            params={{ page: page.key }}
            label={t("settings.features.page.label", { page: t(page.title) })}
            title={t("settings.features.page.label", { page: t(page.title) })}
          />
        ))
      ) : plugin.settings_spec.length > 0 ? (
        <PluginSettingsForm
          pluginId={plugin.id}
          spec={plugin.settings_spec}
          values={plugin.settings}
          skipGroups={module?.ownSettingGroups ?? []}
        />
      ) : null}
      {Own ? <Own /> : null}
    </>
  );
}

/**
 * Settings → Features (UX §4, ADR 0029): one switch per plugin with a line on what it adds;
 * turning one off hides its rooms and panels at once and keeps its data. A stopped plugin says
 * so, with Retry. A feature with a Settings page of its own (Tasks, Meals, Photos & Screensaver)
 * shows a row that opens it, so its fields live in one place; the rest keep their few fields
 * here, saving as they change. A plugin can still draw something of its own under its switch
 * (`settings.features`); nothing does now that Google's keys are asked for inside Sign in with
 * Google (ADR 0030).
 */
export function FeaturesPage() {
  const t = useT();
  const { data: plugins = [] } = usePlugins();
  const modules = usePluginModules();
  const queryClient = useQueryClient();
  const toggle = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      asParent(async () =>
        on
          ? unwrap(
              await api.POST("/api/plugins/{plugin_id}/enable", {
                params: { path: { plugin_id: id } },
              }),
            )
          : unwrap(
              await api.POST("/api/plugins/{plugin_id}/disable", {
                params: { path: { plugin_id: id } },
              }),
            ),
      ),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.plugins() });
    },
  });
  const retry = useMutation({
    mutationFn: (id: string) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/plugins/{plugin_id}/restart", {
            params: { path: { plugin_id: id } },
          }),
        ),
      ),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.plugins() });
    },
  });

  if (plugins.length === 0) {
    return (
      <Group title={t("settings.features.none.title")}>
        <div className="py-5">
          <Text>{t("settings.features.none.body")}</Text>
        </div>
      </Group>
    );
  }
  // A plugin's name and description are the server's words.
  return (
    <>
      {plugins.map((plugin) => (
        <Group key={plugin.id} title={plugin.name}>
          <Switch
            label={
              plugin.enabled ? t("settings.features.on.label") : t("settings.features.off.label")
            }
            hint={plugin.description}
            checked={plugin.enabled}
            disabled={toggle.isPending}
            onChange={(on) => {
              toggle.mutate({ id: plugin.id, on });
            }}
          />
          {plugin.status === "errored" ? (
            <div className="flex flex-wrap items-center justify-between gap-3 py-4">
              <Text>{t("settings.features.stopped", { name: plugin.name })}</Text>
              <Button
                variant="secondary"
                pending={retry.isPending}
                onClick={() => {
                  retry.mutate(plugin.id);
                }}
              >
                {t("settings.features.retry.action")}
              </Button>
            </div>
          ) : null}
          {plugin.enabled ? <PluginFields plugin={plugin} modules={modules} /> : null}
          {toggle.isError ? (
            <p role="alert" className="py-3 font-semibold text-alert">
              {errorMessage(toggle.error)}
            </p>
          ) : null}
        </Group>
      ))}
    </>
  );
}
