import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight, Lock, MonitorCog } from "lucide-react";
import { useId, type ReactNode } from "react";

import { api } from "../../api/client";
import { qk } from "../../api/keys";
import { sunroomName, useScreenAgent } from "../../lib/screenAgent";
import { fetchSession } from "../../lib/session";
import { RoomHeader } from "../../shell/roomHeader";
import { Button } from "../../ui/Button";
import { Screen } from "../../ui/Screen";
import { useShell } from "../../ui/shell";
import { AboutPage } from "./AboutPage";
import { BackupPage } from "./BackupPage";
import { CalendarsPage } from "./CalendarsPage";
import { DevicesPage } from "./DevicesPage";
import { DiscordButton } from "./DiscordButton";
import { DisplayPage } from "./DisplayPage";
import { FamilyPage } from "./FamilyPage";
import { FeaturesPage } from "./FeaturesPage";
import { HouseholdPage } from "./HouseholdPage";
import { RecentlyRemoved } from "./RecentlyRemoved";
import { SupportPage } from "./SupportPage";
import { ThisScreenPage } from "./ThisScreenPage";
import { usePluginModulesState } from "../usePluginModules";
import { SETTINGS_PAGES, type SettingsPageKey } from "./pages";
import { useProblems } from "../problems/data";

const PAGES: Record<SettingsPageKey, () => ReactNode> = {
  family: () => <FamilyPage />,
  features: () => <FeaturesPage />,
  calendars: () => <CalendarsPage />,
  display: () => <DisplayPage />,
  "this-screen": () => <ThisScreenPage />,
  household: () => <HouseholdPage />,
  devices: () => <DevicesPage />,
  removed: () => <RecentlyRemoved />,
  backup: () => <BackupPage />,
  support: () => <SupportPage />,
  about: () => <AboutPage />,
};

interface Page {
  key: string;
  title: string;
  render: () => ReactNode;
}

/** This Screen is the wall's own device, not the household's (ADR 0039): what its link and its
 * page say, apart from the pages every device and screen share. */
const THIS_SCREEN = "this-screen";
const DEVICE_HINT = "Network, updates and power";
const DEVICE_LEAD =
  "These settings are for this screen only: its network, updates and power. They don’t change Sunroom for anyone else.";

/** Core's pages, with the enabled plugins' own (Chores) after Calendars & accounts. This Screen
 * only where the wall's own Sunroom Screen answers (ADR 0035), first there (ADR 0039): never on a
 * phone. */
function usePages(): { pages: Page[]; ready: boolean } {
  const { modules, ready } = usePluginModulesState();
  const screenAgent = useScreenAgent();
  const core: Page[] = SETTINGS_PAGES.filter(
    (page) => page.key !== THIS_SCREEN || screenAgent !== null,
  ).map((page) => ({ ...page, render: PAGES[page.key] }));
  const plugins: Page[] = modules.flatMap((module) =>
    (module.settingsPages ?? []).map(({ key, title, Page }) => ({
      key,
      title,
      render: () => <Page />,
    })),
  );
  const at = core.findIndex((page) => page.key === "calendars") + 1;
  return { pages: [...core.slice(0, at), ...plugins, ...core.slice(at)], ready };
}

/** The pages Needs Attention points at (ADR 0034): each gets a small dot in the list. */
function useFlagged(): ReadonlySet<string> {
  const { data: problems = [] } = useProblems();
  return new Set(problems.flatMap((problem) => (problem.page ? [problem.page] : [])));
}

/** The dot beside a page that needs attention; its link says so in words (`flagName`). */
function Flag({ on }: { on: boolean }) {
  if (!on) return null;
  return <span aria-hidden="true" className="ml-3 size-2.5 shrink-0 rounded-full bg-alert" />;
}

/** "Calendars & Accounts, needs attention" for a screen reader, on a page with a problem. */
const flagName = (title: string, on: boolean) =>
  on ? { "aria-label": `${title}, needs attention` } : {};

/** Settings on a phone: the list of pages (UX §5), with the Sunroom Discord at the title's end. */
export function SettingsIndex() {
  const { pages } = usePages();
  const flagged = useFlagged();
  return (
    <Screen title="Settings" back="/more" corner={<DiscordButton kiosk={false} />}>
      <ul className="divide-y divide-line rounded-chip border border-line bg-surface">
        {pages.map((page) => (
          <li key={page.key}>
            <Link
              to="/settings/$page"
              params={{ page: page.key }}
              {...flagName(page.title, flagged.has(page.key))}
              className="press-row flex min-h-14 items-center justify-between px-4 text-row font-semibold"
            >
              <span className="flex min-w-0 items-center">
                {page.title}
                <Flag on={flagged.has(page.key)} />
              </span>
              <ChevronRight aria-hidden="true" className="text-ink-soft" />
            </Link>
          </li>
        ))}
      </ul>
    </Screen>
  );
}

/** One Settings page: full screen with Back on a phone, list and detail on the wall screen. With
 * none named (the wall's /settings), the first: This Screen where there is one, else Family. */
export function SettingsPageScreen({ page }: { page?: string }) {
  const display = useShell() === "display";
  const { pages, ready } = usePages();
  // A plugin's page waits for its plugin to load; an unknown one shows the first.
  const current =
    page === undefined
      ? pages[0]
      : (pages.find((p) => p.key === page) ?? (ready ? pages[0] : undefined));
  if (!current) return null;
  if (!display) {
    return (
      <Screen title={current.title} back="/settings">
        {current.render()}
      </Screen>
    );
  }
  return <DisplaySettings current={current} pages={pages} />;
}

function DisplaySettings({ current, pages }: { current: Page; pages: Page[] }) {
  const flagged = useFlagged();
  const hintId = useId();
  const device = pages.filter((page) => page.key === THIS_SCREEN);
  const household = pages.filter((page) => page.key !== THIS_SCREEN);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const lock = useMutation({
    mutationFn: async () => {
      await api.POST("/api/auth/pin/lock");
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.session() });
      await navigate({ to: session?.device_kind === "kiosk" ? "/display" : "/" });
    },
  });
  return (
    <div className="flex min-h-0 flex-1">
      {/* At the right: the Sunroom Discord, then Lock while a parent's grant lasts (ADR 0042). */}
      <RoomHeader
        title="Settings"
        controls={
          <div className="ml-auto flex items-center gap-3">
            <DiscordButton kiosk={session?.device_kind === "kiosk"} />
            {session?.grant_expires_at ? (
              <Button
                variant="secondary"
                onClick={() => {
                  lock.mutate();
                }}
              >
                <Lock aria-hidden="true" className="size-7" />
                Lock
              </Button>
            ) : null}
          </div>
        }
      />
      <nav
        aria-label="Settings"
        className="w-96 shrink-0 overflow-y-auto border-r border-line py-4"
      >
        {/* This Screen in a box of its own over a rule, then the household's pages under its
            Sunroom's name: this screen apart from what every device and screen share (ADR 0039). */}
        {device.length ? (
          <>
            <ul className="flex flex-col gap-1 border-b border-line px-3 pb-4">
              {device.map((page) => (
                <li key={page.key}>
                  <Link
                    to="/settings/$page"
                    params={{ page: page.key }}
                    aria-label={
                      flagged.has(page.key) ? `${page.title}, needs attention` : page.title
                    }
                    aria-describedby={hintId}
                    aria-current={page.key === current.key ? "page" : undefined}
                    className="press-row flex min-h-20 items-center gap-4 rounded-button-d border-2 border-line px-4 py-2 text-ink-soft aria-[current=page]:border-ink aria-[current=page]:bg-surface aria-[current=page]:text-ink"
                  >
                    <MonitorCog aria-hidden="true" className="size-9 shrink-0" />
                    <span className="flex min-w-0 flex-col">
                      <span className="flex items-center text-d-body font-semibold whitespace-nowrap">
                        {page.title}
                        <Flag on={flagged.has(page.key)} />
                      </span>
                      <span id={hintId} className="text-d-caption text-ink-soft">
                        {DEVICE_HINT}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <p className="px-7 pt-5 pb-2 text-d-secondary font-bold text-ink-soft">
              {sunroomName(session?.household_name)}
            </p>
          </>
        ) : null}
        {/* Inset from the rail: neighbouring targets keep 8 px apart (UX §1). */}
        <ul className="flex flex-col gap-1 px-3">
          {household.map((page) => (
            <li key={page.key}>
              <Link
                to="/settings/$page"
                params={{ page: page.key }}
                {...flagName(page.title, flagged.has(page.key))}
                aria-current={page.key === current.key ? "page" : undefined}
                className="press-row flex min-h-16 items-center rounded-button-d px-4 text-d-body font-semibold whitespace-nowrap text-ink-soft aria-[current=page]:bg-surface aria-[current=page]:text-ink"
              >
                {page.title}
                <Flag on={flagged.has(page.key)} />
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {/* Focusable, so a keyboard can scroll a long page with nothing in it to focus. */}
      <section
        aria-labelledby="settings-page"
        tabIndex={0}
        className="min-w-0 flex-1 overflow-y-auto px-10 py-8"
      >
        {current.key === THIS_SCREEN ? (
          <div className="mb-8 flex items-start gap-4">
            <MonitorCog aria-hidden="true" className="mt-0.5 size-10 shrink-0" />
            <div className="flex max-w-4xl flex-col gap-2">
              <h2 id="settings-page" className="text-d-title font-bold">
                {current.title}
              </h2>
              <p className="text-d-secondary text-ink-soft">{DEVICE_LEAD}</p>
            </div>
          </div>
        ) : (
          <h2 id="settings-page" className="mb-8 text-d-title font-bold">
            {current.title}
          </h2>
        )}
        <div className="max-w-4xl">{current.render()}</div>
      </section>
    </div>
  );
}
