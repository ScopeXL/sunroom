import { QueryCache, QueryClient } from "@tanstack/react-query";
import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";

import { api, ApiError, unwrap } from "./api/client";
import { qk } from "./api/keys";
import { JoinScreen } from "./features/auth/JoinScreen";
import { SignInScreen } from "./features/auth/SignInScreen";
import { WhoScreen, type WhoFrom } from "./features/auth/WhoScreen";
import { CalendarRoom } from "./features/calendar/CalendarRoom";
import { DisplayEntry } from "./features/display/DisplayEntry";
import { InstallScreen } from "./features/onboarding/InstallScreen";
import { SIGNED_IN_STEPS, SetupWizard, type SetupStep } from "./features/onboarding/SetupWizard";
import { CalendarScreen } from "./features/phone/CalendarScreen";
import { MoreScreen } from "./features/phone/MoreScreen";
import { PairDisplayScreen } from "./features/phone/PairDisplayScreen";
import { PluginRoomScreen, splitPath } from "./features/PluginRoomScreen";
import { TodayScreen } from "./features/phone/TodayScreen";
import { SettingsIndex, SettingsPageScreen } from "./features/settings/SettingsScreens";
import { Uninstalling } from "./features/settings/UninstallSheet";
import { setSignedOutHandler } from "./lib/live";
import { shouldShowInstallFirst } from "./lib/platform";
import { uninstalling } from "./lib/screenAgent";
import { fetchSession, rememberSignedIn, signedInBefore, type Session } from "./lib/session";
import { useStore } from "./lib/store";
import { PhoneShell } from "./shell/PhoneShell";
import { ShellLayout } from "./shell/ShellLayout";
import { useShell } from "./ui/shell";

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) handleSignedOut();
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (count, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
    mutations: { retry: 0 },
  },
});

export function handleSignedOut(): void {
  const session = queryClient.getQueryData<Session | null>(qk.session());
  rememberSignedIn(false);
  queryClient.setQueryData(qk.session(), null);
  // Signed out can mean the household started over (Erase everything, ADR 0029): ask again
  // whether Sunroom is set up, so the wall shows its welcome and a phone the wizard.
  void queryClient.invalidateQueries({ queryKey: qk.setupStatus() });
  // A wall screen that lost its sign-in shows its pair code again; a phone signs in again.
  void router.navigate({ to: session?.device_kind === "kiosk" ? "/display" : "/sign-in" });
}

async function currentSession(client: QueryClient): Promise<Session | null | "offline"> {
  try {
    return await client.query({
      queryKey: qk.session(),
      queryFn: fetchSession,
      staleTime: 30_000,
    });
  } catch {
    return "offline";
  }
}

async function setupComplete(client: QueryClient): Promise<boolean | "offline"> {
  try {
    const status = await client.query({
      queryKey: qk.setupStatus(),
      queryFn: async () => unwrap(await api.GET("/api/setup/status")),
      staleTime: 30_000,
    });
    return status.setup_complete;
  } catch {
    return "offline";
  }
}

/** Every page; while Sunroom Screen removes itself (This Screen's Uninstall, ADR 0042) only its
 * cover, whatever the route does underneath as the screen is unpaired. */
function Root() {
  return useStore(uninstalling) ? <Uninstalling /> : <Outlet />;
}

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: Root,
});

/** Screens before signing in use the phone's look (they're opened on phones and laptops). */
function PublicLayout() {
  return (
    <PhoneShell tabs={false}>
      <Outlet />
    </PhoneShell>
  );
}

const publicRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "public",
  component: PublicLayout,
});

const STEPS: SetupStep[] = [
  "welcome",
  "password",
  "household",
  "place",
  "people",
  "pin",
  "calendars",
  "done",
];

const setupRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/setup",
  validateSearch: (search: Record<string, unknown>): { step?: SetupStep } =>
    STEPS.includes(search.step as SetupStep) ? { step: search.step as SetupStep } : {},
  beforeLoad: async ({ context, search }) => {
    const complete = await setupComplete(context.queryClient);
    if (complete !== true) return;
    const session = await currentSession(context.queryClient);
    const step = search.step ?? "welcome";
    if (session && session !== "offline" && SIGNED_IN_STEPS.includes(step)) return;
    throw redirect({ to: session && session !== "offline" ? "/" : "/sign-in" });
  },
  component: function Setup() {
    const { step } = setupRoute.useSearch();
    return <SetupWizard step={step ?? "welcome"} />;
  },
});

const installRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/install",
  validateSearch: (search: Record<string, unknown>): { from?: "more" } =>
    search.from === "more" ? { from: "more" } : {},
  component: InstallScreen,
});

const joinRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/join",
  beforeLoad: async ({ context }) => {
    const session = await currentSession(context.queryClient);
    if (session && session !== "offline") throw redirect({ to: "/" });
  },
  component: JoinScreen,
});

const signInRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/sign-in",
  beforeLoad: async ({ context }) => {
    if ((await setupComplete(context.queryClient)) === false) throw redirect({ to: "/setup" });
    const session = await currentSession(context.queryClient);
    if (session && session !== "offline") throw redirect({ to: "/" });
  },
  component: SignInScreen,
});

/** The wall screen's address: setup help, its pair code, or the board (and a preview of the
 * display shell in any other signed-in browser). */
const displayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/display",
  component: DisplayEntry,
});

const signedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "signed",
  beforeLoad: async ({ context }) => {
    const session = await currentSession(context.queryClient);
    if (session === "offline") {
      // A phone that signed in before opens offline; only a real 401 signs it out.
      if (signedInBefore()) return;
      throw redirect({ to: "/sign-in" });
    }
    if (!session) {
      if ((await setupComplete(context.queryClient)) === false) throw redirect({ to: "/setup" });
      if (shouldShowInstallFirst()) throw redirect({ to: "/install", search: {} });
      throw redirect({ to: "/sign-in" });
    }
  },
  component: ShellLayout,
});

/** "/": the board in the display shell, Today on a phone. */
function Home() {
  return useShell() === "display" ? <CalendarRoom /> : <TodayScreen />;
}

function Calendar() {
  return useShell() === "display" ? <CalendarRoom /> : <CalendarScreen />;
}

const homeRoute = createRoute({ getParentRoute: () => signedRoute, path: "/", component: Home });
const calendarRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/calendar",
  component: Calendar,
});
const moreRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/more",
  component: MoreScreen,
});
const pairRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/pair",
  component: PairDisplayScreen,
});
const whoRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/who",
  validateSearch: (search: Record<string, unknown>): { from?: WhoFrom } =>
    search.from === "more" || search.from === "settings" ? { from: search.from } : {},
  component: function Who() {
    const { from } = whoRoute.useSearch();
    return <WhoScreen from={from} />;
  },
});
const settingsRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/settings",
  component: function Settings() {
    return useShell() === "display" ? <SettingsPageScreen /> : <SettingsIndex />;
  },
});
const settingsPageRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/settings/$page",
  component: function SettingsPage() {
    const { page } = settingsPageRoute.useParams();
    return <SettingsPageScreen page={page} />;
  },
});

/** A plugin's room or tab (/lists, /chores/rewards); static addresses above win (PLAN §6.5). */
const roomRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/$room",
  component: function Room() {
    const { room } = roomRoute.useParams();
    return <PluginRoomScreen room={room} path={[]} />;
  },
});
const roomPathRoute = createRoute({
  getParentRoute: () => signedRoute,
  path: "/$room/$",
  component: function RoomPath() {
    const params = roomPathRoute.useParams();
    return <PluginRoomScreen room={params.room} path={splitPath(params._splat)} />;
  },
});

const routeTree = rootRoute.addChildren([
  publicRoute.addChildren([setupRoute, installRoute, joinRoute, signInRoute]),
  displayRoute,
  signedRoute.addChildren([
    homeRoute,
    calendarRoute,
    moreRoute,
    pairRoute,
    whoRoute,
    settingsRoute,
    settingsPageRoute,
    roomRoute,
    roomPathRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  scrollRestoration: true,
});

setSignedOutHandler(handleSignedOut);

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
