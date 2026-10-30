/**
 * Needs Attention (ADR 0034): what needs a parent, from GET /api/problems. Asked again when a
 * live event says something changed (lib/eventRouter), and every 5 minutes for the two causes
 * no event announces (a backup at 3:30 AM, a filling disk).
 */
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import type { components } from "../../api/schema";
import { formatTime, shortDate, zonedParts } from "../../lib/dates";
import { t, useT, type Key } from "../../lib/lang";
import { SETTINGS_PAGES } from "../settings/pages";
import { usePluginModulesState } from "../usePluginModules";

export type Problem = components["schemas"]["ProblemOut"];

const EVERY_MS = 5 * 60_000;

export function useProblems() {
  return useQuery({
    queryKey: qk.problems(),
    queryFn: async () => unwrap(await api.GET("/api/problems")).problems,
    refetchInterval: EVERY_MS,
  });
}

/** "Since 9:10 AM" today, "Since Tue, Oct 6, 9:10 AM" before; in the household's zone. */
export function sinceWords(since: string, now: Date): string {
  const moment = new Date(since);
  const day = zonedParts(moment).day;
  const today = zonedParts(now).day;
  return day === today
    ? t("problems.since.today", { time: formatTime(moment) })
    : t("problems.since.earlier", { day: shortDate(day), time: formatTime(moment) });
}

/** The Settings pages' titles by key, core's and the features' own: "Open Calendars & Accounts". */
export function usePageTitles(): (page: string | null | undefined) => string | null {
  const t = useT();
  const { modules } = usePluginModulesState();
  const titles = new Map<string, Key>([
    ...SETTINGS_PAGES.map(({ key, title }): [string, Key] => [key, title]),
    ...modules.flatMap((module) =>
      (module.settingsPages ?? []).map(({ key, title }): [string, Key] => [key, title]),
    ),
  ]);
  return (page) => {
    const title = page ? titles.get(page) : undefined;
    return title ? t(title) : null;
  };
}
