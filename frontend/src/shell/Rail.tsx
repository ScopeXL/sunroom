import { Link } from "@tanstack/react-router";
import { CalendarDays, Lock, Plus, Settings, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { useT, type Key } from "../lib/lang";

import { SunMark } from "../ui/SunMark";

export interface RailRoom {
  key: string;
  label: Key;
  icon: LucideIcon;
}

const ROOM_LINK =
  "press-row flex flex-col items-center justify-center text-d-secondary font-semibold text-ink-soft aria-[current=page]:bg-wall aria-[current=page]:text-ink portrait:h-24 landscape:min-h-0 landscape:flex-1";
// A room is 6rem tall, and gives way down to a tap target when the screen is short (Extra large
// text, a laptop), so Add and Settings always stay on screen. Folded, it's a 4.5rem square.
const ROOM_ITEM =
  "rail-room portrait:max-w-40 portrait:min-w-0 portrait:flex-1 landscape:flex landscape:min-h-tap landscape:flex-col";
// A name under an icon. It stays in the page when the rail folds, so a room keeps its name for
// a screen reader and the word can fade as the rail closes: no height, no ink (styles/motion.css).
const WORD = "rail-word mt-1 max-h-8 whitespace-nowrap";
const WORD_FOLDED =
  "landscape:mt-0 landscape:max-h-0 landscape:overflow-hidden landscape:opacity-0";

/**
 * The display's rail (UX §3, ADR 0030): the Sunroom mark alone in a block as tall as the header,
 * the Calendar room then each enabled plugin's (Lists, Tasks…), Add, and Settings as one row
 * that lines up with the tips strip: a gear, or a padlock while Settings are locked behind the
 * PIN on a paired screen. `compact` folds it to its icons (never away): every room, Add and
 * Settings stay one tap off. Hide the rail and Show the rail are in the header (shell/Header),
 * across from the Today panel's button. In portrait it's the bottom bar, always with its words.
 */
export function Rail({
  home,
  room,
  rooms,
  lock,
  compact,
  side,
  settled,
  onAdd,
  onLock,
}: {
  home: "/display" | "/";
  room: string;
  /** The plugins' rooms, in their order (the Calendar room comes first, always). */
  rooms: RailRoom[];
  /** locked: behind the PIN; unlocked: a PIN grant is open; open: no PIN is set. */
  lock: "locked" | "unlocked" | "open";
  /** Only the icons (landscape; the bottom bar keeps its words). */
  compact: boolean;
  /** Which side of the screen it's on: its rule faces the board. */
  side: "left" | "right";
  /** The household's settings have arrived: from the next frame on, a fold may animate. */
  settled: boolean;
  onAdd: () => void;
  onLock: () => void;
}) {
  // Never on first paint: a rail that starts folded is simply drawn folded (UX §1).
  const [moves, setMoves] = useState(false);
  useEffect(() => {
    if (!settled) return;
    const frame = requestAnimationFrame(() => {
      setMoves(true);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [settled]);

  const t = useT();
  const word = compact ? `${WORD} ${WORD_FOLDED}` : WORD;
  const item = `${ROOM_ITEM} ${compact ? "landscape:flex-[0_1_4.5rem]" : "landscape:flex-[0_1_6rem]"}`;
  return (
    <nav
      aria-label={t("shell.rail.aria")}
      data-segmented=""
      data-rail-motion={moves ? "" : undefined}
      className={`flex flex-col bg-surface landscape:h-full landscape:w-[var(--rail-w)] landscape:overflow-clip landscape:border-line portrait:h-28 portrait:flex-row portrait:items-center portrait:border-t portrait:border-line ${
        side === "right" ? "landscape:border-l" : "landscape:border-r"
      }`}
    >
      {/* As tall as the header, with the same rule under it, so the two rules meet. */}
      <div className="flex h-[var(--header-h)] shrink-0 items-center justify-center border-b border-line portrait:hidden">
        <SunMark className="size-12" />
      </div>
      <ul className="flex flex-col landscape:min-h-0 portrait:flex-1 portrait:flex-row">
        <li className={item}>
          <Link
            to={home}
            aria-current={room === "calendar" ? "page" : undefined}
            className={ROOM_LINK}
          >
            <CalendarDays aria-hidden="true" className="size-9 shrink-0" strokeWidth={2} />
            <span className={word}>{t("calendar.room.title")}</span>
          </Link>
        </li>
        {rooms.map(({ key, label, icon: Icon }) => (
          <li key={key} className={item}>
            <Link
              to="/$room"
              params={{ room: key }}
              aria-current={room === key ? "page" : undefined}
              className={ROOM_LINK}
            >
              <Icon aria-hidden="true" className="size-9 shrink-0" strokeWidth={2} />
              <span className={word}>{t(label)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <div className="flex-1 portrait:hidden" />
      <div
        className={`flex justify-center portrait:px-6 portrait:py-4 ${compact ? "landscape:py-3" : "landscape:py-4"}`}
      >
        <button
          type="button"
          onClick={onAdd}
          className="press flex flex-col items-center text-d-caption font-semibold"
        >
          {/* Folded, the circle is the size of a room's icon cell: a tap target, no more. */}
          <span
            className={`rail-add flex items-center justify-center rounded-full bg-ink text-wall portrait:size-16 ${
              compact ? "landscape:size-tap" : "landscape:size-16"
            }`}
          >
            <Plus
              aria-hidden="true"
              className={`portrait:size-9 ${compact ? "landscape:size-8" : "landscape:size-9"}`}
              strokeWidth={2.5}
            />
          </span>
          <span className={word}>{t("shell.add.action")}</span>
        </button>
      </div>
      {/* One row, the height of the tips strip beside it, under the same kind of rule. */}
      <button
        type="button"
        onClick={onLock}
        aria-label={lock === "unlocked" ? t("shell.rail.unlocked.aria") : t("settings.title")}
        aria-current={room === "settings" ? "page" : undefined}
        data-icon={lock === "locked" ? "lock" : "gear"}
        className="press-row flex shrink-0 items-center justify-center font-semibold text-ink-soft aria-[current=page]:bg-wall aria-[current=page]:text-ink landscape:h-tap landscape:border-t landscape:border-line landscape:px-3 landscape:text-d-secondary portrait:h-24 portrait:w-32 portrait:flex-col portrait:gap-1 portrait:text-d-caption"
      >
        {lock === "locked" ? (
          <Lock aria-hidden="true" className="shrink-0 landscape:size-8 portrait:size-9" />
        ) : (
          <Settings aria-hidden="true" className="shrink-0 landscape:size-8 portrait:size-9" />
        )}
        <span
          aria-hidden="true"
          className={`rail-word-beside whitespace-nowrap ${
            compact
              ? "landscape:max-w-0 landscape:overflow-hidden landscape:opacity-0"
              : "landscape:ml-2 landscape:max-w-32"
          }`}
        >
          {lock === "unlocked" ? t("shell.rail.unlocked") : t("settings.title")}
        </span>
      </button>
    </nav>
  );
}
