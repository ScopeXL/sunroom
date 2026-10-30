import { useDroppable } from "@dnd-kit/core";
import { AnimatePresence } from "motion/react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type MouseEvent,
} from "react";

import { useArrived } from "../../lib/arrivals";
import { dayNumber, formatWallTime, longWeekday, shortWeekday } from "../../lib/dates";
import { resting } from "../../lib/displayState";
import type { Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useStore } from "../../lib/store";
import { Leaves } from "../../ui/Leaves";
import { Draggable, MoreButton } from "./Draggable";
import {
  EventChip,
  PeopleMarks,
  arrivalKey,
  chipTone,
  PeopleEdge,
  occurrenceLabel,
  peopleOf,
} from "./EventChip";
import {
  chipTier,
  gridStepMinutes,
  gutterHours,
  initialScrollTop,
  laneStyle,
  maxZoom,
  minutesAtY,
  nowTop,
  pixelsPerHour,
  placeTimed,
  rescaledScrollTop,
  zoomIn,
  zoomOut,
  ZOOM_STEP,
  type ChipBox,
} from "./hours";
import { shownFor, type DayColumn, type DayEntry } from "./layout";
import type { Occurrence } from "./types";
import { ZoomControl } from "./ZoomControl";

const BAND_CHIPS = 3;

export interface HoursGridProps {
  days: string[];
  today: string;
  now: string;
  columns: Map<string, DayColumn<Occurrence>>;
  members: Member[];
  dimPast: boolean;
  people: string[];
  /** 1 fits the whole day; each Zoom in is half again (features/calendar/hours). */
  zoom: number;
  /** Another zoom was asked for: the buttons at the grid's corner (ZoomControl), or their
   * shortcuts (ctrl + wheel, a trackpad pinch). */
  onZoom?: ((zoom: number) => void) | undefined;
  lifted: Occurrence | null;
  lit: string | null;
  /** The plugins' marks for each day's header (its weather). */
  marks: ComponentType<{ day: string }>[];
  onOpen: (occurrence: Occurrence) => void;
  onAdd: (day: string, hour: number, minute: number) => void;
  onMore: (day: string) => void;
}

interface Measure {
  /** What the grid has under the sticky heads. */
  fit: number;
  /** The heads' height, kept clear when a focused chip scrolls into view. */
  head: number;
  /** A day's column. */
  width: number;
  /** The root font size: the Text size setting. */
  rem: number;
}

/**
 * The Week board's Hours layout (UX §4 "Week board, Hours layout", ADR 0028): each day from
 * midnight to midnight, events placed by their time and as tall as they last, the now line
 * creeping down today. Fitting the day (zoom 1) nothing scrolls; zoomed in it scrolls with no
 * scrollbar: the hour cut off at the bottom edge, the hours under a finger and the zoom's
 * buttons say so, and Fit the day always shows the whole day (ADR 0033; the overlay bar flashed
 * once a minute while the grid followed now). Each day's head (its name, then its all-day
 * events) stays on top. A tap on an empty spot adds an event there; a long press lifts a chip to
 * another day.
 */
export function HoursGrid(props: HoursGridProps) {
  const t = useT();
  const { days, today, now, onZoom } = props;
  const scroller = useRef<HTMLDivElement>(null);
  const corner = useRef<HTMLDivElement>(null);
  const [measure, setMeasure] = useState<Measure | null>(null);

  useLayoutEffect(() => {
    const node = scroller.current;
    const head = corner.current;
    if (!node || !head) return;
    const update = () => {
      const column = node.querySelector<HTMLElement>("[data-day-body]");
      const next: Measure = {
        fit: Math.max(0, node.clientHeight - head.offsetHeight),
        head: head.offsetHeight,
        width: column?.clientWidth ?? 0,
        rem: Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16,
      };
      setMeasure((current) =>
        current?.fit === next.fit &&
        current.head === next.head &&
        current.width === next.width &&
        current.rem === next.rem
          ? current
          : next,
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    observer.observe(head);
    return () => {
      observer.disconnect();
    };
  }, []);

  // As far in as this grid goes at this text size; a grid that got shorter (the keyboard, the
  // tips strip) may hold a zoom past its new limit, so it's clamped here, not in the state.
  const max = measure && measure.fit > 0 ? maxZoom(measure.fit, measure.rem) : ZOOM_STEP;
  const zoom = Math.min(props.zoom, max);
  const pph = measure && measure.fit > 0 ? pixelsPerHour(zoom, measure.fit) : 0;

  // Shortcuts for Zoom in and Zoom out: ctrl + wheel, which is also what a
  // trackpad pinch sends. One step per gesture tick, never faster than the eye can follow.
  const zoomRef = useRef({ zoom, max, onZoom });
  useEffect(() => {
    zoomRef.current = { zoom, max, onZoom };
  });
  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    let last = 0;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const state = zoomRef.current;
      if (!state.onZoom || event.timeStamp - last < 150 || event.deltaY === 0) return;
      last = event.timeStamp;
      state.onZoom(event.deltaY < 0 ? zoomIn(state.zoom, state.max) : zoomOut(state.zoom));
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      node.removeEventListener("wheel", onWheel);
    };
  }, []);

  // Fitting the day, the grid never scrolls. Zooming in from there starts at now (or 7 AM on
  // another week); between zooms the minute in the middle of the view stays there. A screen
  // left alone since the board went back to now keeps now in view, minute by minute (ADR 0031).
  const rest = useStore(resting);
  const previous = useRef<{ zoom: number; pph: number } | null>(null);
  useLayoutEffect(() => {
    const node = scroller.current;
    if (!node || !measure || pph <= 0) return;
    const before = previous.current;
    if (rest || !before || before.zoom <= 1 || zoom <= 1) {
      if (rest || before?.zoom !== zoom || before.pph !== pph) {
        node.scrollTop = initialScrollTop({ zoom, pph, fit: measure.fit, now, days });
      }
    } else if (before.pph !== pph) {
      node.scrollTop = rescaledScrollTop(node.scrollTop, measure.fit, before.pph, pph);
    }
    previous.current = { zoom, pph };
  }, [zoom, pph, measure, now, days, rest]);

  const style = {
    "--pph": `${String(pph)}px`,
    "--step": String(gridStepMinutes(pph, measure?.rem)),
    "--grid-h": `${String(24 * pph)}px`,
    scrollPaddingTop: `${String(measure?.head ?? 0)}px`,
  } as CSSProperties;

  return (
    // The zoom floats over the grid's corner, outside the scroller: it never scrolls away.
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scroller}
        data-hours=""
        style={style}
        className="relative min-h-0 flex-1 overflow-y-auto overscroll-y-contain border-t border-line [scrollbar-width:none] [touch-action:pan-y]"
      >
        <div className="grid grid-cols-[6rem_repeat(7,minmax(0,1fr))] grid-rows-[auto_var(--grid-h)]">
          <div className="row-span-2 grid grid-rows-subgrid">
            <div
              ref={corner}
              className="sticky top-0 z-20 flex items-end bg-wall px-3 pb-3 text-d-secondary font-semibold text-ink-soft"
            >
              {t("calendar.board.all_day")}
            </div>
            <div aria-hidden="true" className="relative">
              {pph > 0
                ? gutterHours(pph, measure?.rem).map((hour) => (
                    <span
                      key={hour}
                      className="absolute right-3 -translate-y-1/2 text-d-secondary whitespace-nowrap text-ink-soft"
                      style={{ top: `${String(hour * pph)}px` }}
                    >
                      {formatWallTime(`2026-01-01T${String(hour).padStart(2, "0")}:00:00`, {
                        compact: true,
                      })}
                    </span>
                  ))
                : null}
            </div>
          </div>
          {days.map((day) => (
            <HoursColumn
              key={day}
              {...props}
              day={day}
              isToday={day === today}
              column={props.columns.get(day)}
              pph={pph}
              rem={measure?.rem ?? 16}
              width={measure?.width ?? 0}
            />
          ))}
        </div>
      </div>
      {onZoom ? <ZoomControl zoom={zoom} max={max} onZoom={onZoom} /> : null}
    </div>
  );
}

function HoursColumn({
  day,
  isToday,
  now,
  column,
  members,
  dimPast,
  people,
  zoom,
  lifted,
  lit,
  marks,
  pph,
  rem,
  width,
  onOpen,
  onAdd,
  onMore,
}: HoursGridProps & {
  day: string;
  isToday: boolean;
  column: DayColumn<Occurrence> | undefined;
  pph: number;
  rem: number;
  width: number;
}) {
  const t = useT();
  const { setNodeRef, isOver } = useDroppable({ id: day });
  const filter = new Set(people);
  const allDay = column?.allDay ?? [];
  const timed = column?.timed ?? [];
  const placed =
    pph > 0
      ? placeTimed(
          timed.map((entry) => entry.occurrence),
          day,
          pph,
          rem,
          width,
        )
      : [];
  const entries = new Map(timed.map((entry) => [entry.occurrence.key, entry]));
  const y = pph > 0 ? nowTop(now, day, pph) : null;
  const lighted = isOver || lit === day;

  const add = (event: MouseEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("button, [data-chip]") || pph <= 0) return;
    const at = event.clientY - event.currentTarget.getBoundingClientRect().top;
    const minutes = minutesAtY(at, pph);
    onAdd(day, Math.floor(minutes / 60), minutes % 60);
  };

  return (
    <section
      ref={setNodeRef}
      data-day={day}
      data-today={isToday ? "" : undefined}
      aria-current={isToday ? "date" : undefined}
      // No container here: a container's layout containment would stop it being a subgrid, and
      // the heads and bodies would no longer line up across the days.
      className="row-span-2 grid min-w-0 grid-rows-subgrid border-l border-line"
    >
      {/* Opaque, so the hours slide under it. */}
      <div
        className={`day-column sticky top-0 z-20 flex min-w-0 flex-col ${
          lighted
            ? "bg-[color-mix(in_oklab,var(--color-sun)_15%,var(--color-wall))]"
            : isToday
              ? "bg-lit"
              : "bg-wall"
        }`}
      >
        <h2
          className={`day-head flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 pt-4 pb-3 text-d-title ${
            isToday ? "font-bold" : "font-semibold text-ink-soft"
          }`}
        >
          <span>{shortWeekday(day)}</span>
          {isToday ? (
            <span className="inline-flex h-[1.35em] min-w-[1.35em] shrink-0 items-center justify-center rounded-full bg-sun px-[0.15em] text-on-sun">
              {dayNumber(day)}
            </span>
          ) : (
            <span>{dayNumber(day)}</span>
          )}
          {isToday ? <span className="sr-only">{t("calendar.board.today")}</span> : null}
          {marks.map((Mark, index) => (
            <Mark key={index} day={day} />
          ))}
        </h2>
        {allDay.length ? (
          <div className="flex flex-col gap-2 px-1 pb-2">
            {allDay.slice(0, BAND_CHIPS).map((entry) => (
              <Draggable
                key={entry.occurrence.key}
                entry={entry}
                day={day}
                faded={!shownFor(entry.occurrence, filter)}
                lifted={lifted}
              >
                <EventChip
                  occurrence={entry.occurrence}
                  members={members}
                  now={now}
                  dimPast={dimPast && isToday}
                  continues={entry.continues}
                  compact
                  day={day}
                  onOpen={() => {
                    onOpen(entry.occurrence);
                  }}
                />
              </Draggable>
            ))}
            {allDay.length > BAND_CHIPS ? (
              <MoreButton count={allDay.length - BAND_CHIPS} day={day} onMore={onMore} />
            ) : null}
          </div>
        ) : null}
      </div>
      {/* A tap on an empty spot adds an event at that time: a shortcut for Add in the rail.
          `isolate` gives the body its own stacking context: the now line's z-30 (over the chips)
          stays inside it, and the sticky head's z-20 is above the whole body. */}
      <div
        data-dense=""
        data-day-body=""
        data-over={lighted ? "" : undefined}
        onClick={add}
        className={`hour-lines relative isolate min-w-0 @container ${lighted ? "bg-sun/15" : isToday ? "bg-lit" : ""}`}
      >
        <div className="absolute inset-y-0 inset-x-1">
          {/* A chip taken off the day fades and shrinks away (UX §9 "Chips leave"). */}
          <AnimatePresence initial={false}>
            {placed.map((item) => {
              if (item.kind === "more") {
                return (
                  <button
                    key={`more-${item.hidden[0]?.key ?? ""}`}
                    type="button"
                    onClick={() => {
                      onMore(day);
                    }}
                    className="press absolute rounded-chip-d bg-line/60 px-1 text-center text-d-secondary font-semibold text-ink [touch-action:manipulation]"
                    style={{
                      top: `${String(item.top)}px`,
                      height: `${String(item.height)}px`,
                      ...laneStyle(item.lane, item.lanes),
                    }}
                    aria-label={t("calendar.hours.more.aria", {
                      n: item.hidden.length,
                      day: longWeekday(day),
                    })}
                  >
                    {`+${String(item.hidden.length)}`}
                  </button>
                );
              }
              const entry = entries.get(item.occurrence.key);
              if (!entry) return null;
              return (
                <Draggable
                  key={item.occurrence.key}
                  entry={entry}
                  day={day}
                  faded={!shownFor(item.occurrence, filter)}
                  lifted={lifted}
                  className="absolute"
                  style={{
                    top: `${String(item.box.top)}px`,
                    height: `${String(item.box.height)}px`,
                    ...laneStyle(item.lane, item.lanes),
                  }}
                >
                  <Leaves className="h-full">
                    <HoursChip
                      entry={entry}
                      box={item.box}
                      rem={rem}
                      members={members}
                      now={now}
                      dimPast={dimPast && isToday}
                      day={day}
                      onOpen={() => {
                        onOpen(item.occurrence);
                      }}
                    />
                  </Leaves>
                </Draggable>
              );
            })}
          </AnimatePresence>
        </div>
        {y !== null ? <NowMinute key={`${String(zoom)}:${String(pph)}`} y={y} now={now} /> : null}
      </div>
    </section>
  );
}

/**
 * An event on the Hours grid: a button at least a tap target tall, holding the tinted block as
 * tall as the event lasts. What the block shows depends on its height: a time row and the title,
 * one row with both, the title alone, or only the tint (the button's name still says it all).
 */
function HoursChip({
  entry,
  box,
  rem,
  members,
  now,
  dimPast,
  day,
  onOpen,
}: {
  entry: DayEntry<Occurrence>;
  box: ChipBox;
  rem: number;
  members: Member[];
  now: string;
  dimPast: boolean;
  day: string;
  onOpen: () => void;
}) {
  const { occurrence } = entry;
  const people = peopleOf(occurrence, members);
  const arrived = useArrived(arrivalKey(occurrence));
  const tone = chipTone(occurrence, people, now, dimPast, "bg-line/60");
  const { tier, titleLines } = chipTier(box.visible, rem);
  const time = occurrence.start_local ? formatWallTime(occurrence.start_local) : "";
  return (
    <button
      type="button"
      data-chip=""
      data-arrive={arrived ? "" : undefined}
      data-key={occurrence.key}
      aria-label={occurrenceLabel(occurrence, people, day)}
      onClick={onOpen}
      // A column from the top: a button would center the block in itself, off its time.
      className="press flex h-full w-full flex-col rounded-chip-d text-left [touch-action:manipulation] focus-visible:z-40"
    >
      <span
        data-person={tone.person}
        className={`relative flex min-w-0 shrink-0 overflow-hidden rounded-chip-d pr-1 ${tone.className} ${
          tier === "lines" ? "flex-col gap-0.5 py-1.5" : "items-center gap-2"
        }`}
        style={{ marginTop: `${String(box.offset)}px`, height: `${String(box.visible)}px` }}
      >
        {tone.edge ? <PeopleEdge colors={tone.edge} /> : null}
        {tier === "lines" ? (
          <>
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="truncate text-d-secondary font-semibold @max-[10rem]:hidden">
                {time}
              </span>
              <PeopleMarks people={people} />
            </span>
            <span
              className={`${titleLines === 2 ? "line-clamp-2" : "line-clamp-1"} text-d-body font-semibold break-words`}
            >
              {occurrence.title}
            </span>
          </>
        ) : tier === "line" ? (
          <>
            <span className="min-w-0 flex-1 truncate text-d-body font-semibold">
              {occurrence.title}
            </span>
            <span className="shrink-0 text-d-secondary font-semibold @max-[10rem]:hidden">
              {time}
            </span>
          </>
        ) : tier === "title" ? (
          <span className="min-w-0 flex-1 truncate py-0.5 text-d-caption font-semibold">
            {occurrence.title}
          </span>
        ) : null}
      </span>
    </button>
  );
}

/** Today's now line (UX §9): it glides a minute's worth each minute, and with Reduce Motion
 * steps instead. Remounted on a zoom or resize, so it never glides across a change of scale. */
function NowMinute({ y, now }: { y: number; now: string }) {
  const t = useT();
  return (
    <div
      aria-hidden="true"
      data-now-line=""
      className="now-minute now-glow pointer-events-none absolute inset-x-0 top-0 z-30 h-0.5 rounded-full bg-sun-ink"
      style={{ transform: `translateY(${String(y)}px)` }}
    >
      <span
        className={`now-label absolute left-1 rounded-sm bg-lit/90 px-1 font-semibold whitespace-nowrap text-sun-ink ${
          y < 32 ? "top-1.5" : "bottom-1.5"
        }`}
      >
        {t("calendar.board.now", { time: formatWallTime(now).replace(/ [AP]M$/, "") })}
      </span>
    </div>
  );
}
