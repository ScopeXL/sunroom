import { ChevronDown, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";

import {
  addDays,
  monthGrid,
  monthYear,
  shortDate,
  shortMonth,
  wallNow,
  weekOf,
  zonedParts,
} from "../../lib/dates";
import { Arrivals, useArrivals } from "../../lib/arrivals";
import { usePageTurn } from "../../lib/motion";
import type { BoardPanel } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { useT, type Key } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { ActionBar } from "../../ui/ActionBar";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { LiveStatusButton } from "../../ui/LiveStatus";
import { Chip } from "../../ui/Chip";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { TextField } from "../../ui/TextField";
import { AddPanel } from "../calendar/AddPanel";
import { useEventSearch, useOccurrences } from "../calendar/data";
import { arrivalKey } from "../calendar/EventChip";
import { DayView } from "../calendar/DayView";
import { EventSheet } from "../calendar/EventSheet";
import { Agenda, DayGroups, PhoneMonth, WeekStrip } from "../calendar/PhoneLists";
import { useOpenOverlay } from "../calendar/overlays";
import type { Occurrence } from "../calendar/types";

type Mode = "week" | "day" | "agenda" | "month";

const MODES: readonly { value: Mode; label: Key }[] = [
  { value: "week", label: "phone.calendar.mode.week" },
  { value: "day", label: "phone.calendar.mode.day" },
  { value: "agenda", label: "phone.calendar.mode.agenda" },
  { value: "month", label: "phone.calendar.mode.month" },
];

const MODE_KEY = "sunroom.calendar.mode";
const PEOPLE_KEY = "sunroom.calendar.people";
const LIST_DAYS = 14;
const AGENDA_PAST = 14;
const AGENDA_DAYS = 56;

/** A phone remembers its view and person filter (UX §5); private browsing just forgets. */
function remembered<T>(key: string, fallback: T, valid: (value: unknown) => value is T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const value: unknown = JSON.parse(raw);
    return valid(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage is off: the choice lasts until the page reloads.
  }
}

const isMode = (value: unknown): value is Mode =>
  value === "week" || value === "day" || value === "agenda" || value === "month";
const isIds = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((id) => typeof id === "string");

/** The same day of the month `step` months away (the 31st becomes the month's last day). */
function monthStep(day: string, step: number): string {
  const [year = 1970, month = 1, date = 1] = day.split("-").map(Number);
  const index = year * 12 + (month - 1) + step;
  const y = Math.floor(index / 12);
  const m = (index % 12) + 1;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${String(y)}-${String(m).padStart(2, "0")}-${String(Math.min(date, last)).padStart(2, "0")}`;
}

/**
 * A phone's Calendar (UX §5): Week (a strip of days over a continuous list from the chosen day),
 * Day (the timeline), Agenda (grouped by day, the past folded into Earlier) and Month (a grid
 * with dots over the chosen day's list). The month title opens the month picker with search.
 * Events open in a sheet; Add and Change open the editor in a sheet.
 */
export function CalendarScreen() {
  const t = useT();
  const minute = useMinute();
  const now = wallNow(minute);
  const today = zonedParts(minute).day;
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const weekStartsOn = settings?.week_starts_on ?? 6;
  const dimPast = settings?.display_dim_past ?? true;
  const [mode, setModeState] = useState<Mode>(() => remembered(MODE_KEY, "week", isMode));
  const pages = usePageTurn();
  const [people, setPeopleState] = useState<string[]>(() => remembered(PEOPLE_KEY, [], isIds));
  const [showPeople, setShowPeople] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [panel, setPanel] = useState<BoardPanel>(null);
  const [picker, setPicker] = useState(false);
  const selected = chosen ?? today;
  const week = weekOf(selected, weekStartsOn);
  const grid = monthGrid(selected, 0, weekStartsOn);

  const setMode = (next: Mode) => {
    pages.rest();
    setModeState(next);
    remember(MODE_KEY, next);
  };
  const setPeople = (next: string[]) => {
    setPeopleState(next);
    remember(PEOPLE_KEY, next);
  };

  const range =
    mode === "day"
      ? { from: selected, to: addDays(selected, 1) }
      : mode === "agenda"
        ? { from: addDays(today, -AGENDA_PAST), to: addDays(today, AGENDA_DAYS) }
        : mode === "month"
          ? { from: grid.days[0] ?? selected, to: addDays(grid.days.at(-1) ?? selected, 1) }
          : { from: week[0] ?? selected, to: addDays(selected, LIST_DAYS) };
  const { data, isPlaceholderData } = useOccurrences(range.from, range.to, { overlays: true });
  const occurrences = data?.occurrences ?? [];
  // An event added or moved while this list shows eases in (lib/arrivals); another mode or day
  // is a new scope.
  const arrived = useArrivals(
    occurrences.map(arrivalKey),
    data && !isPlaceholderData ? `${mode} ${range.from} ${range.to}` : null,
  );
  const openOverlay = useOpenOverlay();

  const open = (occurrence: Occurrence) => {
    if (openOverlay(occurrence)) return;
    setPanel({
      kind: "event",
      eventId: occurrence.event_id ?? null,
      recurrenceId: occurrence.recurrence_id ?? null,
      key: occurrence.key,
    });
  };
  const step = (direction: -1 | 1) => {
    pages.turn(direction);
    if (mode === "day") setChosen(addDays(selected, direction));
    else if (mode === "month") setChosen(monthStep(selected, direction));
    else setChosen(addDays(selected, direction * 7));
  };
  const unit = mode === "day" ? "day" : mode === "month" ? "month" : "week";
  const listDays = Array.from({ length: LIST_DAYS }, (_, n) => addDays(selected, n));
  const agendaDays = Array.from({ length: AGENDA_PAST + AGENDA_DAYS }, (_, n) =>
    addDays(today, n - AGENDA_PAST),
  );
  const chosenPeople = members.filter((m) => people.includes(m.id));

  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-4 px-4 pt-[calc(env(safe-area-inset-top)+16px)] pb-40">
      <Arrivals value={arrived}>
        <header className="flex items-center justify-between gap-2">
          <h1 className="text-title font-bold">
            <button
              type="button"
              aria-haspopup="dialog"
              onClick={() => {
                setPicker(true);
              }}
              className="press flex min-h-11 items-center gap-1 rounded-button text-left"
            >
              {monthYear(mode === "week" ? (week[3] ?? selected) : selected)}
              <ChevronDown aria-hidden="true" className="size-6" />
            </button>
          </h1>
          <div className="flex items-center gap-2">
            {selected !== today ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setChosen(null);
                }}
              >
                {t("phone.calendar.today.action")}
              </Button>
            ) : null}
            {mode === "agenda" ? null : (
              <>
                <Button
                  variant="secondary"
                  icon
                  aria-label={t("phone.calendar.previous.aria", { unit })}
                  onClick={() => {
                    step(-1);
                  }}
                >
                  <ChevronLeft aria-hidden="true" className="size-6" />
                </Button>
                <Button
                  variant="secondary"
                  icon
                  aria-label={t("phone.calendar.next.aria", { unit })}
                  onClick={() => {
                    step(1);
                  }}
                >
                  <ChevronRight aria-hidden="true" className="size-6" />
                </Button>
              </>
            )}
          </div>
        </header>
        <Segmented
          label={t("phone.calendar.mode.aria")}
          options={MODES.map(({ value, label }) => ({ value, label: t(label) }))}
          value={mode}
          onChange={setMode}
        />
        <div className="flex flex-col gap-2">
          {/* The live-updates icon at the right, only while something's wrong (ADR 0030): the
              header has no room beside the arrows. */}
          <div className="flex items-center justify-between gap-2">
            <Chip
              opener
              expanded={showPeople}
              onClick={() => {
                setShowPeople(!showPeople);
              }}
            >
              {chosenPeople.length
                ? t("phone.calendar.show.people", {
                    names: chosenPeople.map((m) => m.name).join(", "),
                  })
                : t("phone.calendar.show.everyone")}
            </Chip>
            <LiveStatusButton />
          </div>
          {showPeople ? (
            <div
              role="group"
              aria-label={t("phone.calendar.show.aria")}
              className="flex flex-wrap gap-2"
            >
              {members.map((member) => {
                const on = people.includes(member.id);
                return (
                  <button
                    key={member.id}
                    type="button"
                    aria-pressed={on}
                    aria-label={member.name}
                    onClick={() => {
                      setPeople(
                        on ? people.filter((id) => id !== member.id) : [...people, member.id],
                      );
                    }}
                    className={`press flex size-12 items-center justify-center rounded-full ${
                      on ? "ring-[3px] ring-ink" : people.length ? "opacity-50" : ""
                    }`}
                  >
                    <Avatar member={member} size="sm" />
                  </button>
                );
              })}
              {people.length ? (
                <Button
                  variant="quiet"
                  onClick={() => {
                    setPeople([]);
                  }}
                >
                  {t("phone.calendar.everyone.action")}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <div {...pages.attrs} className="flex flex-col gap-4">
          {mode === "week" ? (
            <>
              <WeekStrip
                days={week}
                today={today}
                selected={selected}
                occurrences={occurrences}
                members={members}
                people={people}
                onSelect={setChosen}
              />
              <DayGroups
                days={listDays}
                today={today}
                now={now}
                occurrences={occurrences}
                members={members}
                people={people}
                dimPast={dimPast}
                onOpen={open}
              />
            </>
          ) : mode === "day" ? (
            <section aria-label={shortDate(selected)} className="flex flex-col">
              <h2 className="text-row font-bold">
                {selected === today
                  ? t("phone.calendar.day.today", { date: shortDate(selected) })
                  : shortDate(selected)}
              </h2>
              <DayView
                day={selected}
                now={now}
                occurrences={occurrences}
                members={members}
                dimPast={dimPast}
                people={people}
                onOpen={open}
                onAdd={(hour) => {
                  setPanel({ kind: "add", day: selected, hour });
                }}
              />
            </section>
          ) : mode === "agenda" ? (
            <Agenda
              days={agendaDays}
              today={today}
              now={now}
              occurrences={occurrences}
              members={members}
              people={people}
              dimPast={dimPast}
              onOpen={open}
            />
          ) : (
            <>
              <PhoneMonth
                grid={grid}
                today={today}
                selected={selected}
                occurrences={occurrences}
                members={members}
                people={people}
                onSelect={setChosen}
              />
              <DayGroups
                days={[selected]}
                today={today}
                now={now}
                occurrences={occurrences}
                members={members}
                people={people}
                dimPast={dimPast}
                keepEmpty
                onOpen={open}
              />
            </>
          )}
        </div>

        <ActionBar>
          <Button
            block
            onClick={() => {
              setPanel({ kind: "add", day: selected, hour: null });
            }}
          >
            <Plus aria-hidden="true" className="size-5" />
            {t("app.action.add")}
          </Button>
        </ActionBar>
        <EventSheet
          panel={panel?.kind === "event" ? panel : null}
          onClose={() => {
            setPanel(null);
          }}
          onChange={(eventId, recurrenceId) => {
            setPanel({ kind: "edit", eventId, recurrenceId });
          }}
        />
        <AddPanel
          panel={panel?.kind === "add" || panel?.kind === "edit" ? panel : null}
          today={today}
          onClose={() => {
            setPanel(null);
          }}
          onType={(type) => {
            setPanel((open) => (open?.kind === "add" ? { ...open, type } : open));
          }}
        />
        <MonthPicker
          open={picker}
          selected={selected}
          onPick={(day) => {
            setChosen(day);
            setPicker(false);
          }}
          onFound={(day) => {
            setChosen(day);
            setMode("day");
            setPicker(false);
          }}
          onClose={() => {
            setPicker(false);
          }}
        />
      </Arrivals>
    </main>
  );
}

const MONTHS = Array.from({ length: 12 }, (_, n) => n);

/** The month picker (UX §5): search by title or place, or jump to a month. */
function MonthPicker({
  open,
  selected,
  onPick,
  onFound,
  onClose,
}: {
  open: boolean;
  selected: string;
  onPick: (day: string) => void;
  onFound: (day: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [year, setYear] = useState(() => Number(selected.slice(0, 4)));
  const { data: hits = [], isFetching } = useEventSearch(open ? query : "");
  const words = query.trim();
  return (
    <Sheet open={open} title={t("phone.calendar.find.title")} onClose={onClose}>
      <div className="flex flex-col gap-5">
        <TextField
          label={t("phone.calendar.find.search.label")}
          type="search"
          placeholder={t("phone.calendar.find.search.placeholder")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          enterKeyHint="search"
        />
        {words.length >= 2 ? (
          <ul
            aria-label={t("phone.calendar.find.found.aria")}
            aria-busy={isFetching}
            className="flex flex-col"
          >
            {hits.length === 0 && !isFetching ? (
              <li className="text-secondary text-ink-soft">
                {t("phone.calendar.find.none.empty", { words })}
              </li>
            ) : null}
            {hits.map((hit) => {
              const day = hit.next_start_date ?? hit.next_start_local?.slice(0, 10) ?? null;
              return (
                <li key={hit.event.id}>
                  <button
                    type="button"
                    disabled={!day}
                    onClick={() => {
                      if (day) onFound(day);
                    }}
                    className="press-row flex min-h-14 w-full flex-col items-start justify-center rounded-chip px-2 py-2 text-left"
                  >
                    <span className="text-body font-semibold">{hit.event.title}</span>
                    <span className="text-secondary text-ink-soft">
                      {[day ? shortDate(day) : null, hit.event.location]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="secondary"
            icon
            aria-label={t("phone.calendar.find.previous_year.aria")}
            onClick={() => {
              setYear(year - 1);
            }}
          >
            <ChevronLeft aria-hidden="true" className="size-6" />
          </Button>
          <p className="text-row font-bold">{year}</p>
          <Button
            variant="secondary"
            icon
            aria-label={t("phone.calendar.find.next_year.aria")}
            onClick={() => {
              setYear(year + 1);
            }}
          >
            <ChevronRight aria-hidden="true" className="size-6" />
          </Button>
        </div>
        <div
          role="group"
          aria-label={t("phone.calendar.find.months.aria")}
          className="grid grid-cols-3 gap-2"
        >
          {MONTHS.map((index) => {
            const first = `${String(year)}-${String(index + 1).padStart(2, "0")}-01`;
            const on = selected.slice(0, 7) === first.slice(0, 7);
            return (
              <Chip
                key={first}
                on={on}
                onClick={() => {
                  onPick(first);
                }}
              >
                {shortMonth(first)}
              </Chip>
            );
          })}
        </div>
      </div>
    </Sheet>
  );
}
