import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { qk } from "../api/keys";
import { AddPanel } from "../features/calendar/AddPanel";
import { useReminders } from "../features/calendar/reminders";
import { TodayPanel } from "../features/calendar/TodayPanel";
import { usePluginRooms, useScreenOverlays } from "../features/usePluginModules";
import { TipsBar } from "../features/tips/TipsBar";
import { zonedParts } from "../lib/dates";
import {
  backToNow,
  displayState,
  editorOpen,
  forgetView,
  householdChose,
  idleHolds,
  rememberRoom,
  roomAtStart,
  setRemembering,
  updateDisplay,
} from "../lib/displayState";
import { useDatePreferences, useSettings } from "../lib/household";
import { idleFor, swallowFollowingClick, watchActivity, whenIdle } from "../lib/idle";
import { watchKeyboardFields } from "../lib/keyboard";
import { MotionProvider } from "../lib/motion";
import { useLiveUpdates } from "../lib/live";
import { useServerRestart } from "../lib/restart";
import { reloadFresh, useServerUpdate } from "../lib/update";
import { useScreenAgentEvents } from "../lib/screenAgent";
import { noteDimmer } from "../lib/dimmer";
import { dimmedTo, isNight } from "../lib/night";
import { askForPin, askPinOnlyWhen } from "../lib/parent";
import { watchPointer } from "../lib/pointer";
import { useQuietTheme } from "../lib/quietTheme";
import { fetchSession } from "../lib/session";
import { useStore } from "../lib/store";
import { sunDay } from "../lib/sun";
import {
  allowAppearanceMotion,
  applyAppearance,
  rememberAppearance,
  resolveTheme,
} from "../lib/theme";
import { useMinute } from "../lib/time";
import { setToastProfile } from "../lib/toast";
import { useKeepAwake } from "../lib/wakeLock";
import { CelebrationLayer } from "../ui/Celebration";
import { KeyboardHost } from "../ui/Keyboard";
import { PinDialog } from "../ui/PinDialog";
import { ShellContext } from "../ui/shell";
import { OfflinePill, ToastRegion, useAppUpdate } from "../ui/StatusLayer";
import { Header } from "./Header";
import { kioskCommands } from "./kioskCommands";
import { Night } from "./Night";
import { Rail } from "./Rail";

const BACK_TO_NOW_MS = 2 * 60_000;
const EDITOR_IDLE_MS = 10 * 60_000;
const SETTINGS_LOCK_MS = 2 * 60_000;
// The PIN pad rises for a refusal only this soon after a touch (lib/parent).
const PIN_AFTER_TOUCH_MS = 30_000;
const WAKE_MS = 2 * 60_000;
const NIGHTLY_UPDATE_HOUR = 3;
// The page's veil for each evening dim level (percent of full brightness).
const VEIL: Record<number, string> = { 60: "opacity-30", 40: "opacity-45", 20: "opacity-60" };

/** A tap woke the sleeping wall: tell the server, so the Pi's helper switches the panel on. */
function tellServerAwake(): void {
  void api.POST("/api/display/wake").catch(() => undefined);
}
const UPDATE_IDLE_MS = 10 * 60_000;

// The page has decided where it starts (below). Once per page load, not per mount: the kiosk
// remounts this shell between /display and the rooms.
let started = false;

/**
 * The wall display's shell (UX §3): the rail at one side, and beside it the header over the
 * board and the Today panel in landscape; the header, the Today band, the board and a bottom bar
 * in portrait. It keeps the shared screen in its
 * shared state (UX §1 "Idle, wake and reset"), sleeps on schedule (Night), acts on commands from
 * a parent's phone, takes a new version at night, and holds the on-screen keyboard and PIN pad.
 *
 * `home` is "/display" on a paired screen and "/" on a laptop (which has a real keyboard).
 */
export function DisplayShell({ home, children }: { home: "/display" | "/"; children: ReactNode }) {
  const kiosk = home === "/display";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const rooms = usePluginRooms();
  const screenOverlays = useScreenOverlays();
  const segment = pathname.split("/")[1] ?? "";
  const room = pathname.startsWith("/settings")
    ? "settings"
    : rooms.some((r) => r.key === segment)
      ? segment
      : "calendar";
  const inPluginRoom = room !== "settings" && room !== "calendar";
  const { data: settings } = useSettings();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const now = useMinute();
  const { panelShown, railCollapsed, panel } = useStore(displayState);
  // Woken at night (a tap, or a parent's Wake): awake for 2 minutes from the latest wake.
  const [awake, setAwake] = useState(false);
  const [wakes, setWakes] = useState(0);
  const update = useAppUpdate();
  useKeepAwake(kiosk);
  useLiveUpdates();
  useScreenAgentEvents();
  useServerUpdate();
  useServerRestart();
  useDatePreferences();
  useReminders();

  const { mutate: lockNow } = useMutation({
    mutationFn: async () => {
      await api.POST("/api/auth/pin/lock");
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.session() });
    },
  });

  const { day, hour, minute } = zonedParts(now);
  const minuteOfDay = hour * 60 + minute;
  const nightTime = isNight(settings?.sleep_from, settings?.sleep_to, hour, minute);
  const sleeping = nightTime && !awake;
  // The evening dim: the Pi's helper dims the panel itself; anywhere else the page draws a veil.
  const [dimmer] = useState(() => noteDimmer(window.location.search));
  const dim = nightTime
    ? null
    : dimmedTo(
        settings?.dim_from,
        settings?.sleep_from,
        settings?.sleep_to,
        settings?.dim_level ?? 40,
        hour,
        minute,
      );
  const latitude = settings?.latitude;
  const longitude = settings?.longitude;
  const sun = useMemo(() => sunDay(day, latitude, longitude), [day, latitude, longitude]);
  const theme = useQuietTheme(
    settings?.theme ?? null,
    settings ? resolveTheme(settings.theme, minuteOfDay, sun) : null,
  );

  // Theme, wall tint and text size follow the household's settings, the clock and the sun. What
  // was shown is kept for the next page's first paint (public/theme-boot.js), and the fades are
  // armed only once it's on (ADR 0032): armed sooner, a theme that came with the settings would
  // fade in from whatever the page painted first.
  const motionArmed = useRef(false);
  useEffect(() => {
    if (!settings || !theme) return;
    const shown = applyAppearance(
      {
        theme: nightTime ? "dark" : theme,
        daylightTint: settings.daylight_tint,
        textSize: settings.text_size,
        reduceMotion: settings.display_reduce_motion,
        display: true,
        sun,
      },
      minuteOfDay,
    );
    rememberAppearance(shown, {
      choice: settings.theme,
      daylightTint: settings.daylight_tint,
      sun,
    });
    if (!motionArmed.current) {
      motionArmed.current = true;
      allowAppearanceMotion();
    }
  }, [settings, theme, minuteOfDay, nightTime, sun]);

  useEffect(() => {
    setToastProfile(true);
    const stopActivity = watchActivity();
    const stopKeyboard = kiosk ? watchKeyboardFields() : () => undefined;
    // A paired screen hides a resting pointer; a laptop has a person behind its mouse.
    const stopPointer = kiosk ? watchPointer() : () => undefined;
    return () => {
      setToastProfile(false);
      stopActivity();
      stopKeyboard();
      stopPointer();
    };
  }, [kiosk]);

  // Where this screen starts (Settings → Display → When it starts, ADR 0030). Where it left
  // off: the view came back with the store (lib/displayState), and a page that opened at home
  // (the Pi's launcher always opens /display) goes back to the room it was in. The home view:
  // nothing is kept, and the page goes home. From then on the room is kept as it changes;
  // Settings never is (its PIN grant may be gone).
  const startMode = settings?.display_start;
  const atHome = pathname === "/" || pathname === "/display" || pathname === "/calendar";
  useEffect(() => {
    if (!startMode) return;
    setRemembering(startMode === "last");
    if (!started) {
      started = true;
      if (startMode === "home") {
        forgetView();
        if (!atHome) void navigate({ to: home, replace: true });
        return;
      }
      const [key, ...rest] = (roomAtStart() ?? "").slice(1).split("/");
      if (atHome && key) {
        void (rest.length
          ? navigate({ to: "/$room/$", params: { room: key, _splat: rest.join("/") } })
          : navigate({ to: "/$room", params: { room: key } }));
        return;
      }
    }
    // Not while the rooms are still loading: an address isn't known to be a room until then.
    if (atHome) rememberRoom(null);
    else if (inPluginRoom) rememberRoom(pathname);
  }, [startMode, atHome, inPluginRoom, pathname, home, navigate]);

  // After 2 minutes idle the board goes back to now, in the view, panel and rail this screen
  // chose (ADR 0031); an editor left open gets 10 minutes before it closes too (UX §1 "Undo,
  // drafts").
  useEffect(
    () =>
      whenIdle(BACK_TO_NOW_MS, () => {
        if (!editorOpen()) backToNow();
      }),
    [],
  );
  useEffect(() => whenIdle(EDITOR_IDLE_MS, backToNow), []);

  // A change in Settings → Display wins over this screen's own choice of the same thing.
  useEffect(() => {
    if (!settings) return;
    householdChose({
      homeView: settings.display_home_view,
      weekLayout: settings.display_week_layout,
      todayPanel: settings.display_show_today_panel,
      compactRail: settings.display_rail_compact,
    });
  }, [settings]);

  // Settings' parent grant locks after 2 minutes idle (looking never needed it; a change asks
  // the PIN again). The page itself leaves with the other rooms, below (ADR 0034 narrows 0031).
  useEffect(() => {
    if (room !== "settings") return;
    return whenIdle(SETTINGS_LOCK_MS, () => {
      if (session?.grant_expires_at) lockNow();
    });
  }, [room, session?.grant_expires_at, lockNow]);
  // So a page left open behind the lock never raises the PIN pad by itself.
  useEffect(() => askPinOnlyWhen(() => idleFor() < PIN_AFTER_TOUCH_MS), []);

  // Lists, Tasks, Settings and the other rooms return to the board after the household's minutes
  // idle (UX §1; 0 is Never, which Settings honours too since ADR 0034), unless something holds
  // the screen (a routine being run).
  const returnMinutes = settings?.display_return_minutes ?? 5;
  const leaves = inPluginRoom || room === "settings";
  useEffect(() => {
    if (!leaves || returnMinutes <= 0) return;
    return whenIdle(returnMinutes * 60_000, () => {
      if (idleHolds.get() > 0) return;
      updateDisplay({ panel: null });
      void navigate({ to: home });
    });
  }, [leaves, returnMinutes, home, navigate]);

  // A new version waits for the night (3 AM), and for a quiet screen, before it reloads.
  useEffect(() => {
    if (!kiosk || !update.ready) return;
    if (hour === NIGHTLY_UPDATE_HOUR && idleFor() >= UPDATE_IDLE_MS) update.apply();
  }, [kiosk, update, hour]);

  // Commands from a parent's phone (POST /api/kiosk/command).
  useEffect(
    () =>
      kioskCommands.subscribe(() => {
        const command = kioskCommands.get()?.command;
        if (command === "reload") void reloadFresh();
        if (command === "wake") {
          setAwake(true);
          setWakes((n) => n + 1);
          if (kiosk) tellServerAwake();
        }
      }),
    [kiosk],
  );

  // Back to sleep 2 minutes after the latest wake.
  useEffect(() => {
    if (!awake) return;
    const timer = setTimeout(() => {
      setAwake(false);
    }, WAKE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [awake, wakes]);

  const openSettings = async () => {
    if (room === "settings") {
      if (session?.grant_expires_at) lockNow();
      await navigate({ to: home });
      return;
    }
    if (!session?.is_parent && !(await askForPin())) return;
    // Settings' first page: This Screen on a wall run by Sunroom Screen, else Family (ADR 0039).
    await navigate({ to: "/settings" });
  };

  // In every room, Settings included: its pages are capped at a reading width anyway.
  const showPanel = panelShown ?? settings?.display_show_today_panel ?? true;
  const railSide = settings?.display_rail_side ?? "left";
  // Folded to its icons on this screen, or by the household's setting, whichever came last.
  const railCompact = railCollapsed ?? settings?.display_rail_compact ?? false;
  const mirrored = railSide === "right" ? "landscape:flex-row-reverse" : "";

  return (
    <ShellContext.Provider value="display">
      <MotionProvider reduceMotion={settings?.display_reduce_motion ?? false}>
        <div
          data-shell="display"
          data-rail={railCompact ? "compact" : "full"}
          className={`flex h-dvh overflow-clip bg-wall text-ink landscape:flex-row portrait:flex-col ${mirrored}`}
        >
          <div className="contents portrait:order-last portrait:block">
            <Rail
              home={home}
              room={room}
              rooms={rooms}
              lock={
                session?.grant_expires_at
                  ? "unlocked"
                  : session?.has_pin === false || (!kiosk && session?.is_parent === true)
                    ? "open"
                    : "locked"
              }
              compact={railCompact}
              side={railSide}
              settled={settings !== undefined}
              onAdd={() => {
                if (room === "settings") void navigate({ to: home });
                updateDisplay({ panel: { kind: "add", day: null, hour: null } });
              }}
              onLock={() => {
                void openSettings();
              }}
            />
          </div>
          {/* The <header> stays under plain divs: inside main, section, aside or nav it would
              stop being the page's banner. */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Header
              panelShown={showPanel}
              onTogglePanel={() => {
                updateDisplay({ panelShown: !showPanel });
              }}
              railCompact={railCompact}
              railSide={railSide}
              onFoldRail={(compact) => {
                updateDisplay({ railCollapsed: compact });
              }}
            />
            {showPanel ? (
              <div className="hidden portrait:flex portrait:h-[var(--band-h)] portrait:shrink-0 portrait:flex-col portrait:overflow-clip portrait:border-b portrait:border-line portrait:bg-surface">
                <TodayPanel home={home} band />
              </div>
            ) : null}
            <div
              className={`flex min-h-0 min-w-0 flex-1 landscape:flex-row portrait:flex-col ${mirrored}`}
            >
              <main className="flex min-h-0 min-w-0 flex-1 flex-col pb-[var(--osk-h,0px)]">
                {children}
                <TipsBar />
              </main>
              <TodaySide shown={showPanel} railSide={railSide} home={home} />
            </div>
          </div>
        </div>
        {inPluginRoom ? (
          <AddPanel
            panel={panel?.kind === "add" ? panel : null}
            today={zonedParts(now).day}
            room={room}
            onClose={() => {
              updateDisplay({ panel: null });
            }}
            onType={(type) => {
              if (panel?.kind === "add") updateDisplay({ panel: { ...panel, type } });
            }}
          />
        ) : null}
        <CelebrationLayer />
        <ToastRegion display railSide={railSide} panelShown={showPanel} />
        <OfflinePill display />
        {kiosk ? <KeyboardHost rail={railSide} /> : null}
        <PinDialog />
        {screenOverlays.map(({ id, Overlay }) => (
          <Overlay key={id} asleep={sleeping} home={home} />
        ))}
        {dim !== null && dimmer === "page" ? (
          <div
            aria-hidden="true"
            data-veil=""
            className={`pointer-events-none fixed inset-0 z-[58] bg-night ${VEIL[dim] ?? "opacity-45"}`}
          />
        ) : null}
        <Night
          sleeping={sleeping}
          mode={settings?.sleep_mode ?? "dim_clock"}
          onWake={() => {
            swallowFollowingClick();
            setAwake(true);
            setWakes((n) => n + 1);
            if (kiosk) tellServerAwake();
          }}
        />
      </MotionProvider>
    </ShellContext.Provider>
  );
}

/** How long what's in the Today panel stays while its box closes: a little over the 220 ms. */
const PANEL_CLOSES_MS = 300;

/**
 * The Today panel beside the board, in landscape. Shown or hidden, its box stays in the row: the
 * width eases between the panel's and nothing (UX §9 "The shell"; styles/motion.css), so the board
 * takes or gives the room rather than jumping. What's inside keeps its own width meanwhile, and
 * leaves once the box has closed. Never on first paint: the motion arrives a frame later.
 */
function TodaySide({
  shown,
  railSide,
  home,
}: {
  shown: boolean;
  railSide: "left" | "right";
  home: "/display" | "/";
}) {
  const [moves, setMoves] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setMoves(true);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, []);
  const [held, setHeld] = useState(shown);
  if (shown && !held) setHeld(true);
  useEffect(() => {
    if (shown || !held) return;
    const timer = setTimeout(() => {
      setHeld(false);
    }, PANEL_CLOSES_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [shown, held]);
  return (
    <div
      data-today-side={moves ? "" : undefined}
      inert={!shown}
      aria-hidden={shown ? undefined : true}
      className={`flex shrink-0 overflow-clip portrait:hidden ${shown ? "w-[var(--panel-w)]" : "w-0"}`}
    >
      {held ? (
        <div
          className={`flex w-[var(--panel-w)] shrink-0 flex-col border-line bg-surface ${
            railSide === "right" ? "border-r" : "border-l"
          }`}
        >
          <TodayPanel home={home} />
        </div>
      ) : null}
    </div>
  );
}
