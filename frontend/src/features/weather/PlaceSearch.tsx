import { MapPin } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { errorMessage } from "../../api/client";
import { useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useDebounced } from "../../lib/useDebounced";
import { Button } from "../../ui/Button";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { Group, Text } from "../settings/parts";
import { usePlaces, useSetPlace, type Place } from "./data";

/**
 * Find the household's city by name and pick it (Open-Meteo's place search, ADR 0030). The field
 * searches as you type, 350 ms after the last key and from two letters, and lists what it found
 * under itself: in the page's flow, never a floating list, because the wall's keyboard and a
 * phone's sheet both need the page to make room for it. On a laptop the arrow keys walk the
 * list from the field.
 */
function PlaceSearch({
  onPicked,
  focus = false,
}: {
  onPicked: (place: Place) => void;
  focus?: boolean;
}) {
  const t = useT();
  const display = useShell() === "display";
  const [words, setWords] = useState("");
  const listId = useId();
  const list = useRef<HTMLUListElement>(null);
  const typed = words.trim();
  const query = useDebounced(typed, 350);
  const { data, isFetching, error } = usePlaces(query);
  const setPlace = useSetPlace();
  const text = display ? "text-d-body" : "text-body";

  // The last answer stays up while the next one is fetched (no blink between keys), but not
  // once the field is too short to search.
  const places = typed.length < 2 ? [] : (data ?? []);
  const searching = typed.length >= 2 && (typed !== query || isFetching);
  const status = error
    ? ""
    : places.length
      ? t("weather.places.count", { n: places.length })
      : searching
        ? t("weather.places.searching")
        : typed.length === 0
          ? ""
          : // Open-Meteo matches two letters exactly and three or more loosely.
            typed.length < 3
            ? t("weather.places.keep_typing")
            : t("weather.places.none");

  const rows = () => Array.from(list.current?.querySelectorAll<HTMLElement>("button") ?? []);
  const move = (event: KeyboardEvent<HTMLElement>, field: HTMLElement | null) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const all = rows();
    if (!all.length) return;
    const at = all.findIndex((row) => row === document.activeElement);
    const to = at + (event.key === "ArrowDown" ? 1 : -1);
    event.preventDefault();
    if (to < 0) field?.focus();
    else all[Math.min(to, all.length - 1)]?.focus();
  };
  const field = useRef<HTMLInputElement>(null);

  return (
    <div className="flex flex-col gap-4">
      <TextField
        ref={field}
        label={t("weather.places.city.label")}
        value={words}
        maxLength={80}
        // The browser's own address suggestions would cover the list.
        autoComplete="off"
        autoFocus={focus}
        aria-controls={listId}
        onChange={(event) => {
          setWords(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") move(event, null);
        }}
      />
      {error && !places.length ? (
        <p role="alert" className={`${text} font-semibold text-alert`}>
          {errorMessage(error)}
        </p>
      ) : null}
      {/* Always here, so a screen reader hears it change; out of the flow once the list shows. */}
      <p
        aria-live="polite"
        className={places.length || !status ? "sr-only" : `${text} text-ink-soft`}
      >
        {status}
      </p>
      <ul
        ref={list}
        id={listId}
        aria-label={t("weather.places.aria")}
        className={places.length ? "flex flex-col gap-2" : "hidden"}
        onKeyDown={(event) => {
          move(event, field.current);
        }}
      >
        {places.map((place) => (
          <li key={`${String(place.latitude)},${String(place.longitude)}`}>
            <button
              type="button"
              onClick={() => {
                setPlace.mutate(place, {
                  onSuccess: () => {
                    onPicked(place);
                  },
                });
              }}
              className={`press-row flex w-full items-center gap-3 rounded-chip border border-line bg-surface px-4 text-left ${
                display ? "min-h-16 text-d-body" : "min-h-12 text-body"
              } font-semibold`}
            >
              <MapPin aria-hidden="true" className="size-6 shrink-0 text-ink-soft" />
              {place.label}
            </button>
          </li>
        ))}
      </ul>
      {setPlace.isError ? (
        <p role="alert" className={`${text} font-semibold text-alert`}>
          {errorMessage(setPlace.error)}
        </p>
      ) : null}
    </div>
  );
}

/** First run's "Where's home?" (PLAN §15 M4): for the weather and the sunset. */
export function PlaceOnboarding({ onDone }: { onDone: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  return (
    <>
      <p className={display ? "text-d-body" : "text-body"}>{t("weather.onboarding.lead")}</p>
      <PlaceSearch onPicked={onDone} />
      <Button variant="quiet" block onClick={onDone}>
        {t("app.action.later")}
      </Button>
    </>
  );
}

/** Settings → Household → Location (UX §4): the city, Change and Remove. */
export function LocationSettings() {
  const t = useT();
  const display = useShell() === "display";
  const { data: settings } = useSettings();
  const setPlace = useSetPlace();
  const [changing, setChanging] = useState(false);
  const label = settings?.location_label ?? null;
  return (
    <Group title={t("weather.location.title")} note={t("weather.location.note")}>
      <div className={`flex flex-col gap-4 ${display ? "py-5" : "py-4"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Text soft={!label}>{label ?? t("weather.location.unset")}</Text>
          <div className="flex gap-3">
            {!changing ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setChanging(true);
                }}
              >
                {label ? t("app.action.change") : t("weather.location.set.action")}
              </Button>
            ) : null}
            {label && !changing ? (
              <Button
                variant="quiet-danger"
                pending={setPlace.isPending}
                onClick={() => {
                  setPlace.mutate(null);
                }}
              >
                {t("app.action.remove")}
              </Button>
            ) : null}
          </div>
        </div>
        {changing ? (
          <PlaceSearch
            focus
            onPicked={() => {
              setChanging(false);
            }}
          />
        ) : null}
      </div>
    </Group>
  );
}
