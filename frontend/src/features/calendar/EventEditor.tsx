import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../../api/client";
import { addDays, householdZone, longMonthDay, weekdayOf } from "../../lib/dates";
import { serverNow } from "../../lib/clock";
import { useMembers, useSettings } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { ColorDots } from "../../ui/ColorDots";
import { DayField } from "../../ui/DayField";
import { Field, FormSection } from "../../ui/Field";
import { LengthField } from "../../ui/LengthField";
import { MonthGrid } from "../../ui/MonthGrid";
import { PanelActions } from "../../ui/PanelActions";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { TimeField } from "../../ui/TimeField";
import { ChoiceRow } from "../../ui/ValueRow";
import { WhoPicker } from "../../ui/WhoPicker";
import { calendarChoiceLabel, takesEvents, useCalendars } from "./data";
import { parseQuickAdd, type QuickAddDraft } from "./quickAdd";
import { reminderChoices, reminderPick, reminderValue } from "./reminderWords";
import { RepeatField } from "./RepeatField";
import { repeatToRRule, rruleToRepeat, type Repeat, type RepeatEnd } from "./repeat";
import type { CalendarEvent, EventFields, Occurrence, PersonColor } from "./types";
import { useBoardDay } from "./useBoardDay";

export interface Draft {
  title: string;
  day: string;
  allDay: boolean;
  /** Last day for an all-day span (inclusive); null is one day. */
  lastDay: string | null;
  start: string; // "HH:MM"
  minutes: number;
  memberIds: string[];
  /** Who was chosen (the row, or quick add naming people on a new event): only then are the
   * people sent, so an untouched Who leaves a synced event's person and its title's say alone
   * (P1, ADR 0034). */
  whoTouched?: boolean;
  repeat: Repeat | null;
  repeatEnd: RepeatEnd;
  /** A rule the editor's shapes can't hold ("the 15th" on an event that starts on the 9th):
   * kept exactly as it is, with the server's words for it, until a repeat is picked. */
  kept: KeptRule | null;
  calendarId: string | null;
  color: PersonColor | null;
  location: string;
  notes: string;
  /** Its own reminders, minutes before; none with `remindersOff` false is the household's
   * Default reminder (ADR 0034). */
  reminders: number[];
  remindersOff: boolean;
  /** The Remind row was picked: only then are reminders sent, so an untouched row keeps what
   * the event holds. */
  remindChanged?: boolean;
}

export interface KeptRule {
  rrule: string;
  text: string;
}

const dayDiff = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

function addMinutes(day: string, start: string, minutes: number): string {
  const [h = 0, m = 0] = start.split(":").map(Number);
  const total = h * 60 + m + minutes;
  const days = Math.floor(total / 1440);
  const rest = total - days * 1440;
  return `${addDays(day, days)}T${String(Math.floor(rest / 60)).padStart(2, "0")}:${String(rest % 60).padStart(2, "0")}`;
}

/**
 * The day a weekly repeat starts: its first weekday on or after the chosen day. A start on any
 * other day would be an extra occurrence (RFC 5545 always counts the start), so "Every weekday"
 * chosen on a Saturday starts on Monday.
 */
export function firstDayOf(repeat: Repeat | null, day: string): string {
  if (repeat?.freq !== "weekly") return day;
  for (let n = 0; n < 7; n += 1) {
    const candidate = addDays(day, n);
    if (repeat.weekdays.includes(weekdayOf(candidate))) return candidate;
  }
  return day;
}

/** The API body for this draft. `align` moves a weekly repeat's start onto one of its days;
 * one occurrence changed on its own stays where it was put. `weekStartsOn` is the household's,
 * for a rule whose days depend on it. A kept rule goes back as it came. */
export function draftToFields(
  original: Draft,
  { align = true, weekStartsOn = 0 }: { align?: boolean; weekStartsOn?: number } = {},
): EventFields & { title: string } {
  const day = align ? firstDayOf(original.repeat, original.day) : original.day;
  const draft: Draft =
    day === original.day
      ? original
      : {
          ...original,
          day,
          lastDay: original.lastDay ? addDays(original.lastDay, dayDiff(original.day, day)) : null,
        };
  const rrule = draft.repeat
    ? repeatToRRule(draft.repeat, draft.day, draft.repeatEnd, weekStartsOn)
    : (draft.kept?.rrule ?? null);
  const common = {
    title: draft.title.trim(),
    ...(draft.whoTouched ? { member_ids: draft.memberIds } : {}),
    ...(draft.remindChanged
      ? { reminders: draft.reminders, reminders_off: draft.remindersOff }
      : {}),
    calendar_id: draft.calendarId,
    color: draft.color,
    location: draft.location.trim(),
    description: draft.notes,
    rrule,
  };
  if (draft.allDay) {
    return {
      ...common,
      all_day: true,
      start_date: draft.day,
      end_date: addDays(draft.lastDay ?? draft.day, 1),
    };
  }
  return {
    ...common,
    all_day: false,
    start: `${draft.day}T${draft.start}`,
    end: addMinutes(draft.day, draft.start, draft.minutes),
  };
}

/**
 * A draft for an existing event, at the occurrence it was opened from. `at` is that occurrence's
 * own row when it was changed on its own (R2, ADR 0034): its title, place, notes, color and
 * reminders are read there; the series' timing and repeat from `event`.
 */
export function draftFromEvent(
  event: CalendarEvent,
  occurrence: Occurrence | null,
  weekStartsOn = 0,
  at: CalendarEvent | null = null,
): Draft {
  const own = at?.is_override ? at : event;
  const startLocal = occurrence?.start_local ?? event.start ?? null;
  const endLocal = occurrence?.end_local ?? event.end ?? null;
  const day = occurrence?.start_date ?? startLocal?.slice(0, 10) ?? event.start_date ?? "";
  const endDate = occurrence?.end_date ?? event.end_date;
  const parsed = event.rrule ? rruleToRepeat(event.rrule, day, weekStartsOn) : null;
  let minutes = 60;
  if (startLocal && endLocal) {
    minutes = Math.max(
      5,
      Math.round((Date.parse(`${endLocal}Z`) - Date.parse(`${startLocal}Z`)) / 60_000),
    );
  }
  return {
    title: own.title,
    day,
    allDay: event.all_day,
    lastDay: event.all_day && endDate ? addDays(endDate, -1) : null,
    start: startLocal ? startLocal.slice(11, 16) : "09:00",
    minutes,
    memberIds: occurrence?.member_ids ?? event.member_ids,
    repeat: parsed?.repeat ?? null,
    repeatEnd: parsed?.end ?? {},
    kept:
      event.rrule && !parsed
        ? { rrule: event.rrule, text: event.repeat_text ?? t("calendar.repeat.as_it_is") }
        : null,
    calendarId: event.calendar_id,
    color: own.color ?? null,
    location: own.location,
    notes: own.description,
    reminders: own.reminders,
    remindersOff: own.reminders_off,
  };
}

/**
 * The event editor (UX §4 "Add and the event editor", §5, ADR 0029): the quick-add field, then
 * every part of the event on its own row, built for a finger: Who, Day, Time, How long, Repeats,
 * Calendar, Color, and More… for the rest. Typing fills the rows as it's understood; a row set
 * by hand keeps winning over later typing, and anything the parser fills is one tap to change.
 * The button stays pinned above the keyboard. The same form fills the wall's side panel and a
 * phone's sheet.
 */
export function EventEditor({
  initial,
  editing,
  today,
  defaultDay,
  defaultHour,
  defaultMinute = null,
  pending,
  error,
  onSave,
  onDay,
}: {
  /** An existing event's draft; null for a new one. */
  initial: Draft | null;
  /** Only the title in the field (no parsing) when changing an event. */
  editing: boolean;
  today: string;
  /** The day Add was opened on: a tapped day, or today. */
  defaultDay: string;
  defaultHour: number | null;
  /** With `defaultHour`: the minute a tap on the Hours grid chose. */
  defaultMinute?: number | null;
  pending: boolean;
  error: unknown;
  onSave: (draft: Draft) => void;
  /** The draft's day as it changes, so the board can light it; null when the editor closes. */
  onDay?: (day: string | null) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const { data: calendars = [] } = useCalendars();
  const weekStartsOn = settings?.week_starts_on ?? 6;
  const writable = calendars.filter(takesEvents);
  // Settings → Calendars & Accounts → Default calendar: where a new event starts.
  const defaultCalendar = writable.find((c) => c.is_default)?.id ?? writable[0]?.id ?? null;
  const [text, setText] = useState(initial?.title ?? "");
  const [manual, setManual] = useState<Partial<Draft>>(initial ?? {});
  const [whoTouched, setWhoTouched] = useState(false);
  const defaultReminder = settings?.default_reminder_minutes ?? null;
  const [more, setMore] = useState(
    Boolean(
      initial &&
      (initial.location || initial.notes || initial.reminders.length || initial.remindersOff),
    ),
  );
  const [span, setSpan] = useState(Boolean(initial?.lastDay && initial.lastDay !== initial.day));

  const parsed: QuickAddDraft | null = useMemo(() => {
    if (editing) return null;
    return parseQuickAdd(text, {
      now: new Date(serverNow()),
      zone: householdZone() ?? settings?.timezone ?? "UTC",
      weekStartsOn: settings?.week_starts_on ?? 6,
      members: members.map((m) => ({ id: m.id, name: m.name })),
      defaultDay,
    });
  }, [editing, text, settings, members, defaultDay]);

  const set = (change: Partial<Draft>) => {
    setManual((current) => ({ ...current, ...change }));
  };
  // A day tapped on the board while the panel is open sets the date (UX §4).
  useBoardDay(defaultDay, (day) => {
    if (!initial) set({ day });
  });

  const fromHour =
    defaultHour === null
      ? null
      : `${String(defaultHour).padStart(2, "0")}:${String(defaultMinute ?? 0).padStart(2, "0")}`;
  const draft: Draft = {
    title: editing ? text : (parsed?.title ?? text),
    day: manual.day ?? parsed?.day ?? defaultDay,
    allDay: manual.allDay ?? (parsed ? parsed.allDay && fromHour === null : false),
    lastDay: manual.lastDay ?? null,
    start: manual.start ?? parsed?.start ?? fromHour ?? "09:00",
    minutes: manual.minutes ?? parsed?.durationMinutes ?? 60,
    memberIds: manual.memberIds ?? parsed?.memberIds ?? [],
    // Names quick add took out of a new event's title must be sent: the title no longer has them.
    whoTouched: whoTouched || Boolean(!initial && parsed?.memberIds.length),
    repeat: manual.repeat !== undefined ? manual.repeat : (parsed?.repeat ?? null),
    repeatEnd: manual.repeatEnd ?? {},
    kept: manual.kept ?? null,
    calendarId: manual.calendarId ?? defaultCalendar,
    color: manual.color !== undefined ? manual.color : null,
    location: manual.location ?? "",
    notes: manual.notes ?? "",
    reminders: manual.reminders ?? [],
    remindersOff: manual.remindersOff ?? false,
    remindChanged: manual.remindChanged ?? false,
  };
  useEffect(() => {
    onDay?.(draft.day);
  }, [onDay, draft.day]);
  useEffect(
    () => () => {
      onDay?.(null);
    },
    [onDay],
  );

  // Once the parser has taken words out of what was typed, say what's left as the title.
  const took = !editing && draft.title.trim() !== "" && draft.title.trim() !== text.trim();
  const longer = draft.lastDay !== null && draft.lastDay !== draft.day;

  return (
    <form
      className={`flex flex-col ${display ? "gap-8" : "gap-6"}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (draft.title.trim()) onSave(draft);
      }}
    >
      <FormSection title={t("calendar.editor.what.title")} quiet>
        <TextField
          label={
            editing ? t("calendar.editor.event_title.label") : t("calendar.editor.quick.label")
          }
          hint={
            editing
              ? null
              : took
                ? t("calendar.editor.quick.saved_as", { title: draft.title.trim() })
                : t("calendar.editor.quick.hint")
          }
          value={text}
          maxLength={200}
          autoComplete="off"
          data-autofocus=""
          error={error ? errorMessage(error) : null}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <Field label={t("calendar.editor.who.label")}>
          <WhoPicker
            label={t("calendar.editor.who.label")}
            members={members}
            value={draft.memberIds}
            multiple
            onChange={(memberIds) => {
              setWhoTouched(true);
              set({ memberIds });
            }}
          />
        </Field>
      </FormSection>
      <FormSection title={t("calendar.editor.when.title")}>
        <DayField
          value={draft.day}
          today={today}
          weekStartsOn={weekStartsOn}
          onChange={(day) => {
            // A span keeps its last day while it's still after the new first one.
            set({ day, lastDay: draft.lastDay && draft.lastDay > day ? draft.lastDay : null });
          }}
        />
        {draft.allDay ? (
          <Field label={t("calendar.editor.last_day.label")}>
            <ChipRow label={t("calendar.editor.last_day.label")}>
              <Chip
                on={!longer}
                onClick={() => {
                  setSpan(false);
                  set({ lastDay: null });
                }}
              >
                {t("calendar.editor.last_day.same")}
              </Chip>
              <Chip
                opener
                expanded={span}
                onClick={() => {
                  setSpan(!span);
                }}
              >
                {longer && draft.lastDay
                  ? t("calendar.editor.last_day.until", { date: longMonthDay(draft.lastDay) })
                  : t("calendar.editor.last_day.another")}
              </Chip>
            </ChipRow>
            {span ? (
              <MonthGrid
                label={t("calendar.editor.last_day.month.aria")}
                value={draft.lastDay ?? draft.day}
                today={today}
                weekStartsOn={weekStartsOn}
                min={draft.day}
                onChange={(lastDay) => {
                  set({ lastDay: lastDay === draft.day ? null : lastDay });
                }}
              />
            ) : null}
          </Field>
        ) : null}
        <TimeField
          label={t("calendar.editor.time.label")}
          value={draft.allDay ? null : draft.start}
          none={{ label: t("calendar.editor.all_day") }}
          onChange={(time) => {
            set(time === null ? { allDay: true } : { allDay: false, start: time });
          }}
        />
        {draft.allDay ? null : (
          <LengthField
            value={draft.minutes}
            onChange={(minutes) => {
              set({ minutes });
            }}
          />
        )}
        <RepeatField
          day={draft.day}
          today={today}
          value={draft.repeat}
          repeatEnd={draft.repeatEnd}
          kept={draft.kept}
          weekStartsOn={weekStartsOn}
          onChange={set}
        />
      </FormSection>
      <FormSection title={t("calendar.editor.details.title")}>
        {writable.length > 1 ? (
          <ChoiceRow
            label={t("calendar.editor.calendar.label")}
            choices={writable.map((c) => ({ value: c.id, label: calendarChoiceLabel(c) }))}
            value={draft.calendarId ?? ""}
            onChange={(calendarId) => {
              set({ calendarId });
            }}
          />
        ) : null}
        <Field label={t("calendar.editor.color.label")}>
          <ColorDots
            value={draft.color}
            noneLabel={t("calendar.editor.color.person")}
            onChange={(color) => {
              set({ color });
            }}
          />
        </Field>
        <div>
          <Chip
            opener
            expanded={more}
            onClick={() => {
              setMore(!more);
            }}
          >
            {t("calendar.editor.more")}
          </Chip>
        </div>
        {more ? (
          <>
            <TextField
              label={t("calendar.editor.where.label")}
              value={draft.location}
              maxLength={300}
              autoComplete="off"
              onChange={(event) => {
                set({ location: event.target.value });
              }}
            />
            <TextField
              label={t("calendar.editor.notes.label")}
              value={draft.notes}
              maxLength={5000}
              autoComplete="off"
              onChange={(event) => {
                set({ notes: event.target.value });
              }}
            />
            <ChoiceRow
              label={t("calendar.editor.remind.label")}
              hint={t("calendar.editor.remind.hint")}
              choices={reminderChoices(defaultReminder, draft.reminders)}
              value={reminderValue(draft.reminders, draft.remindersOff, defaultReminder)}
              onChange={(value) => {
                // A pick replaces the set (R3): two reminders stay two until one is picked.
                const { reminders, off } = reminderPick(value);
                set({ reminders, remindersOff: off, remindChanged: true });
              }}
            />
          </>
        ) : null}
      </FormSection>
      <PanelActions>
        <Button type="submit" block pending={pending} disabled={!draft.title.trim()}>
          {editing ? t("calendar.editor.action.save") : t("calendar.editor.action.add")}
        </Button>
      </PanelActions>
    </form>
  );
}
