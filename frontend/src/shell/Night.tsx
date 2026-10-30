import { useEffect, useState } from "react";

import { useOccurrences } from "../features/calendar/data";
import { byDay } from "../features/calendar/layout";
import { addDays, formatClock, formatWallTime, zonedParts } from "../lib/dates";
import { useT } from "../lib/lang";
import { useMinute } from "../lib/time";
import { Digits } from "../ui/Digits";

const LEAVE_AT_MOST_MS = 400;

/**
 * Night (UX §4): the dim clock on black with tomorrow's first event under it, or a black screen
 * when the screen should be off (the Pi helper turns the backlight off in M5). A tap wakes the
 * screen for 2 minutes and does nothing else: this layer takes the touch, and lib/idle drops the
 * click that follows.
 */
export function Night({
  sleeping,
  mode,
  onWake,
}: {
  sleeping: boolean;
  mode: "dim_clock" | "screen_off";
  onWake: () => void;
}) {
  // Waking, the layer fades away over the screen it gives back (UX §9), then goes.
  const [leaving, setLeaving] = useState(false);
  const [was, setWas] = useState(sleeping);
  if (sleeping !== was) {
    setWas(sleeping);
    setLeaving(!sleeping);
  }
  useEffect(() => {
    if (!leaving) return;
    // Its fade's end takes it away; this is for a browser that never says the fade ended.
    const timer = setTimeout(() => {
      setLeaving(false);
    }, LEAVE_AT_MOST_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [leaving]);
  if (!sleeping && !leaving) return null;
  return (
    <NightLayer
      mode={mode}
      leaving={!sleeping}
      onWake={onWake}
      onGone={() => {
        setLeaving(false);
      }}
    />
  );
}

function NightLayer({
  mode,
  leaving,
  onWake,
  onGone,
}: {
  mode: "dim_clock" | "screen_off";
  leaving: boolean;
  onWake: () => void;
  onGone: () => void;
}) {
  const now = useMinute();
  const { day, hour } = zonedParts(now);
  // Before dawn, "tomorrow" is today: what the morning starts with.
  const next = hour < 5 ? day : addDays(day, 1);
  const { data } = useOccurrences(next, addDays(next, 1), { enabled: mode === "dim_clock" });
  const column = byDay(data?.occurrences ?? [], [next]).get(next);
  const first = column?.timed[0]?.occurrence ?? column?.allDay[0]?.occurrence;
  const t = useT();
  const when = first && !first.all_day && first.start_local ? first.start_local : null;
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={t("shell.night.aria")}
      onPointerDown={(event) => {
        event.preventDefault();
        onWake();
      }}
      onKeyDown={onWake}
      onAnimationEnd={(event) => {
        if (leaving && event.target === event.currentTarget) onGone();
      }}
      className={`fixed inset-0 z-[60] flex cursor-pointer flex-col items-center justify-center gap-6 bg-night text-night-ink ${
        leaving ? "night-out pointer-events-none" : "night-in"
      }`}
    >
      {mode === "dim_clock" ? (
        <>
          <p className="text-wall-clock font-bold opacity-35">
            <Digits value={formatClock(now)} />
          </p>
          {first ? (
            <p className="max-w-[60rem] text-center text-d-glance font-semibold opacity-35">
              {when
                ? t("shell.night.timed", {
                    day: hour < 5 ? "today" : "tomorrow",
                    time: formatWallTime(when),
                    title: first.title,
                  })
                : t("shell.night.all_day", {
                    day: hour < 5 ? "today" : "tomorrow",
                    title: first.title,
                  })}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
