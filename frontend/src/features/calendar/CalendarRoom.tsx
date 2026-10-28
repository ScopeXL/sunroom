import { useMemo, useState } from "react";

import {
  addDays,
  monthGrid,
  monthYear,
  rollingWeek,
  shortDate,
  wallNow,
  weekOf,
  weekSpan,
  zonedParts,
} from "../../lib/dates";
import { Arrivals, useArrivals } from "../../lib/arrivals";
import { displayState, updateDisplay, type BoardView } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { usePageTurn } from "../../lib/motion";
import { useStore } from "../../lib/store";
import { useMinute } from "../../lib/time";
import { useRoomHeader } from "../../shell/roomHeader";
import { AddPanel } from "./AddPanel";
import { BoardControls } from "./BoardControls";
import { useEventChanges, useOccurrences } from "./data";
import { DayView } from "./DayView";
import { arrivalKey } from "./EventChip";
import { EventSheet } from "./EventSheet";
import { MonthView } from "./MonthView";
import { useOpenOverlay } from "./overlays";
import { PeopleView } from "./PeopleView";
import { ScopeChooser } from "./ScopeChooser";
import { TodayView } from "./TodayView";
import type { Occurrence, Scope } from "./types";
import { WeekView } from "./WeekView";

function homeView(setting: string | undefined): BoardView {
  if (setting === "rolling") return "rolling";
  if (setting === "today") return "today";
  if (setting === "people") return "people";
  return "week";
}

/**
 * The Calendar room on the wall screen (UX §3, §4): the board in its current view, its controls
 * in the wall's header (the arrows, the Week's layout, Filter, the views), the plugins' quiet
 * pills above the days, and the side panel (an event, or Add). What it shows lives in the
 * display's shared state, so the idle machine can put it back to this week (lib/displayState).
 */
export function CalendarRoom() {
  const state = useStore(displayState);
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const minute = useMinute();
  const now = wallNow(minute);
  const today = zonedParts(minute).day;
  const weekStartsOn = settings?.week_starts_on ?? 6;
  const view = state.view ?? homeView(settings?.display_home_view);
  const layout = state.weekLayout ?? settings?.display_week_layout ?? "agenda";
  const dimPast = settings?.display_dim_past ?? true;
  const changes = useEventChanges();
  const pages = usePageTurn();
  const [dragging, setDragging] = useState(false);
  const [draftDay, setDraftDay] = useState<string | null>(null);
  const [pendingMove, setPendingMove] = useState<{ occurrence: Occurrence; toDay: string } | null>(
    null,
  );

  // The calendar week, or on Rolling Week a window that keeps today in one column (ADR 0033, a
  // view of its own since ADR 0042). One array per week, not per render: the Hours grid follows
  // now while `days` holds still.
  const rolling = view === "rolling";
  const week = useMemo(() => {
    const anchor = addDays(today, state.weekOffset * 7);
    return rolling ? rollingWeek(anchor) : weekOf(anchor, weekStartsOn);
  }, [today, state.weekOffset, rolling, weekStartsOn]);
  const focusDay = state.day ?? today;
  const month = monthGrid(today, state.monthOffset, weekStartsOn);
  const range =
    view === "day" || view === "people"
      ? { from: focusDay, to: addDays(focusDay, 1) }
      : view === "month"
        ? { from: month.days[0] ?? today, to: addDays(month.days.at(-1) ?? today, 1) }
        : view === "today"
          ? { from: today, to: addDays(today, 7) }
          : { from: week[0] ?? today, to: addDays(week[6] ?? today, 1) };
  const { data, isPlaceholderData } = useOccurrences(range.from, range.to, { overlays: true });
  const occurrences = data?.occurrences ?? [];
  // A chip added or moved while this week (day, month) shows eases in; paging or another view
  // is a new scope, and the events of the last one still up while it loads are nobody's news.
  const arrived = useArrivals(
    occurrences.map(arrivalKey),
    data && !isPlaceholderData ? `${view} ${range.from} ${range.to}` : null,
  );
  const openOverlay = useOpenOverlay();

  const open = (occurrence: Occurrence) => {
    if (openOverlay(occurrence)) return;
    updateDisplay({
      panel: {
        kind: "event",
        eventId: occurrence.event_id ?? null,
        recurrenceId: occurrence.recurrence_id ?? null,
        key: occurrence.key,
      },
    });
  };
  // A tap on the board while Add is open sets the day: the panel keeps the kind of thing being
  // added and its title.
  const add = (day: string | null, hour: number | null = null, minute: number | null = null) => {
    const open = state.panel?.kind === "add" ? state.panel : null;
    updateDisplay({
      panel: {
        kind: "add",
        day,
        hour,
        minute,
        ...(open?.type ? { type: open.type } : {}),
        ...(open?.title ? { title: open.title } : {}),
      },
    });
  };
  const move = (occurrence: Occurrence, toDay: string) => {
    if (!occurrence.event_id) return;
    if (occurrence.is_recurring) {
      setPendingMove({ occurrence, toDay });
      return;
    }
    changes.move.mutate({
      target: { eventId: occurrence.event_id, recurrenceId: null },
      scope: "all",
      toDate: toDay,
      title: occurrence.title,
    });
  };

  // Each view's arrows change what that view reads: People pages a day, as Day does.
  const page = (step: -1 | 1) => {
    pages.turn(step);
    if (view === "day" || view === "people") updateDisplay({ day: addDays(focusDay, step) });
    else if (view === "month") updateDisplay({ monthOffset: state.monthOffset + step });
    else updateDisplay({ weekOffset: state.weekOffset + step });
  };
  const backToToday = () => {
    pages.turn(focusDay > today ? -1 : 1);
    updateDisplay({ day: null });
  };
  // The room's name, for a screen reader (the header draws none: the day heads carry the dates,
  // and the Month and Day views say theirs), and what the middle button goes back to.
  const weekHeader = {
    title: state.weekOffset === 0 ? "This Week" : weekSpan(week),
    homeLabel: "This Week",
    atHome: state.weekOffset === 0,
    home: () => {
      pages.turn(-state.weekOffset);
      updateDisplay({ weekOffset: 0 });
    },
  };
  const header = {
    week: weekHeader,
    // The window around today pages a week at a time too, back to "This Week".
    rolling: weekHeader,
    day: {
      title: shortDate(focusDay),
      homeLabel: "Today",
      atHome: focusDay === today,
      home: backToToday,
    },
    month: {
      title: monthYear(month.first),
      homeLabel: "This Month",
      atHome: state.monthOffset === 0,
      home: () => {
        pages.turn(-state.monthOffset);
        updateDisplay({ monthOffset: 0 });
      },
    },
    // The day is written over the columns (DayCaption); "People" names the room.
    people: {
      title: "People",
      homeLabel: "Today",
      atHome: focusDay === today,
      home: backToToday,
    },
    // Always today and the six days after: nothing to page, so no arrows (BoardControls).
    today: {
      title: "Today",
      homeLabel: "Today",
      atHome: true,
      home: () => undefined,
    },
  }[view];
  // Someone who has since left the household may still be in a remembered filter.
  const people = state.people.filter((id) => members.some((member) => member.id === id));

  useRoomHeader({
    title: header.title,
    notice: dragging ? "Drop on a day" : null,
    controls: (
      <BoardControls
        view={view}
        onView={(next) => {
          pages.rest();
          updateDisplay({ view: next });
        }}
        paging={view !== "today"}
        homeLabel={header.homeLabel}
        atHome={header.atHome}
        onPage={page}
        onHome={header.home}
        layout={layout}
        onLayout={(weekLayout) => {
          updateDisplay({ weekLayout });
        }}
        members={members}
        people={people}
        onPeople={(chosen) => {
          updateDisplay({ people: chosen });
        }}
      />
    ),
  });

  return (
    <section
      aria-label={view === "week" || view === "rolling" ? "This Week" : header.title}
      className="@container flex min-h-0 flex-1 flex-col"
    >
      <Arrivals value={arrived}>
        <div {...pages.attrs} className="flex min-h-0 flex-1 flex-col">
          {view === "week" || view === "rolling" ? (
            <WeekView
              days={week}
              today={today}
              now={now}
              occurrences={occurrences}
              members={members}
              dimPast={dimPast}
              people={people}
              layout={layout}
              zoom={state.hoursZoom}
              onZoom={(hoursZoom) => {
                updateDisplay({ hoursZoom });
              }}
              onOpen={open}
              onAdd={(day, hour, minute) => {
                add(day, hour ?? null, minute ?? null);
              }}
              onMore={(day) => {
                updateDisplay({ view: "day", day });
              }}
              onMove={move}
              onSwipe={page}
              onDragging={setDragging}
              lit={state.panel?.kind === "add" || state.panel?.kind === "edit" ? draftDay : null}
            />
          ) : view === "day" ? (
            <DayView
              day={focusDay}
              now={now}
              occurrences={occurrences}
              members={members}
              dimPast={dimPast}
              people={people}
              onOpen={open}
              onAdd={(hour) => {
                add(focusDay, hour);
              }}
            />
          ) : view === "month" ? (
            <MonthView
              grid={month}
              today={today}
              occurrences={occurrences}
              members={members}
              people={people}
              onDay={(day) => {
                updateDisplay({ view: "day", day });
              }}
            />
          ) : view === "people" ? (
            <PeopleView
              day={focusDay}
              today={today}
              now={now}
              occurrences={occurrences}
              members={members}
              dimPast={dimPast}
              onOpen={open}
            />
          ) : (
            <TodayView
              today={today}
              now={now}
              occurrences={occurrences}
              loading={data === undefined}
              members={members}
              onOpen={open}
            />
          )}
        </div>
        <EventSheet
          panel={state.panel?.kind === "event" ? state.panel : null}
          onClose={() => {
            updateDisplay({ panel: null });
          }}
          onChange={(eventId, recurrenceId) => {
            updateDisplay({ panel: { kind: "edit", eventId, recurrenceId } });
          }}
        />
        <AddPanel
          panel={state.panel?.kind === "add" || state.panel?.kind === "edit" ? state.panel : null}
          today={today}
          onDay={setDraftDay}
          onClose={() => {
            updateDisplay({ panel: null });
          }}
          onType={(type) => {
            if (state.panel?.kind === "add") updateDisplay({ panel: { ...state.panel, type } });
          }}
        />
        <ScopeChooser
          open={pendingMove !== null}
          verb="Move"
          title={pendingMove?.occurrence.title ?? ""}
          onChoose={(scope: Scope) => {
            const pending = pendingMove;
            setPendingMove(null);
            if (!pending?.occurrence.event_id) return;
            changes.move.mutate({
              target: {
                eventId: pending.occurrence.event_id,
                recurrenceId: pending.occurrence.recurrence_id ?? null,
              },
              scope,
              toDate: pending.toDay,
              title: pending.occurrence.title,
            });
          }}
          onCancel={() => {
            setPendingMove(null);
          }}
        />
      </Arrivals>
    </section>
  );
}
