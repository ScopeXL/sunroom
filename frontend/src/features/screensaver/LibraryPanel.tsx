import { RefreshCw, Search } from "lucide-react";
import { useState } from "react";

import { errorMessage } from "../../api/client";
import { isHomeAddress } from "../../lib/address";
import { formatTime } from "../../lib/dates";
import { tPlugin, useT } from "../../lib/lang";
import { useSavedFlash } from "../../lib/savedFlash";
import { useDebounced } from "../../lib/useDebounced";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { Field } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { SavedMark } from "../../ui/SavedMark";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import {
  useLibraries,
  useLibraryChoices,
  useLibraryKinds,
  usePhotoChanges,
  type LibraryChoice,
  type LibraryKind,
  type LibraryPicks,
  type PhotoLibrary,
} from "./data";
import { connectedLine, count, libraryLine, picksSentence } from "./words";

/** Which page the panel opens on: connecting a new library, or one that's connected. */
export type LibraryOpening = { page: "add" } | { page: "library"; id: string };

const LIMITS = [100, 250, 500, 1000, 2000] as const;

/** What's picked, every list there (the API leaves an empty one out). */
interface Picked {
  people: string[];
  albums: string[];
  tags: string[];
}

function picked(picks: LibraryPicks): Picked {
  return { people: picks.people ?? [], albums: picks.albums ?? [], tags: picks.tags ?? [] };
}
type Limit = (typeof LIMITS)[number];
/** Over this many albums, a field finds one by name. */
const ALBUMS_BEFORE_SEARCH = 12;

/** A library's own hints ("The address you open Immich at."), in the page's language. */
function addressHint(kind: LibraryKind | undefined): string | null {
  if (!kind?.address_hint) return null;
  return tPlugin("screensaver", `libraries.${kind.kind}.address_hint`, kind.address_hint);
}

function keyHelp(kind: LibraryKind | undefined): string | null {
  if (!kind?.key_help) return null;
  return tPlugin("screensaver", `libraries.${kind.kind}.key_help`, kind.key_help);
}

/**
 * One panel for a photo library (UX §4 "Photo Libraries", ADR 0036), with two openings: **Add a
 * Library**, which connects one (its kind, its address, its key, the home-network switch), and a
 * library's row, which opens on what it shows. Connecting turns the panel into the library's own
 * page, so the family picks what to show at once.
 */
export function LibraryPanel({
  opening,
  onOpen,
  onClose,
}: {
  opening: LibraryOpening | null;
  onOpen: (opening: LibraryOpening) => void;
  onClose: () => void;
}) {
  const t = useT();
  const { data: libraries = [] } = useLibraries({ enabled: opening !== null });
  const { data: kinds = [] } = useLibraryKinds({ enabled: opening !== null });
  const library =
    opening?.page === "library" ? libraries.find((each) => each.id === opening.id) : undefined;
  const title =
    opening?.page === "library"
      ? (library?.name ?? t("photos.library.title"))
      : t("photos.library.add.title");
  return (
    <SidePanel
      open={opening !== null}
      title={title}
      onClose={onClose}
      scrollKey={opening?.page === "library" ? opening.id : "add"}
    >
      {opening?.page === "add" ? (
        <AddLibrary
          kinds={kinds}
          onConnected={(added) => {
            onOpen({ page: "library", id: added.id });
          }}
        />
      ) : library ? (
        <LibraryPage
          key={library.id}
          library={library}
          kind={kinds.find((kind) => kind.kind === library.kind)}
          onRemoved={onClose}
        />
      ) : null}
    </SidePanel>
  );
}

/** Connecting: the kind (Immich alone today), the address, the key and the home network. */
function AddLibrary({
  kinds,
  onConnected,
}: {
  kinds: LibraryKind[];
  onConnected: (library: PhotoLibrary) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { addLibrary } = usePhotoChanges();
  const [chosen, setChosen] = useState<string | null>(null);
  const kind = kinds.find((each) => each.kind === chosen) ?? kinds[0];
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  // Until it's touched, the switch follows the address: on for one that looks like home.
  const [home, setHome] = useState<boolean | null>(null);
  const ticked = home ?? isHomeAddress(url);
  const ready = Boolean(kind && url.trim() && key.trim());
  return (
    <form
      className={`flex flex-col ${display ? "gap-6" : "gap-5"}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || !kind) return;
        addLibrary.mutate(
          { kind: kind.kind, url: url.trim(), api_key: key.trim(), allow_private: ticked },
          { onSuccess: onConnected },
        );
      }}
    >
      <Field label={t("photos.library.kind.label")}>
        {/* A row, so the next kind of library is a chip, not a redesign. */}
        <ChipRow label={t("photos.library.kind.label")}>
          {kinds.map((each) => (
            <Chip
              key={each.kind}
              on={each.kind === kind?.kind}
              onClick={() => {
                setChosen(each.kind);
              }}
            >
              {each.name}
            </Chip>
          ))}
        </ChipRow>
      </Field>
      <TextField
        label={t("photos.library.address.label")}
        placeholder={kind?.placeholder}
        hint={addressHint(kind)}
        autoCapitalize="none"
        autoComplete="off"
        {...(display ? {} : { inputMode: "url" as const })}
        value={url}
        onChange={(event) => {
          setUrl(event.target.value);
        }}
      />
      <TextField
        label={t("photos.library.key.label")}
        type="password"
        layout="password"
        autoComplete="off"
        hint={keyHelp(kind)}
        value={key}
        onChange={(event) => {
          setKey(event.target.value);
        }}
        error={addLibrary.isError ? errorMessage(addLibrary.error) : null}
      />
      <Switch
        label={t("photos.library.home.label")}
        hint={
          kind
            ? t("photos.library.home.hint", { name: kind.name })
            : t("photos.library.home.hint_any")
        }
        checked={ticked}
        onChange={setHome}
      />
      <PanelActions>
        <Button type="submit" block pending={addLibrary.isPending} disabled={!ready}>
          {addLibrary.isPending
            ? t("photos.library.connecting.action")
            : t("photos.library.connect.action")}
        </Button>
      </PanelActions>
    </form>
  );
}

/** A connected library: how it's doing, what it shows, how many, and the rest. */
function LibraryPage({
  library,
  kind,
  onRemoved,
}: {
  library: PhotoLibrary;
  kind: LibraryKind | undefined;
  onRemoved: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const text = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const kindName = kind?.name ?? library.name;
  const changes = usePhotoChanges();
  const { data: choices } = useLibraryChoices(library.id);
  const { saved, flash } = useSavedFlash();
  // What's picked, as tapped: each tap saves the whole set (ADR 0029, settings save themselves).
  const [picks, setPicks] = useState<Picked>(() => picked(library.picks));
  const [asking, setAsking] = useState(false);
  const save = (change: Parameters<typeof changes.patchLibrary.mutate>[0]["change"]) => {
    changes.patchLibrary.mutate({ id: library.id, change }, { onSuccess: flash });
  };
  const toggle = (group: keyof Picked, id: string) => {
    const now = picks[group].includes(id)
      ? picks[group].filter((each) => each !== id)
      : [...picks[group], id];
    const next = { ...picks, [group]: now };
    setPicks(next);
    save({ picks: next });
  };
  const line = libraryLine(library);
  const needsKey = library.status === "needs_reconnect";
  return (
    <div className={`flex flex-col ${display ? "gap-8" : "gap-6"}`}>
      <div className="flex flex-col gap-1">
        {library.status === "connected" ? (
          <p className={`${text} font-semibold`}>{connectedLine(library, kindName)}</p>
        ) : null}
        <p
          role={line.trouble ? "status" : undefined}
          className={
            line.trouble
              ? `${display ? "text-d-secondary" : "text-secondary"} font-semibold text-alert`
              : soft
          }
        >
          {line.text}
        </p>
      </div>
      {needsKey ? <ConnectAgain library={library} kind={kind} /> : null}
      <section aria-labelledby={`${library.id}-show`} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3
            id={`${library.id}-show`}
            className={display ? "text-d-body font-bold" : "text-row font-bold"}
          >
            {t("photos.library.show.title")}
          </h3>
          <SavedMark show={saved} />
        </div>
        <p className={text}>{picksSentence(picks, choices, library.limit)}</p>
        <Faces
          libraryId={library.id}
          people={choices?.people ?? []}
          unnamed={choices?.unnamed_people ?? 0}
          kindName={kindName}
          chosen={picks.people}
          onToggle={(id) => {
            toggle("people", id);
          }}
        />
        <Chips
          label={t("photos.library.albums.label")}
          empty={t("photos.library.albums.empty", { name: kindName })}
          choices={choices?.albums ?? []}
          chosen={picks.albums}
          search
          onToggle={(id) => {
            toggle("albums", id);
          }}
        />
        <Chips
          label={t("photos.library.tags.label")}
          empty={t("photos.library.tags.empty", { name: kindName })}
          choices={choices?.tags ?? []}
          chosen={picks.tags}
          onToggle={(id) => {
            toggle("tags", id);
          }}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="quiet"
            pending={changes.refreshChoices.isPending}
            onClick={() => {
              changes.refreshChoices.mutate(library.id);
            }}
          >
            <RefreshCw aria-hidden="true" className={display ? "size-6" : "size-5"} />
            {t("photos.library.refresh.action")}
          </Button>
          {choices?.fetched_at ? (
            <span className={soft}>
              {t("photos.library.choices_from", { time: formatTime(new Date(choices.fetched_at)) })}
            </span>
          ) : null}
        </div>
        {changes.refreshChoices.isError ? (
          <p role="alert" className="font-semibold text-alert">
            {errorMessage(changes.refreshChoices.error)}
          </p>
        ) : null}
      </section>
      <Field label={t("photos.library.limit.label")} hint={t("photos.library.limit.hint")}>
        <Segmented
          label={t("photos.library.limit.label")}
          value={String(library.limit)}
          options={LIMITS.map((limit) => ({ value: String(limit), label: count(limit) }))}
          onChange={(value) => {
            save({ limit: Number(value) as Limit });
          }}
        />
      </Field>
      <Switch
        label={t("photos.library.enabled.label")}
        hint={t("photos.library.enabled.hint")}
        checked={library.enabled}
        onChange={(enabled) => {
          save({ enabled });
        }}
      />
      <div>
        <Button
          variant="secondary"
          disabled={!library.enabled || library.checking}
          pending={changes.checkLibrary.isPending}
          onClick={() => {
            changes.checkLibrary.mutate(library);
          }}
        >
          {t("photos.check_now.action")}
        </Button>
      </div>
      {changes.patchLibrary.isError || changes.checkLibrary.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(changes.patchLibrary.error ?? changes.checkLibrary.error)}
        </p>
      ) : null}
      {asking ? (
        <div className="flex flex-col gap-3 rounded-button border-2 border-line p-4">
          <p className={`${text} font-semibold`}>
            {t("photos.library.remove.ask", {
              name: library.name,
              n: library.photo_count,
              kind: kindName,
            })}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="danger"
              pending={changes.removeLibrary.isPending}
              onClick={() => {
                changes.removeLibrary.mutate(library, { onSuccess: onRemoved });
              }}
            >
              {t("photos.library.remove.action", { name: library.name })}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setAsking(false);
              }}
            >
              {t("photos.library.keep.action")}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          block
          variant="quiet-danger"
          onClick={() => {
            setAsking(true);
          }}
        >
          {t("photos.library.remove_library.action")}
        </Button>
      )}
    </div>
  );
}

/** A library that needs its key again: the key (and, opened on request, a new address). */
function ConnectAgain({ library, kind }: { library: PhotoLibrary; kind: LibraryKind | undefined }) {
  const t = useT();
  const display = useShell() === "display";
  const { reconnectLibrary } = usePhotoChanges();
  const [key, setKey] = useState("");
  const [moving, setMoving] = useState(false);
  const [url, setUrl] = useState(library.url);
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!key.trim()) return;
        reconnectLibrary.mutate({
          id: library.id,
          apiKey: key.trim(),
          ...(moving && url.trim() ? { url: url.trim() } : {}),
        });
      }}
    >
      {moving ? (
        <TextField
          label={t("photos.library.address.label")}
          placeholder={kind?.placeholder}
          autoCapitalize="none"
          autoComplete="off"
          {...(display ? {} : { inputMode: "url" as const })}
          value={url}
          onChange={(event) => {
            setUrl(event.target.value);
          }}
        />
      ) : (
        <div>
          <Chip
            opener
            expanded={false}
            onClick={() => {
              setMoving(true);
            }}
          >
            {t("photos.library.change_address.action")}
          </Chip>
        </div>
      )}
      <TextField
        label={t("photos.library.key.label")}
        type="password"
        layout="password"
        autoComplete="off"
        hint={keyHelp(kind)}
        value={key}
        onChange={(event) => {
          setKey(event.target.value);
        }}
        error={reconnectLibrary.isError ? errorMessage(reconnectLibrary.error) : null}
      />
      <div>
        <Button type="submit" disabled={!key.trim()} pending={reconnectLibrary.isPending}>
          {t("photos.library.connect_again.action")}
        </Button>
      </div>
    </form>
  );
}

/**
 * The library's named people as faces with their names under them, wrapping (a family's library
 * can know thirty), ringed when chosen as the Who picker rings its people. A face Sunroom can't
 * fetch is the person's initial in a neutral circle.
 */
function Faces({
  libraryId,
  people,
  unnamed,
  kindName,
  chosen,
  onToggle,
}: {
  libraryId: string;
  people: LibraryChoice[];
  unnamed: number;
  kindName: string;
  chosen: readonly string[];
  onToggle: (id: string) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const hint = display ? "text-d-caption text-ink-soft" : "text-caption text-ink-soft";
  return (
    <Field label={t("photos.library.people.label")}>
      {people.length ? (
        <div
          role="group"
          aria-label={t("photos.library.people.label")}
          className="flex flex-wrap gap-2"
        >
          {people.map((person) => (
            <button
              key={person.id}
              type="button"
              aria-pressed={chosen.includes(person.id)}
              aria-label={person.name}
              onClick={() => {
                onToggle(person.id);
              }}
              className={`press select-fill flex flex-col items-center gap-1 rounded-button px-1 aria-pressed:bg-p-tint aria-pressed:ring-[3px] aria-pressed:ring-ink aria-pressed:ring-inset ${
                display ? "w-24 py-2" : "w-16 py-1"
              }`}
            >
              <Face libraryId={libraryId} person={person} />
              <span
                className={`w-full truncate text-center font-semibold ${display ? "text-d-caption" : "text-caption"}`}
              >
                {person.name}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className={hint}>{t("photos.library.people.empty", { name: kindName })}</p>
      )}
      {unnamed ? (
        <p className={hint}>{t("photos.library.people.unnamed", { n: unnamed })}</p>
      ) : null}
    </Field>
  );
}

function Face({ libraryId, person }: { libraryId: string; person: LibraryChoice }) {
  const display = useShell() === "display";
  const [failed, setFailed] = useState(false);
  const size = display ? "size-16 text-d-body" : "size-12 text-body";
  if (!person.has_thumb || failed) {
    return (
      <span
        aria-hidden="true"
        className={`inline-flex ${size} items-center justify-center rounded-full border-2 border-line bg-wall font-bold text-ink-soft`}
      >
        {person.name.trim().charAt(0).toUpperCase() || "?"}
      </span>
    );
  }
  return (
    <img
      alt=""
      src={`/api/screensaver/libraries/${libraryId}/thumb?person=${encodeURIComponent(person.id)}`}
      onError={() => {
        setFailed(true);
      }}
      className={`${size} rounded-full bg-line object-cover`}
    />
  );
}

/** Albums or tags as chips that wrap, the chosen ones first, with a count when the library
 * gives one; over a dozen albums, a field finds one by name. */
function Chips({
  label,
  empty,
  choices,
  chosen,
  search = false,
  onToggle,
}: {
  label: string;
  empty: string;
  choices: LibraryChoice[];
  chosen: readonly string[];
  search?: boolean;
  onToggle: (id: string) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const [query, setQuery] = useState("");
  const typed = useDebounced(query, 200).trim().toLowerCase();
  const finding = search && choices.length > ALBUMS_BEFORE_SEARCH;
  const shown = [
    ...choices.filter((choice) => chosen.includes(choice.id)),
    ...choices.filter(
      (choice) =>
        !chosen.includes(choice.id) && (!typed || choice.name.toLowerCase().includes(typed)),
    ),
  ];
  return (
    <Field label={label}>
      {finding ? (
        <div className="relative">
          <TextField
            label={t("photos.library.find_album.label")}
            hideLabel
            placeholder={t("photos.library.find_album.label")}
            autoComplete="off"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
          <Search
            aria-hidden="true"
            className={`pointer-events-none absolute top-1/2 right-4 -translate-y-1/2 text-ink-soft ${
              display ? "size-7" : "size-5"
            }`}
          />
        </div>
      ) : null}
      {choices.length ? (
        <ChipRow label={label}>
          {shown.map((choice) => (
            <Chip
              key={choice.id}
              on={chosen.includes(choice.id)}
              onClick={() => {
                onToggle(choice.id);
              }}
            >
              {choice.count !== null ? `${choice.name} · ${count(choice.count)}` : choice.name}
            </Chip>
          ))}
        </ChipRow>
      ) : (
        <p className={display ? "text-d-caption text-ink-soft" : "text-caption text-ink-soft"}>
          {empty}
        </p>
      )}
    </Field>
  );
}
