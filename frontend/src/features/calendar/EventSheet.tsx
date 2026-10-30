import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { qk } from "../../api/keys";
import { addDays, formatWallRange, shortDate, zonedParts } from "../../lib/dates";
import type { BoardPanel } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { askForPin } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { useMinute } from "../../lib/time";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { DayField } from "../../ui/DayField";
import { SidePanel } from "../../ui/SidePanel";
import { useShell } from "../../ui/shell";
import { useEventActions } from "../usePluginModules";
import { useCalendars, useEvent, useEventAt, useEventChanges } from "./data";
import { coreOverlayOf } from "./overlays";
import { ScopeChooser } from "./ScopeChooser";
import type { CalendarInfo, Occurrence, Scope } from "./types";

/** The occurrence a panel was opened from, as the board last loaded it. */
export function useCachedOccurrence(key: string | null): Occurrence | null {
  const queryClient = useQueryClient();
  if (!key) return null;
  for (const [, data] of queryClient.getQueriesData<{ occurrences: Occurrence[] }>({
    queryKey: ["occurrences"],
  })) {
    const found = data?.occurrences.find((o) => o.key === key);
    if (found) return found;
  }
  return null;
}

/** "Thu, Oct 9 · 4:00–5:00 PM", "Fri, Oct 9 · all day", "Thu, Oct 8 – Sat, Oct 10". */
export function whenText(occurrence: Occurrence): string {
  if (occurrence.all_day && occurrence.start_date && occurrence.end_date) {
    const last = addDays(occurrence.end_date, -1);
    return last === occurrence.start_date
      ? t("calendar.sheet.when.all_day", { date: shortDate(occurrence.start_date) })
      : `${shortDate(occurrence.start_date)} – ${shortDate(last)}`;
  }
  if (occurrence.start_local && occurrence.end_local) {
    const day = occurrence.start_local.slice(0, 10);
    const endDay = occurrence.end_local.slice(0, 10);
    const range = formatWallRange(occurrence.start_local, occurrence.end_local);
    return endDay === day
      ? `${shortDate(day)} · ${range}`
      : `${shortDate(day)} – ${shortDate(endDay)} · ${range}`;
  }
  return "";
}

/** A birthday's sheet says where it comes from (ADR 0028): "From Mia's birthday in Settings →
 * Family." */
export function birthdaySource(name: string | undefined): string {
  return name
    ? t("calendar.sheet.birthday.from", { name })
    : t("calendar.sheet.birthday.from_settings");
}

/** Where a synced event comes from, and where to change it (UX §4 "Event sheet"). The account's
 * name is the server's (`source_label`): the sentences around it are the page's. */
export function sourceLine(calendar: CalendarInfo, readOnly: boolean): string | null {
  const source = calendar.source_label;
  if (calendar.kind !== "sync" || !source) return null;
  if (!readOnly) return `${source} · ${calendar.name}`;
  if (source === "Holidays") return t("calendar.sheet.source.holidays");
  if (source === "a calendar address") {
    return t("calendar.sheet.source.address", { calendar: calendar.name });
  }
  // Where it changes: Apple's and Google's own apps, by name; any other account, itself.
  const app = source === "Apple" ? "apple" : source === "Google" ? "google" : "other";
  return t("calendar.sheet.source.change_there", { source, calendar: calendar.name, app });
}

/**
 * An event's sheet (UX §4 "Event sheet"): when, how it repeats, who, where, which calendar and
 * the notes, then Change, Move and Remove. A repeating event asks which ones. With Child-safe
 * editing on, Change and Remove on the wall screen ask for the parent PIN; Move doesn't.
 */
export function EventSheet({
  panel,
  onClose,
  onChange,
}: {
  panel: Extract<BoardPanel, { kind: "event" }> | null;
  onClose: () => void;
  onChange: (eventId: string, recurrenceId: string | null) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const occurrence = useCachedOccurrence(panel?.key ?? null);
  const { data: event } = useEvent(panel?.eventId ?? null);
  // A time changed on its own keeps its own notes (R2, ADR 0034); its place is the occurrence's.
  const { data: at } = useEventAt(
    panel?.eventId ?? null,
    occurrence?.recurrence_id ?? null,
    Boolean(occurrence?.is_override),
  );
  const notes = (occurrence?.is_override ? at?.description : undefined) ?? event?.description;
  const { data: members = [] } = useMembers();
  const { data: calendars = [] } = useCalendars();
  const { data: settings } = useSettings();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const changes = useEventChanges();
  const eventActions = useEventActions();
  const [moving, setMoving] = useState(false);
  const [asking, setAsking] = useState<null | { verb: "Remove" | "Move"; toDay?: string }>(null);
  const today = zonedParts(useMinute()).day;

  const title = occurrence?.title ?? event?.title ?? "";
  const people = members.filter((m) =>
    (occurrence?.member_ids ?? event?.member_ids ?? []).includes(m.id),
  );
  const calendar = calendars.find((c) => c.id === (occurrence?.calendar_id ?? event?.calendar_id));
  const repeats = occurrence?.is_recurring ?? Boolean(event?.rrule);
  const readOnly = occurrence?.read_only ?? event?.read_only ?? false;
  const birthday = occurrence !== null && coreOverlayOf(occurrence)?.key === "birthdays";
  const target = panel?.eventId
    ? { eventId: panel.eventId, recurrenceId: panel.recurrenceId }
    : null;
  const guarded =
    display &&
    session?.device_kind === "kiosk" &&
    !session.is_parent &&
    session.has_pin &&
    (settings?.kid_safe_editing ?? true);

  const close = () => {
    setMoving(false);
    setAsking(null);
    onClose();
  };
  const remove = (scope: Scope) => {
    if (!target) return;
    changes.remove.mutate({ target, scope, title }, { onSuccess: close });
  };
  const moveTo = (toDay: string, scope: Scope) => {
    if (!target) return;
    changes.move.mutate({ target, scope, toDate: toDay, title }, { onSuccess: close });
  };

  const text = display ? "text-d-body" : "text-body";
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const source = birthday
    ? birthdaySource(people[0]?.name)
    : calendar
      ? sourceLine(calendar, readOnly)
      : null;
  const pending = occurrence?.pending ?? event?.pending ?? false;
  // What the plugins add ("Add a countdown"): they don't change the event, so a read-only one
  // gets them too. Not a birthday: Countdowns counts those down by itself.
  const extras =
    occurrence && !birthday
      ? eventActions.map((Action, index) => (
          <Action key={index} occurrence={occurrence} onDone={close} />
        ))
      : [];
  const actions = readOnly ? (
    <div className="flex flex-col gap-3">
      <p className={soft}>{source ?? t("calendar.sheet.source.account")}</p>
      {extras.length ? <div className="flex flex-wrap gap-3">{extras}</div> : null}
    </div>
  ) : moving ? null : (
    <div className="flex flex-wrap gap-3">
      <Button
        variant="secondary"
        onClick={() => {
          void (async () => {
            if (guarded && !(await askForPin(t("calendar.sheet.pin.hint")))) return;
            if (panel?.eventId) onChange(panel.eventId, panel.recurrenceId);
          })();
        }}
      >
        {t("app.action.change")}
      </Button>
      <Button
        variant="secondary"
        onClick={() => {
          setMoving(true);
        }}
      >
        {t("calendar.event.action.move")}
      </Button>
      <Button
        variant="quiet-danger"
        onClick={() => {
          if (repeats) setAsking({ verb: "Remove" });
          else remove("all");
        }}
      >
        {t("app.action.remove")}
      </Button>
      {extras}
    </div>
  );

  return (
    <>
      <SidePanel open={panel !== null} title={title} onClose={close} footer={actions}>
        <div className="flex flex-col gap-4">
          {occurrence ? <p className={`${text} font-semibold`}>{whenText(occurrence)}</p> : null}
          {event?.repeat_text ? <p className={soft}>{event.repeat_text}</p> : null}
          {occurrence?.is_override ? <p className={soft}>{t("calendar.sheet.override")}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            {people.length ? (
              people.map((member) => (
                <span key={member.id} className={`flex items-center gap-2 ${text}`}>
                  <Avatar member={member} size="sm" />
                  {member.name}
                </span>
              ))
            ) : (
              <span className={`flex items-center gap-2 ${text}`}>
                <Avatar member={null} size="sm" />
                {t("calendar.everyone")}
              </span>
            )}
          </div>
          {occurrence?.location || event?.location ? (
            <p className={text}>{occurrence?.location ?? event?.location}</p>
          ) : null}
          {calendar && !readOnly ? <p className={soft}>{source ?? calendar.name}</p> : null}
          {pending ? (
            <p className={`${soft} font-semibold`}>{t("calendar.sheet.pending")}</p>
          ) : null}
          {notes ? <p className={`${text} whitespace-pre-wrap`}>{notes}</p> : null}
          {moving ? (
            <MovePicker
              weekStartsOn={settings?.week_starts_on ?? 6}
              today={today}
              onPick={(day) => {
                if (repeats) setAsking({ verb: "Move", toDay: day });
                else moveTo(day, "all");
              }}
              onCancel={() => {
                setMoving(false);
              }}
            />
          ) : null}
        </div>
      </SidePanel>
      <ScopeChooser
        open={asking !== null}
        verb={asking?.verb ?? "Remove"}
        title={title}
        repeatText={event?.repeat_text}
        onChoose={(scope) => {
          const pending = asking;
          setAsking(null);
          if (pending?.verb === "Move" && pending.toDay) moveTo(pending.toDay, scope);
          else remove(scope);
        }}
        onCancel={() => {
          setAsking(null);
        }}
      />
    </>
  );
}

/** Move to another day (UX §4): the week's days, Previous and Next week, or any date from a
 * month grid. A tap on a day moves it there. */
function MovePicker({
  today,
  weekStartsOn,
  onPick,
  onCancel,
}: {
  today: string;
  weekStartsOn: number;
  onPick: (day: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  return (
    <div className="flex flex-col gap-3 border-t border-line pt-4">
      <DayField
        label={t("calendar.sheet.move.label")}
        value={null}
        today={today}
        weekStartsOn={weekStartsOn}
        min={today}
        onChange={onPick}
      />
      <div>
        <Button variant="quiet" onClick={onCancel}>
          {t("calendar.event.action.dont_move")}
        </Button>
      </div>
    </div>
  );
}
