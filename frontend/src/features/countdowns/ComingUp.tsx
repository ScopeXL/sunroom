import { useNavigate } from "@tanstack/react-router";
import { CalendarPlus } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { zonedParts } from "../../lib/dates";
import { updateDisplay } from "../../lib/displayState";
import { useMembers, type Member } from "../../lib/household";
import { lastActivity } from "../../lib/idle";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { celebrate } from "../../ui/Celebration";
import { useShell } from "../../ui/shell";
import type { Occurrence } from "../calendar/types";
import { useComingUp, type Upcoming } from "./data";
import { comingUpText } from "./words";

const SHOWN = 3;

function remembered(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}

function remember(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // A screen that can't keep it may cheer twice; nothing worse.
  }
}

/**
 * The day itself (UX §4 "Countdowns room"): the first time the wall is touched that day, the big
 * celebration plays once, in the person's color.
 */
function useDayCelebration(items: Upcoming[], members: Member[], today: string) {
  const anchor = useRef<HTMLElement>(null);
  const todays = useMemo(() => items.filter((item) => item.days === 0), [items]);
  useEffect(() => {
    if (!todays.length) return;
    return lastActivity.subscribe(() => {
      const due = todays.filter((item) => !remembered(`sunroom.cheered.${item.key}.${today}`));
      const first = due[0];
      if (!first) return;
      for (const item of due) remember(`sunroom.cheered.${item.key}.${today}`);
      const person = members.find((m) => m.id === first.member_id);
      celebrate(
        anchor.current ?? document.body,
        first.color ?? person?.color ?? "everyone",
        "full",
      );
    });
  }, [todays, members, today]);
  return anchor;
}

/** The Today panel's Coming up (UX §3): the nearest three (one in portrait's band); on the day,
 * "Today: Mia's birthday!". */
export function ComingUpWall({ band = false }: { band?: boolean }) {
  const t = useT();
  const today = zonedParts(useMinute()).day;
  const { data } = useComingUp(band ? 1 : SHOWN);
  const { data: members = [] } = useMembers();
  const navigate = useNavigate();
  const items = data?.items ?? [];
  const anchor = useDayCelebration(items, members, today);
  if (!items.length) return null;
  return (
    <section ref={anchor} aria-labelledby="today-coming-up" className="flex flex-col gap-2">
      <h2 id="today-coming-up" className="text-d-body font-bold text-ink-soft">
        {t("countdowns.coming_up.title")}
      </h2>
      {items.map((item) => {
        const person = members.find((m) => m.id === item.member_id) ?? null;
        return (
          <button
            key={item.key}
            type="button"
            data-person={item.color ?? person?.color ?? "everyone"}
            onClick={() => {
              void navigate({ to: "/$room", params: { room: "countdowns" } });
            }}
            className="press-row -mx-3 flex min-h-16 items-center gap-3 rounded-chip-d px-3 py-2 text-left"
          >
            {item.emoji ? (
              <span aria-hidden="true" className="w-8 text-center text-d-title">
                {item.emoji}
              </span>
            ) : (
              <Avatar member={person} size="sm" />
            )}
            <span
              className={`flex-1 break-words ${item.days === 0 ? "text-d-glance font-bold" : "text-d-body font-semibold"}`}
            >
              {comingUpText(item.title, item.days)}
            </span>
          </button>
        );
      })}
    </section>
  );
}

/** Today on a phone: the same three. */
export function ComingUpPhone() {
  const t = useT();
  const { data } = useComingUp(SHOWN);
  const items = data?.items ?? [];
  const navigate = useNavigate();
  if (!items.length) return null;
  return (
    <section aria-labelledby="phone-coming-up" className="flex flex-col gap-1">
      <h2 id="phone-coming-up" className="text-row font-bold text-ink-soft">
        {t("countdowns.coming_up.title")}
      </h2>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => {
            void navigate({ to: "/$room", params: { room: "countdowns" } });
          }}
          className={`press-row flex min-h-12 items-center gap-3 rounded-chip px-1 text-left ${
            item.days === 0 ? "text-row font-bold" : "text-body font-semibold"
          }`}
        >
          {item.emoji ? <span aria-hidden="true">{item.emoji}</span> : null}
          <span className="flex-1">{comingUpText(item.title, item.days)}</span>
        </button>
      ))}
    </section>
  );
}

/** "Add a countdown" on an event's sheet (UX §4): Add opens with Countdown, its title and day. */
export function AddCountdownFromEvent({
  occurrence,
  onDone,
}: {
  occurrence: Occurrence;
  onDone: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const day = occurrence.start_date ?? occurrence.start_local?.slice(0, 10) ?? null;
  return (
    <Button
      variant="secondary"
      onClick={() => {
        onDone();
        if (display) {
          updateDisplay({
            panel: { kind: "add", day, hour: null, type: "countdown", title: occurrence.title },
          });
          return;
        }
        void navigate({
          to: "/$room/$",
          params: {
            room: "countdowns",
            _splat: `new/${day ?? ""}/${encodeURIComponent(occurrence.title)}`,
          },
        });
      }}
    >
      <CalendarPlus aria-hidden="true" className={display ? "size-7" : "size-5"} />
      {t("countdowns.from_event.action")}
    </Button>
  );
}
