import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import {
  addDays,
  formatClock,
  formatWallTime,
  longWeekday,
  monthDay,
  wallNow,
  zonedParts,
} from "../../lib/dates";
import { backToNow, idleHolds } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { swallowFollowingClick, whenIdle } from "../../lib/idle";
import { useMinute } from "../../lib/time";
import { kioskCommands } from "../../shell/kioskCommands";
import { Digits } from "../../ui/Digits";
import { useOccurrences } from "../calendar/data";
import { peopleOf } from "../calendar/EventChip";
import { todayParts } from "../calendar/layout";
import { useSaverCorners } from "../usePluginModules";
import { useManifest, type Manifest, type SaverPhoto } from "./data";
import { saverStarts } from "./start";

/** Away this long, a tap goes back to this week's board instead of where the wall was. */
const LONG_AWAY_MS = 30 * 60_000;
const OUT_MS = 220;

function inOrder(photos: SaverPhoto[], shuffle: boolean): SaverPhoto[] {
  if (!shuffle) return photos;
  const out = [...photos];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const [a, b] = [out[i], out[j]];
    if (a && b) [out[i], out[j]] = [b, a];
  }
  return out;
}

/**
 * The screensaver (UX §4 "Screensaver", §6 "Screensaver in and out"): when nobody has touched the
 * wall for the set minutes, the household's photos fade in, uncropped on the wall's tint, with
 * the clock, the date and Up next on a band along the bottom. Night wins over it, and so does
 * anything holding the screen (a routine being run). Any tap fades it out to where the wall was,
 * or to this week's board after half an hour (in the room it was in, with Return to the calendar
 * after on Never); the waking tap presses nothing else.
 */
export function Saver({ asleep, home }: { asleep: boolean; home: "/display" | "/" }) {
  const { data: manifest } = useManifest();
  const minutes = manifest?.settings.start_after_minutes ?? null;
  const [since, setSince] = useState<number | null>(null);

  useEffect(() => {
    if (asleep || since !== null || minutes === null) return;
    return whenIdle(minutes * 60_000, () => {
      if (idleHolds.get() > 0 || document.querySelector("dialog[open]")) return;
      setSince(Date.now());
    });
  }, [asleep, since, minutes]);

  // Start screensaver: the Photos room's button, or a parent's phone.
  useEffect(() => {
    const unsubscribe = saverStarts.subscribe(() => {
      setSince(Date.now());
    });
    const unsubscribeCommands = kioskCommands.subscribe(() => {
      if (kioskCommands.get()?.command === "screensaver") setSince(Date.now());
    });
    return () => {
      unsubscribe();
      unsubscribeCommands();
    };
  }, []);

  if (since === null || asleep || !manifest) return null;
  return (
    <SaverScreen
      key={since}
      manifest={manifest}
      since={since}
      home={home}
      onGone={() => {
        setSince(null);
      }}
    />
  );
}

function SaverScreen({
  manifest,
  since,
  home,
  onGone,
}: {
  manifest: Manifest;
  since: number;
  home: "/display" | "/";
  onGone: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  // Return to the calendar after: Never keeps the room the wall was in, even after half an hour
  // (ADR 0034); the board itself still comes back to now.
  const { data: household } = useSettings();
  const returns = (household?.display_return_minutes ?? 5) > 0;
  const { settings } = manifest;
  const [photos] = useState(() => inOrder(manifest.photos, settings.shuffle));
  const [index, setIndex] = useState(0);
  // The photo underneath goes once the new one has faded in (a narrower one would show it at
  // its sides).
  const [settled, setSettled] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const shown = photos.length ? photos[index % photos.length] : undefined;
  const before =
    photos.length > 1 ? photos[(index - 1 + photos.length) % photos.length] : undefined;

  // The next photo every so often, once it has loaded (a crossfade never shows a gap).
  useEffect(() => {
    if (photos.length < 2) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      const next = photos[(index + 1) % photos.length];
      if (!next) return;
      const image = new Image();
      image.src = next.url;
      void image
        .decode()
        .catch(() => undefined)
        .then(() => {
          if (!cancelled) setIndex((n) => n + 1);
        });
    }, settings.every_seconds * 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [photos, index, settings.every_seconds]);

  const wake = () => {
    if (leaving) return;
    swallowFollowingClick();
    setLeaving(true);
    if (Date.now() - since >= LONG_AWAY_MS) {
      backToNow();
      if (returns) void navigate({ to: home });
    }
    setTimeout(onGone, OUT_MS);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={t("photos.saver.aria")}
      data-saver=""
      onPointerDown={(event) => {
        event.preventDefault();
        wake();
      }}
      onKeyDown={wake}
      className={`fixed inset-0 z-[57] cursor-pointer overflow-hidden bg-wall ${
        leaving ? "saver-out" : "saver-in"
      }`}
    >
      {before && index > 0 && settled !== index ? (
        <img
          key={`under-${before.id}-${String(index)}`}
          src={before.url}
          alt=""
          className="absolute inset-0 size-full object-contain"
        />
      ) : null}
      {shown ? (
        <img
          key={`${shown.id}-${String(index)}`}
          src={shown.url}
          alt=""
          className={`absolute inset-0 size-full object-contain ${index > 0 ? "saver-photo-in" : ""}`}
          onAnimationEnd={() => {
            setSettled(index);
          }}
        />
      ) : null}
      {settings.show_clock || !shown ? <Band onPhoto={Boolean(shown)} /> : null}
    </div>
  );
}

/** The clock, the date and Up next, along the bottom (on a dark wash when over a photo). */
function Band({ onPhoto }: { onPhoto: boolean }) {
  const t = useT();
  const minute = useMinute();
  const now = wallNow(minute);
  const { day } = zonedParts(minute);
  const corners = useSaverCorners();
  const { data } = useOccurrences(day, addDays(day, 1));
  const { data: members = [] } = useMembers();
  const next = todayParts(data?.occurrences ?? [], now).upNext;
  const people = next ? peopleOf(next, members) : [];
  const soft = onPhoto ? "text-saver-ink" : "text-ink-soft";
  return (
    <div
      className={`saver-band-in absolute inset-x-0 bottom-0 flex items-end justify-between gap-12 px-16 pt-40 pb-12 ${
        onPhoto
          ? "bg-linear-to-t from-saver-shade/70 via-saver-shade/45 to-transparent text-saver-ink"
          : "text-ink"
      }`}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <p className="text-wall-clock leading-none font-bold">
          <Digits value={formatClock(minute)} />
        </p>
        <p className="flex flex-wrap items-center gap-x-4 text-d-glance font-semibold">
          <span>
            {longWeekday(day)}, {monthDay(day)}
          </span>
          {corners.map((Corner, index) => (
            <Corner key={index} />
          ))}
        </p>
        {!onPhoto ? <p className={`text-d-body ${soft}`}>{t("photos.saver.empty")}</p> : null}
      </div>
      {next ? (
        <div className="flex max-w-[40%] min-w-0 flex-col items-end gap-1 text-right">
          <p className={`text-d-secondary font-semibold ${soft}`}>{t("photos.saver.up_next")}</p>
          <p className="text-d-glance font-bold">
            {next.start_local
              ? t("photos.saver.next_at", {
                  time: formatWallTime(next.start_local),
                  title: next.title,
                })
              : t("photos.saver.next_all_day", { title: next.title })}
          </p>
          {people.length ? (
            <p className="text-d-body font-semibold">{people.map((p) => p.name).join(", ")}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
