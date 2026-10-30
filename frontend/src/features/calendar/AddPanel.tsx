import { useQueryClient } from "@tanstack/react-query";
import { CalendarDays } from "lucide-react";
import { useState } from "react";

import { addDays } from "../../lib/dates";
import type { BoardPanel } from "../../lib/displayState";
import { useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { Segmented } from "../../ui/Segmented";
import { SidePanel } from "../../ui/SidePanel";
import { useAddTypes } from "../usePluginModules";
import { useEvent, useEventAt, useEventChanges } from "./data";
import { EventEditor, draftFromEvent, draftToFields, type Draft } from "./EventEditor";
import { ScopeChooser } from "./ScopeChooser";
import type { CalendarEvent, EventFields, Occurrence, Scope } from "./types";

type EditorPanel = Extract<BoardPanel, { kind: "add" } | { kind: "edit" }>;

/** The occurrence a change was opened from, from the board's loaded weeks. */
export function useOccurrenceOf(
  eventId: string | null,
  recurrenceId: string | null,
): Occurrence | null {
  const queryClient = useQueryClient();
  if (!eventId) return null;
  for (const [, data] of queryClient.getQueriesData<{ occurrences: Occurrence[] }>({
    queryKey: ["occurrences"],
  })) {
    const found = data?.occurrences.find(
      (o) => o.event_id === eventId && (o.recurrence_id ?? null) === recurrenceId,
    );
    if (found) return found;
  }
  return null;
}

const dayDiff = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

/**
 * What a change sends at each scope. "This" can't repeat; "all" keeps the series' first day,
 * moved only as far as the occurrence's day moved, so a changed time doesn't restart the series.
 * "The person's color" on an event that had its own clears it: the server reads no color as
 * "leave it" (ADR 0034).
 */
export function fieldsFor(
  draft: Draft,
  scope: Scope,
  event: CalendarEvent,
  occurrence: Occurrence | null,
  weekStartsOn = 0,
): EventFields & { title: string; clear_rrule?: boolean; clear_color?: boolean } {
  const fields = {
    ...draftToFields(draft, { align: scope !== "this", weekStartsOn }),
    clear_color: draft.color === null && Boolean(event.color),
  };
  if (scope === "this") {
    const one = { ...fields };
    delete one.rrule;
    return one;
  }
  const clear = !fields.rrule && Boolean(event.rrule);
  if (scope === "following" || !occurrence) return { ...fields, clear_rrule: clear };
  const occurrenceDay = occurrence.start_date ?? occurrence.start_local?.slice(0, 10) ?? draft.day;
  const shift = dayDiff(occurrenceDay, draft.day);
  const seriesDay = event.start_date ?? event.start?.slice(0, 10) ?? draft.day;
  const day = addDays(seriesDay, shift);
  const moved = draftToFields(
    {
      ...draft,
      day,
      lastDay: draft.lastDay ? addDays(draft.lastDay, dayDiff(draft.day, day)) : null,
    },
    { weekStartsOn },
  );
  return { ...moved, clear_rrule: clear, clear_color: fields.clear_color };
}

/**
 * Add and the event editor (UX §4), in the wall's side panel or a phone's sheet. Adding offers
 * every kind of thing the enabled plugins make beside events, as one row of icons over their
 * words (Event, Item, Task, Meal, Countdown), with the room's own kind chosen first; `onType`
 * switches it, and each kind has its own form.
 */
export function AddPanel({
  panel,
  today,
  onClose,
  onDay,
  onType,
  room = "calendar",
}: {
  panel: EditorPanel | null;
  today: string;
  onClose: () => void;
  /** The day being added to or changed, for the board to light (UX §6). */
  onDay?: (day: string | null) => void;
  onType?: (type: string) => void;
  /** Where Add was opened: its kind of thing is chosen first. */
  room?: string;
}) {
  const t = useT();
  const types = useAddTypes();
  const weekStartsOn = useSettings().data?.week_starts_on ?? 6;
  const adding = panel?.kind === "add" ? panel : null;
  const chosen = adding?.type ?? types.find((type) => type.room === room)?.key ?? "event";
  const plugin = adding ? types.find((type) => type.key === chosen) : undefined;
  const editing = panel?.kind === "edit" ? panel : null;
  const { data: event } = useEvent(editing?.eventId ?? null);
  const occurrence = useOccurrenceOf(editing?.eventId ?? null, editing?.recurrenceId ?? null);
  // One occurrence changed on its own: the editor reads its own row (R2, ADR 0034).
  const changedAlone = Boolean(occurrence?.is_override);
  const ownRow = useEventAt(editing?.eventId ?? null, editing?.recurrenceId ?? null, changedAlone);
  const at = ownRow.data;
  const changes = useEventChanges();
  const [asking, setAsking] = useState<Draft | null>(null);
  const repeats = Boolean(event?.rrule);

  const save = (draft: Draft, scope: Scope) => {
    if (!editing || !event) return;
    changes.save.mutate(
      {
        target: { eventId: editing.eventId, recurrenceId: editing.recurrenceId },
        scope,
        fields: fieldsFor(
          draft,
          scope,
          // "Just this one" clears the color that one has, not the series'.
          scope === "this" && at?.is_override ? { ...event, color: at.color } : event,
          occurrence,
          weekStartsOn,
        ),
      },
      { onSuccess: onClose },
    );
  };
  const title = editing ? t("calendar.panel.change.title") : t("calendar.panel.add.title");
  // An occurrence's own row that won't load leaves the editor on the series' words, never blank.
  const ready =
    !editing || (event !== undefined && (!changedAlone || at !== undefined || ownRow.isError));
  // Every kind of thing Add makes: an event, then what the plugins that are on add.
  const kinds = [
    { value: "event", label: t("calendar.add.label"), icon: CalendarDays },
    ...types.map((type) => ({ value: type.key, label: t(type.label), icon: type.icon })),
  ];
  return (
    <>
      <SidePanel open={panel !== null} title={title} onClose={onClose} scrollKey={chosen}>
        {adding && types.length > 0 ? (
          <div className="mb-8">
            <Segmented
              stacked
              label={t("calendar.panel.kind.aria")}
              value={chosen}
              options={kinds}
              onChange={(type) => {
                onType?.(type);
              }}
            />
          </div>
        ) : null}
        {plugin && adding ? (
          <plugin.Editor
            key={plugin.key}
            day={adding.day}
            initialTitle={adding.title ?? null}
            onDone={onClose}
          />
        ) : panel && ready ? (
          <EventEditor
            key={editing ? `${editing.eventId}|${editing.recurrenceId ?? ""}` : "new"}
            initial={
              editing && event ? draftFromEvent(event, occurrence, weekStartsOn, at ?? null) : null
            }
            editing={editing !== null}
            today={today}
            defaultDay={panel.kind === "add" ? (panel.day ?? today) : today}
            defaultHour={panel.kind === "add" ? panel.hour : null}
            defaultMinute={panel.kind === "add" ? (panel.minute ?? null) : null}
            pending={changes.add.isPending || changes.save.isPending}
            {...(onDay ? { onDay } : {})}
            error={changes.add.error ?? changes.save.error}
            onSave={(draft) => {
              if (!editing) {
                changes.add.mutate(draftToFields(draft, { weekStartsOn }), { onSuccess: onClose });
              } else if (repeats && editing.recurrenceId) {
                setAsking(draft);
              } else {
                save(draft, "all");
              }
            }}
          />
        ) : null}
      </SidePanel>
      <ScopeChooser
        open={asking !== null}
        verb="Change"
        title={event?.title ?? ""}
        repeatText={event?.repeat_text}
        onChoose={(scope) => {
          const draft = asking;
          setAsking(null);
          if (draft) save(draft, scope);
        }}
        onCancel={() => {
          setAsking(null);
        }}
      />
    </>
  );
}
