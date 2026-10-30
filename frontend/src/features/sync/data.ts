/**
 * Synced calendars' data (PLAN §11.2): the accounts with their calendars, and every change to
 * them. Adding needs a parent (lib/parent asks for the PIN on the wall screen); passwords and
 * keys are sent once and never come back.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { qk } from "../../api/keys";
import { formatTime } from "../../lib/dates";
import { t } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";

export type Account = components["schemas"]["AccountOut"];
export type RemoteCalendar = components["schemas"]["RemoteCalendarOut"];
export type IcsBody = components["schemas"]["IcsIn"];
export type HolidaysBody = components["schemas"]["HolidaysIn"];
export type CaldavBody = components["schemas"]["CaldavIn"];
/** A mapping change: only what's sent changes (``clear_owner`` makes it Everyone's). */
export type MappingBody = Omit<components["schemas"]["MappingIn"], "clear_owner"> & {
  clear_owner?: boolean;
};

export function useAccounts({ enabled = true } = {}) {
  return useQuery({
    queryKey: qk.syncAccounts(),
    queryFn: async () => unwrap(await api.GET("/api/calendar-sync/accounts")),
    enabled,
    staleTime: 30_000,
  });
}

export function useHolidayPlaces({ enabled = true } = {}) {
  return useQuery({
    queryKey: qk.holidayPlaces(),
    queryFn: async () => unwrap(await api.GET("/api/calendar-sync/holidays/places")),
    enabled,
    staleTime: Infinity,
  });
}

/** What a person calls where a calendar comes from: "Apple", "Google", "School". Apple and
 * Google are names in every language; Holidays is a word. */
export function sourceName(account: Account): string {
  if (account.provider === "holidays") return t("sync.source.holidays");
  if (account.provider === "google") return "Google";
  const address = account.address ?? "";
  if (address.includes("icloud.com")) return "Apple"; // iCloud, which the family knows as Apple
  if (address.includes("google.com")) return "Google";
  return account.label;
}

/** "Updated 9:10 AM", "Syncing…", or the quiet error (UX §8: never an error wall). */
export function statusLine(account: Account): string {
  if (account.syncing) return t("sync.status.syncing");
  if (account.status === "paused") return t("sync.status.paused");
  if (account.status === "needs_reconnect" || account.status === "error") {
    return account.last_error ?? t("sync.status.no_answer", { source: sourceName(account) });
  }
  const slow = account.provider === "ics" && sourceName(account) === "Google";
  if (!account.last_success_at) return t("sync.status.never");
  const time = formatTime(new Date(account.last_success_at));
  return slow ? t("sync.status.updated_slow", { time }) : t("sync.status.updated", { time });
}

export function useSyncChanges() {
  const queryClient = useQueryClient();
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["calendar-sync"] }),
      queryClient.invalidateQueries({ queryKey: ["calendars"] }),
      queryClient.invalidateQueries({ queryKey: ["occurrences"] }),
    ]);
  };

  const addIcs = useMutation({
    mutationFn: async (body: IcsBody) =>
      asParent(async () => unwrap(await api.POST("/api/calendar-sync/accounts/ics", { body }))),
    onSuccess: async (account) => {
      await refresh();
      showToast(t("sync.address.added.toast", { name: account.label }));
    },
  });

  const addHolidays = useMutation({
    mutationFn: async (body: HolidaysBody) =>
      asParent(async () =>
        unwrap(await api.POST("/api/calendar-sync/accounts/holidays", { body })),
      ),
    onSuccess: async () => {
      await refresh();
      showToast(t("sync.holidays.added.toast"));
    },
  });

  const addCaldav = useMutation({
    mutationFn: async (body: CaldavBody) =>
      asParent(async () => unwrap(await api.POST("/api/calendar-sync/accounts/caldav", { body }))),
    onSuccess: refresh,
  });

  const map = useMutation({
    mutationFn: async ({
      account,
      calendar,
      body,
    }: {
      account: string;
      calendar: string;
      body: MappingBody;
    }) =>
      asParent(async () =>
        unwrap(
          await api.PUT("/api/calendar-sync/accounts/{account_id}/calendars/{row_id}", {
            params: { path: { account_id: account, row_id: calendar } },
            body: { clear_owner: false, ...body },
          }),
        ),
      ),
    onSuccess: refresh,
  });

  const syncNow = useMutation({
    mutationFn: async (account: Account) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/{account_id}/sync", {
            params: { path: { account_id: account.id } },
          }),
        ),
      ),
    onSuccess: refresh,
  });

  const reconnect = useMutation({
    mutationFn: async ({
      account,
      password,
      url,
    }: {
      account: Account;
      password?: string;
      url?: string;
    }) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/{account_id}/reconnect", {
            params: { path: { account_id: account.id } },
            body: { app_password: password ?? null, url: url ?? null },
          }),
        ),
      ),
    onSuccess: async (account) => {
      await refresh();
      showToast(t("sync.reconnect.done.toast", { source: sourceName(account) }));
    },
  });

  const disconnect = useMutation({
    mutationFn: async (account: Account) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/calendar-sync/accounts/{account_id}", {
            params: { path: { account_id: account.id } },
          }),
        );
      });
      return account;
    },
    onSuccess: async (account) => {
      await refresh();
      showToast(t("sync.remove.done.toast", { name: account.label }));
    },
  });

  return { addIcs, addHolidays, addCaldav, map, syncNow, reconnect, disconnect, refresh };
}
