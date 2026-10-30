/** The household's settings, people and the display's layout, as queries every screen shares. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useRef } from "react";

import { api, notSaved, unwrap } from "../api/client";
import { qk } from "../api/keys";
import type { components } from "../api/schema";
import { setDatePreferences } from "./dates";
import { useFollowLanguage } from "./lang";
import { asParent } from "./parent";
import { refreshMinute } from "./time";
import { showToast } from "./toast";

export type HouseholdSettings = components["schemas"]["SettingsOut"];
export type SettingsChange = components["schemas"]["SettingsUpdate"];
export type Member = components["schemas"]["MemberOut"];

export function useSettings({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.settings(),
    queryFn: async () => unwrap(await api.GET("/api/settings")),
    staleTime: 30_000,
    enabled,
  });
}

/**
 * Every date and time on screen in the household's zone and its 12- or 24-hour choice
 * (Settings → Household), never the device's (PLAN §7.2). Each shell mounts it once. When the
 * zone changes while a screen is open everything is fetched again, because the server writes
 * local times in the household's zone.
 */
export function useDatePreferences({ enabled = true }: { enabled?: boolean } = {}): void {
  const { data: settings } = useSettings({ enabled });
  const queryClient = useQueryClient();
  const timezone = settings?.timezone;
  const timeFormat = settings?.time_format;
  const shownZone = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!timezone || !timeFormat) return;
    setDatePreferences({ timezone, timeFormat });
    refreshMinute();
    if (shownZone.current !== null && shownZone.current !== timezone) {
      void queryClient.invalidateQueries();
    }
    shownZone.current = timezone;
  }, [timezone, timeFormat, queryClient]);
}

/**
 * Every page of the household in its language (Settings → Household → Language, ADR 0043), a
 * change reaching every screen at once with `settings.changed`. Each shell mounts it once, as
 * `useDatePreferences`; a device with a language of its own keeps it (lib/lang).
 */
export function useHouseholdLanguage({ enabled = true }: { enabled?: boolean } = {}): void {
  const { data: settings } = useSettings({ enabled });
  useFollowLanguage(settings?.language);
}

/**
 * Change household settings (parent-only; the wall screen asks for the PIN first). Settings save
 * themselves (ADR 0029): what's on screen changes at once, and a refusal puts it back and says
 * "Not saved — …" in a toast. No page keeps a Save button or an error line of its own.
 */
export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (change: SettingsChange) =>
      asParent(async () => unwrap(await api.PATCH("/api/settings", { body: change }))),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey: qk.settings() });
      const before = queryClient.getQueryData<HouseholdSettings>(qk.settings());
      if (before) {
        queryClient.setQueryData<HouseholdSettings>(qk.settings(), {
          ...before,
          ...optimistic(change),
        });
      }
      return { before };
    },
    onError: (error, _change, context) => {
      if (context?.before) queryClient.setQueryData(qk.settings(), context.before);
      showToast(notSaved(error));
    },
    onSuccess: (settings) => {
      queryClient.setQueryData(qk.settings(), settings);
    },
  });
}

/** A change as it will read back, for the moment before the server answers. Callers send only
 * the fields they change; null (sleep turned off) is a value the settings can hold. */
function optimistic(change: SettingsChange): Partial<HouseholdSettings> {
  return change as unknown as Partial<HouseholdSettings>;
}

export function useMembers(archived = false) {
  return useQuery({
    queryKey: qk.members(archived),
    queryFn: async () => unwrap(await api.GET("/api/members", { params: { query: { archived } } })),
    staleTime: 30_000,
  });
}

export function usePlugins() {
  return useQuery({
    queryKey: qk.plugins(),
    queryFn: async () => unwrap(await api.GET("/api/plugins")),
    staleTime: 60_000,
  });
}
