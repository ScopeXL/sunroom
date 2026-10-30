import { Link, useRouterState } from "@tanstack/react-router";
import { CalendarDays, Menu, Sun, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { usePluginRooms } from "../features/usePluginModules";
import { useDatePreferences, useHouseholdLanguage, useSettings } from "../lib/household";
import { useLiveUpdates } from "../lib/live";
import { useServerRestart } from "../lib/restart";
import { useServerUpdate } from "../lib/update";
import { MotionProvider } from "../lib/motion";
import { sunDay } from "../lib/sun";
import { applyAppearance, rememberAppearance } from "../lib/theme";
import { useMinute } from "../lib/time";
import { zonedParts } from "../lib/dates";
import { CelebrationLayer } from "../ui/Celebration";
import { ShellContext } from "../ui/shell";
import { OfflinePill, ToastRegion, UpdatePrompt } from "../ui/StatusLayer";

interface Tab {
  key: string;
  label: string;
  icon: LucideIcon;
}

// Today and Calendar, then the plugins' rooms until four tabs are used, then More (UX §3).
export const PLUGIN_TABS = 2;

// Screens opened from More keep More lit (Settings, Pair a display, Who's using this).
const UNDER_MORE = /^\/(more|settings|pair|who|install)(\/|$)/;

const TAB_LINK =
  "group flex min-h-(--tabbar-h) flex-col items-center justify-center gap-0.5 text-caption font-semibold text-ink-soft data-lit:text-ink data-[status=active]:text-ink";
const TAB_PILL =
  "flex h-7 w-12 items-center justify-center rounded-full group-data-lit:bg-ink group-data-lit:text-on-ink group-data-[status=active]:bg-ink group-data-[status=active]:text-on-ink";

function TabFace({ tab }: { tab: Tab }) {
  const Icon = tab.icon;
  return (
    <>
      {/* The active icon sits in a filled ink pill, a cue that isn't color alone. */}
      <span className={TAB_PILL}>
        <Icon aria-hidden="true" size={22} strokeWidth={2.25} />
      </span>
      <span>{tab.label}</span>
    </>
  );
}

/** Bottom tabs on phones (UX §3 "The phone shell"). */
export function TabBar() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const all = usePluginRooms();
  const rooms = all.slice(0, PLUGIN_TABS);
  // The rooms that don't fit in the tabs open from More, and keep it lit.
  const inMore = all
    .slice(PLUGIN_TABS)
    .some(({ key }) => pathname === `/${key}` || pathname.startsWith(`/${key}/`));
  return (
    <nav
      aria-label="Main"
      data-segmented=""
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] print:hidden"
    >
      <ul className="mx-auto flex max-w-xl">
        <li className="flex-1">
          <Link to="/" activeOptions={{ exact: true }} className={TAB_LINK}>
            <TabFace tab={{ key: "today", label: "Today", icon: Sun }} />
          </Link>
        </li>
        <li className="flex-1">
          <Link to="/calendar" className={TAB_LINK}>
            <TabFace tab={{ key: "calendar", label: "Calendar", icon: CalendarDays }} />
          </Link>
        </li>
        {rooms.map((room) => (
          <li key={room.key} className="flex-1">
            <Link to="/$room" params={{ room: room.key }} className={TAB_LINK}>
              <TabFace tab={room} />
            </Link>
          </li>
        ))}
        <li className="flex-1">
          <Link
            to="/more"
            data-lit={UNDER_MORE.test(pathname) || inMore ? "" : undefined}
            className={TAB_LINK}
          >
            <TabFace tab={{ key: "more", label: "More", icon: Menu }} />
          </Link>
        </li>
      </ul>
    </nav>
  );
}

/** A phone's shell: the screen above, the tabs below; theme follows the phone on Auto. */
export function PhoneShell({ children, tabs = true }: { children: ReactNode; tabs?: boolean }) {
  // Screens before signing in (no tabs) have no stream to open.
  useLiveUpdates(tabs);
  useServerUpdate();
  useServerRestart();
  useDatePreferences({ enabled: tabs });
  useHouseholdLanguage({ enabled: tabs });
  const { data: settings } = useSettings({ enabled: tabs });
  const now = useMinute();
  const { day, hour, minute } = zonedParts(now);
  const minuteOfDay = hour * 60 + minute;
  useEffect(() => {
    if (!settings) return;
    const sun = sunDay(day, settings.latitude, settings.longitude);
    const shown = applyAppearance(
      {
        theme: settings.theme,
        daylightTint: settings.daylight_tint,
        textSize: "standard",
        reduceMotion: false,
        display: false,
        sun,
      },
      minuteOfDay,
    );
    // The next page paints this first (public/theme-boot.js, ADR 0032).
    rememberAppearance(shown, {
      choice: settings.theme,
      daylightTint: settings.daylight_tint,
      sun,
    });
  }, [settings, day, minuteOfDay]);
  return (
    <ShellContext.Provider value="phone">
      <MotionProvider reduceMotion={false}>
        <div data-shell="phone" className="min-h-dvh bg-wall text-ink">
          {children}
        </div>
        {tabs ? <TabBar /> : null}
        <CelebrationLayer />
        <OfflinePill />
        <ToastRegion />
        <UpdatePrompt />
      </MotionProvider>
    </ShellContext.Provider>
  );
}
