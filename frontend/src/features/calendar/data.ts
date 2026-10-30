/**
 * The calendar's data: occurrences for a range, calendars, one event, and every change
 * (PLAN §7, §11.1). Changes refresh the board and say what happened in a toast with Undo
 * (UX §2 "Buttons and their toasts"); live updates refresh other screens (lib/eventRouter.ts).
 * On the wall screen, changing or removing may ask for the parent PIN (lib/parent.ts).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { shortWeekday } from "../../lib/dates";
import { t } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { useCalendarOverlays } from "../usePluginModules";
import { CORE_OVERLAYS } from "./overlays";
import type { CalendarEvent, CalendarInfo, Change, EventFields, Scope } from "./types";

/** Occurrences in [from, to). The board asks for `overlays` too: the core's birthdays, and what
 * the plugins that are on add to its days (meals, countdowns). */
export function useOccurrences(
  from: string,
  to: string,
  { enabled = true, overlays = false }: { enabled?: boolean; overlays?: boolean } = {},
) {
  const added = useCalendarOverlays();
  const keys = overlays
    ? [...CORE_OVERLAYS.map((overlay) => overlay.key), ...added.map((overlay) => overlay.key)]
    : [];
  return useQuery({
    queryKey: qk.occurrences(from, to, keys),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/calendar/occurrences", {
          params: { query: { from, to, ...(keys.length ? { overlays: keys } : {}) } },
        }),
      ),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCalendars(removed = false) {
  return useQuery({
    queryKey: qk.calendars(removed),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/calendar/calendars", {
          params: { query: { include_removed: removed } },
        }),
      ),
    staleTime: 60_000,
  });
}

/** The calendars a new event can go to: a local one, or a synced one that isn't read-only. */
export function takesEvents(calendar: CalendarInfo): boolean {
  return !calendar.read_only && !calendar.deleted;
}

/** A calendar's name among choices: a synced one names its account first ("Apple · Family"), as
 * an event's sheet does, so two calendars with one name can be told apart. */
export function calendarChoiceLabel(calendar: CalendarInfo): string {
  return calendar.kind === "sync" && calendar.source_label
    ? `${calendar.source_label} · ${calendar.name}`
    : calendar.name;
}

export function useEvent(eventId: string | null) {
  return useQuery({
    queryKey: qk.event(eventId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/calendar/events/{event_id}", {
          params: { path: { event_id: eventId ?? "" } },
        }),
      ),
    enabled: eventId !== null,
  });
}

/**
 * One occurrence as the editor and the sheet should read it (R2, ADR 0034): its own row when it
 * was changed on its own (its title, place, notes, reminders), else the series. Only asked for
 * an occurrence that is changed (`enabled`).
 */
export function useEventAt(eventId: string | null, recurrenceId: string | null, enabled = true) {
  return useQuery({
    queryKey: qk.eventAt(eventId ?? "", recurrenceId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/calendar/events/{event_id}/occurrences/{recurrence_id}", {
          params: { path: { event_id: eventId ?? "", recurrence_id: recurrenceId ?? "" } },
        }),
      ),
    enabled: enabled && eventId !== null && recurrenceId !== null,
  });
}

export function useRemovedEvents() {
  return useQuery({
    queryKey: qk.removedEvents(),
    queryFn: async () => unwrap(await api.GET("/api/calendar/removed")),
  });
}

export function useEventSearch(query: string) {
  const words = query.trim();
  return useQuery({
    queryKey: qk.eventSearch(words),
    queryFn: async () =>
      unwrap(await api.GET("/api/calendar/search", { params: { query: { q: words } } })),
    enabled: words.length >= 2,
    placeholderData: keepPreviousData,
  });
}

export interface Target {
  /** The series (an occurrence's event_id). */
  eventId: string;
  /** The occurrence, for a repeating event; null for the whole series. */
  recurrenceId: string | null;
}

async function refresh(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["occurrences"] }),
    queryClient.invalidateQueries({ queryKey: ["event"] }),
    queryClient.invalidateQueries({ queryKey: qk.removedEvents() }),
  ]);
}

/** Every change to events, each followed by a toast that can undo it. */
export function useEventChanges() {
  const queryClient = useQueryClient();

  const undo = async (eventId: string, change: Change) => {
    await asParent(async () =>
      unwrap(
        await api.POST("/api/calendar/events/{event_id}/undo", {
          params: { path: { event_id: eventId } },
          body: { revision_id: change.revision_id },
        }),
      ),
    );
    await refresh(queryClient);
  };

  const announce = (message: string, eventId: string, change: Change) => {
    showToast(message, {
      label: t("app.action.undo"),
      onAction: () => {
        void undo(eventId, change).catch(() => {
          showToast(t("calendar.change.undo_failed.toast"));
        });
      },
    });
  };

  const add = useMutation({
    mutationFn: async (body: EventFields & { title: string }) =>
      unwrap(await api.POST("/api/calendar/events", { body })),
    onSuccess: async (change) => {
      await refresh(queryClient);
      if (change.event) {
        announce(
          t("calendar.change.added.toast", { title: change.event.title }),
          change.event.id,
          change,
        );
      }
    },
  });

  const save = useMutation({
    mutationFn: async ({
      target,
      scope,
      fields,
    }: {
      target: Target;
      scope: Scope;
      fields: EventFields & { clear_rrule?: boolean; clear_color?: boolean };
    }) =>
      asParent(async () =>
        target.recurrenceId && scope !== "all"
          ? unwrap(
              await api.PATCH("/api/calendar/events/{event_id}/occurrences/{recurrence_id}", {
                params: {
                  path: { event_id: target.eventId, recurrence_id: target.recurrenceId },
                },
                body: { clear_rrule: false, clear_color: false, ...fields, scope },
              }),
            )
          : unwrap(
              await api.PATCH("/api/calendar/events/{event_id}", {
                params: { path: { event_id: target.eventId } },
                body: { clear_rrule: false, clear_color: false, ...fields, scope: "all" },
              }),
            ),
      ),
    onSuccess: async (change, { target }) => {
      await refresh(queryClient);
      announce(t("calendar.change.saved.toast"), target.eventId, change);
    },
  });

  const remove = useMutation({
    mutationFn: async ({
      target,
      scope,
      title,
    }: {
      target: Target;
      scope: Scope;
      title: string;
    }) => {
      const change = await asParent(async () =>
        target.recurrenceId && scope !== "all"
          ? unwrap(
              await api.DELETE("/api/calendar/events/{event_id}/occurrences/{recurrence_id}", {
                params: {
                  path: { event_id: target.eventId, recurrence_id: target.recurrenceId },
                  query: { scope },
                },
              }),
            )
          : unwrap(
              await api.DELETE("/api/calendar/events/{event_id}", {
                params: { path: { event_id: target.eventId } },
              }),
            ),
      );
      return { change, title };
    },
    onSuccess: async ({ change, title }, { target }) => {
      await refresh(queryClient);
      announce(t("calendar.change.removed.toast", { title }), target.eventId, change);
    },
  });

  const move = useMutation({
    mutationFn: async ({
      target,
      scope,
      toDate,
    }: {
      target: Target;
      scope: Scope;
      toDate: string;
      title: string;
    }) =>
      unwrap(
        await api.POST("/api/calendar/events/{event_id}/move", {
          params: { path: { event_id: target.eventId } },
          body: { to_date: toDate, recurrence_id: target.recurrenceId, scope },
        }),
      ),
    onSuccess: async (change, { target, toDate, title }) => {
      await refresh(queryClient);
      announce(
        t("calendar.change.moved.toast", { title, day: shortWeekday(toDate) }),
        target.eventId,
        change,
      );
    },
  });

  const restore = useMutation({
    mutationFn: async (event: CalendarEvent) =>
      unwrap(
        await api.POST("/api/calendar/events/{event_id}/restore", {
          params: { path: { event_id: event.id } },
        }),
      ),
    onSuccess: async (change, event) => {
      await refresh(queryClient);
      announce(t("calendar.change.restored.toast", { title: event.title }), event.id, change);
    },
  });

  return { add, save, remove, move, restore };
}
