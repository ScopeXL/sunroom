import { Plus } from "lucide-react";
import { useState } from "react";

import { formatTime } from "../../lib/dates";
import { usePlugins } from "../../lib/household";
import { useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { ListRow } from "../../ui/ListRow";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { Group, Text } from "../settings/parts";
import { PluginSettingsForm } from "../settings/PluginSettingsForm";
import {
  useLibraries,
  useLibraryKinds,
  usePhotoChanges,
  useSources,
  type PhotoLibrary,
  type PhotoSource,
} from "./data";
import { LibraryPanel, type LibraryOpening } from "./LibraryPanel";
import { libraryLine } from "./words";

/**
 * Settings → Photos & screensaver (UX §4 "Photos room" Settings): when it starts, how often the
 * photo changes, the clock and what's next, shuffle; the photos folder on the server, which
 * brings in whatever is put there; and the photo libraries (ADR 0036), a row each and Add a
 * Library, which open one panel.
 */
export function SettingsScreensaver() {
  const t = useT();
  const { data: plugins = [] } = usePlugins();
  const plugin = plugins.find((p) => p.id === "screensaver");
  const { data: sources = [] } = useSources();
  const [opening, setOpening] = useState<LibraryOpening | null>(null);
  return (
    <>
      {plugin ? (
        <Group title={t("photos.settings.saver.title")}>
          <PluginSettingsForm
            pluginId="screensaver"
            spec={plugin.settings_spec}
            values={plugin.settings}
          />
        </Group>
      ) : null}
      {sources.map((source) => (
        <SourceGroup key={source.id} source={source} />
      ))}
      <LibrariesGroup onOpen={setOpening} />
      <LibraryPanel
        opening={opening}
        onOpen={setOpening}
        onClose={() => {
          setOpening(null);
        }}
      />
    </>
  );
}

/** Photo Libraries: a row per library (how it's doing, how many photos), then Add a Library. */
function LibrariesGroup({ onOpen }: { onOpen: (opening: LibraryOpening) => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: libraries = [] } = useLibraries();
  const { data: kinds = [] } = useLibraryKinds();
  // "Immich", "Immich and X": the kinds of library Sunroom can connect.
  const names =
    kinds
      .map((kind) => kind.name)
      .reduce<string>(
        (all, name) =>
          all ? t("photos.settings.libraries.and", { names: all, last: name }) : name,
        "",
      ) || "Immich";
  return (
    <Group
      title={t("photos.settings.libraries.title")}
      note={t("photos.settings.libraries.note", { names })}
    >
      {libraries.map((library) => (
        <LibraryRow
          key={library.id}
          library={library}
          onOpen={() => {
            onOpen({ page: "library", id: library.id });
          }}
        />
      ))}
      {libraries.length === 0 ? (
        <div className={display ? "py-5" : "py-4"}>
          <Text>{t("photos.settings.libraries.empty")}</Text>
        </div>
      ) : null}
      <div className={display ? "py-5" : "py-4"}>
        <Button
          variant="secondary"
          onClick={() => {
            onOpen({ page: "add" });
          }}
        >
          <Plus aria-hidden="true" className={display ? "size-7" : "size-5"} />
          {t("photos.library.add.action")}
        </Button>
      </div>
    </Group>
  );
}

function LibraryRow({ library, onOpen }: { library: PhotoLibrary; onOpen: () => void }) {
  const t = useT();
  const line = libraryLine(library);
  return (
    <ListRow
      label={t("photos.library.edit.aria", { name: library.name })}
      title={library.name}
      subtitle={
        line.trouble ? (
          <span role="status" className="font-semibold text-alert">
            {line.text}
          </span>
        ) : (
          line.text
        )
      }
      onClick={onOpen}
    />
  );
}

function SourceGroup({ source }: { source: PhotoSource }) {
  const t = useT();
  const display = useShell() === "display";
  const { scan, setSource } = usePhotoChanges();
  const checked = source.last_scan_at
    ? t("photos.source.checked", { time: formatTime(new Date(source.last_scan_at)) })
    : t("photos.not_checked");
  // Sunroom's own folder gets its name from here, a heading in Title Case (UX §2); a source
  // someone named keeps its name as they wrote it.
  const inbox = source.kind === "inbox";
  return (
    <Group
      title={inbox ? t("photos.source.inbox.title") : source.label}
      note={source.kind === "inbox" ? t("photos.source.inbox.note") : undefined}
    >
      <Switch
        label={
          inbox
            ? t("photos.source.inbox.label")
            : t("photos.source.enabled.label", { name: source.label })
        }
        checked={source.enabled}
        onChange={(enabled) => {
          setSource.mutate({ id: source.id, enabled });
        }}
      />
      <div
        className={`flex flex-wrap items-center justify-between gap-3 ${display ? "py-5" : "py-4"}`}
      >
        <div className="flex flex-col gap-1">
          <Text>{`${t("photos.source.count", { n: source.photo_count })} · ${checked}`}</Text>
          {source.last_error ? (
            <p
              role="status"
              className={`${display ? "text-d-secondary" : "text-secondary"} font-semibold text-alert`}
            >
              {source.last_error}
            </p>
          ) : null}
        </div>
        <Button
          variant="secondary"
          disabled={!source.enabled}
          pending={scan.isPending}
          onClick={() => {
            scan.mutate(source.id);
          }}
        >
          {t("photos.check_now.action")}
        </Button>
      </div>
    </Group>
  );
}
