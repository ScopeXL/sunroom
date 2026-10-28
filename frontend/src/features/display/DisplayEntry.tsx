import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { api, ApiError, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { isLoopbackAddress } from "../../lib/address";
import { zonedParts } from "../../lib/dates";
import { whenIdle, watchActivity } from "../../lib/idle";
import { watchKeyboardFields } from "../../lib/keyboard";
import { MotionProvider } from "../../lib/motion";
import { watchPointer } from "../../lib/pointer";
import { keepPairing } from "../../lib/screenAgent";
import { fetchSession, type Session } from "../../lib/session";
import {
  applyAppearance,
  REMEMBERED_FRESH_MS,
  rememberedAppearance,
  showAppearance,
} from "../../lib/theme";
import { useMinute } from "../../lib/time";
import { DisplayShell } from "../../shell/DisplayShell";
import { Button } from "../../ui/Button";
import { Choice } from "../../ui/Choice";
import { KeyboardHost } from "../../ui/Keyboard";
import { QrCode } from "../../ui/QrCode";
import { ShellContext } from "../../ui/shell";
import { Brand } from "../../ui/Brand";
import { ToastRegion } from "../../ui/ToastRegion";
import { TextField } from "../../ui/TextField";
import { CalendarRoom } from "../calendar/CalendarRoom";
import { SetupWizard, type SetupStep } from "../onboarding/SetupWizard";
import { ScreenNameFields } from "./ScreenName";

const PASSWORD_IDLE_MS = 60_000;
/** Ten minutes untouched leave the wall's own setup: to Set Up Sunroom while nothing is saved,
 * to the board once the household is, whatever is left being in Settings (ADR 0039). */
const SETUP_IDLE_MS = 10 * 60_000;

/** The wall's own setup (ADR 0039): the wizard's steps from the password on, and Name This
 * Screen before All Done! */
type WallStep = Exclude<SetupStep, "welcome"> | "name";

/**
 * What the wall screen shows at /display (PLAN §12.3, UX §4 "Welcome and Pair this screen"):
 * Set Up Sunroom when it isn't yet, here or on another device; its pair code when it isn't paired;
 * "Name this screen" right after pairing; then the board. Any other browser opening /display
 * after signing in gets the display shell as a preview (ADR 0014).
 */
export function DisplayEntry() {
  const { data: status } = useQuery({
    queryKey: qk.setupStatus(),
    queryFn: async () => unwrap(await api.GET("/api/setup/status")),
    refetchInterval: (query) => (query.state.data?.setup_complete ? false : 5000),
  });
  // Until the server answers, however long that takes: a paired screen reloaded while it's down
  // gave up after two tries, then showed Pair This Screen once it was back (ADR 0034).
  const { data: session, isPending } = useQuery({
    queryKey: qk.session(),
    queryFn: fetchSession,
    retry: (_count, error) =>
      !(error instanceof ApiError && error.status >= 400 && error.status < 500),
  });
  const [justPaired, setJustPaired] = useState(false);
  const [wallStep, setWallStep] = useState<WallStep | null>(null);

  if (!status || isPending) return <Frame>{null}</Frame>;
  // Setting up here: until another device finishes setup first, then as the screen it made.
  if (wallStep !== null && (!status.setup_complete || session?.device_kind === "kiosk")) {
    return (
      <Frame bare>
        <WallSetup
          step={wallStep}
          address={status.advertised_url}
          onStep={setWallStep}
          onLeave={() => {
            setWallStep(null);
          }}
        />
      </Frame>
    );
  }
  if (!status.setup_complete) {
    return (
      <Frame>
        <Welcome
          address={status.advertised_url}
          onSetUpHere={() => {
            setWallStep("password");
          }}
        />
      </Frame>
    );
  }
  if (!session) {
    return (
      <Frame>
        <PairThisScreen
          onPaired={() => {
            keepPairing();
            setWallStep(null);
            setJustPaired(true);
          }}
        />
      </Frame>
    );
  }
  if (justPaired && session.device_kind === "kiosk") {
    return (
      <Frame>
        <NameThisScreen
          onDone={() => {
            setJustPaired(false);
          }}
        />
      </Frame>
    );
  }
  return (
    <DisplayShell home="/display">
      <CalendarRoom />
    </DisplayShell>
  );
}

/**
 * The display's look and keyboard, for the screens shown before it's paired, and for the moment
 * a paired one spends finding out that it is. A page loaded soon after this browser last showed
 * the household's appearance keeps it exactly as the boot script put it (a refresh, the Pi's
 * nightly restart: ADR 0032). A screen off for a while follows the household's choices by its
 * clock, and one that never knew the household guesses: Auto, dark from 7 PM.
 */
function Frame({
  children,
  bare = false,
}: {
  children: ReactNode;
  /** The wall's own setup: its steps lay themselves out, as on a phone (SetupFrame). */
  bare?: boolean;
}) {
  const { hour, minute } = zonedParts(useMinute());
  const minuteOfDay = hour * 60 + minute;
  useEffect(() => {
    const known = rememberedAppearance();
    if (known && Date.now() - known.at < REMEMBERED_FRESH_MS) {
      showAppearance(known);
      return;
    }
    applyAppearance(
      {
        theme: known?.choice ?? "auto",
        daylightTint: known?.daylightTint ?? true,
        textSize: known?.textSize ?? "standard",
        reduceMotion: known?.reduceMotion ?? false,
        display: true,
        ...(known?.sun ? { sun: known.sun } : {}),
      },
      minuteOfDay,
    );
  }, [minuteOfDay]);
  useEffect(() => {
    const stopActivity = watchActivity();
    const stopKeyboard = watchKeyboardFields();
    const stopPointer = watchPointer();
    return () => {
      stopActivity();
      stopKeyboard();
      stopPointer();
    };
  }, []);
  return (
    <ShellContext.Provider value="display">
      <MotionProvider reduceMotion={false}>
        {bare ? (
          <div data-shell="display" className="min-h-dvh bg-wall text-ink">
            {children}
          </div>
        ) : (
          <main
            data-shell="display"
            className="flex min-h-dvh flex-col items-center justify-center gap-8 bg-wall px-10 py-12 pb-[calc(var(--osk-h,0px)+48px)] text-center text-ink"
          >
            {children}
          </main>
        )}
        <KeyboardHost rail={null} />
        <ToastRegion display railSide="left" panelShown={false} />
      </MotionProvider>
    </ShellContext.Provider>
  );
}

/** Set Up Sunroom (ADR 0039): right here on the wall's keyboard, or on another device, side by
 * side in landscape and one above the other in portrait, like the screen's own Welcome. */
function Welcome({ address, onSetUpHere }: { address: string; onSetUpHere: () => void }) {
  return (
    <div className="flex w-full max-w-[110rem] flex-col items-center gap-8">
      <Brand size="entry" />
      <h1 className="text-d-glance font-bold">Set Up Sunroom</h1>
      <div className="grid w-full gap-6 portrait:grid-cols-1 landscape:grid-cols-2">
        <Choice
          heading="On This Screen"
          lead="Set it up right here."
          action={<Button onClick={onSetUpHere}>Set Up Here</Button>}
        >
          <p className="text-d-body">
            Type on the keyboard that opens on this screen. You can change all of it later in
            Settings.
          </p>
          <p className="text-d-body text-ink-soft">
            This screen becomes your family’s shared screen, and other devices join afterwards.
          </p>
        </Choice>
        <Choice heading="On Another Device" lead="Scan this code with your phone’s camera.">
          {isLoopbackAddress(address) ? (
            <p className="text-d-body">
              Open Sunroom on another device with this computer’s name or network address instead of{" "}
              <span className="font-bold">{new URL(address).hostname}</span>. Then come back here:
              this screen will show a code to pair it.
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-6">
              <QrCode value={address} label={`A code that opens ${address}`} className="size-56" />
              <p className="min-w-0 flex-1 basis-64 text-d-body">
                Or open <span className="font-bold break-all">{address}</span> on any device. Then
                come back here: this screen will show a code to pair it.
              </p>
            </div>
          )}
        </Choice>
      </div>
    </div>
  );
}

/**
 * Setting Sunroom up on the wall itself (ADR 0039): the wizard's steps in the wall's frame, its
 * keyboard under the fields. The household step makes this screen a paired one; after the
 * calendars it names itself, then All Done! opens the board.
 */
function WallSetup({
  step,
  address,
  onStep,
  onLeave,
}: {
  step: WallStep;
  address: string;
  onStep: (next: WallStep) => void;
  onLeave: () => void;
}) {
  useEffect(() => whenIdle(SETUP_IDLE_MS, onLeave), [onLeave]);
  if (step === "name") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-10 py-12 pb-[calc(var(--osk-h,0px)+48px)] text-center">
        <NameThisScreen
          action="Next"
          onDone={() => {
            onStep("done");
          }}
        />
      </main>
    );
  }
  return (
    <SetupWizard
      step={step}
      onScreen={{
        // The wizard ends at All Done!; on the wall, Name This Screen comes first.
        go: (next) => {
          onStep(next === "done" ? "name" : next === "welcome" ? "password" : next);
        },
        leave: onLeave,
        open: onLeave,
        address,
      }}
    />
  );
}

interface Pairing {
  code: string;
  display: string;
  poll_token: string;
  pair_url: string;
}

function PairThisScreen({ onPaired }: { onPaired: () => void }) {
  const queryClient = useQueryClient();
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [typing, setTyping] = useState(false);

  // Ask for a code, then wait for a signed-in device to claim it; a new code every 10 minutes.
  useEffect(() => {
    const loop = { stopped: false };
    const stopped = () => loop.stopped;
    const run = async () => {
      while (!stopped()) {
        const asked = await api.POST("/api/auth/kiosk/pairings");
        if (stopped()) return;
        if (!asked.response.ok || !asked.data) {
          setProblem(errorMessage(asked.error));
          await new Promise((resolve) => setTimeout(resolve, 10_000));
          continue;
        }
        setProblem(null);
        const current = asked.data;
        setPairing(current);
        for (;;) {
          const polled = await api.GET("/api/auth/kiosk/pairings/{poll_token}", {
            params: { path: { poll_token: current.poll_token }, query: { wait: 25 } },
          });
          if (stopped()) return;
          if (polled.data?.status === "paired" && polled.data.session) {
            queryClient.setQueryData<Session>(qk.session(), polled.data.session);
            onPaired();
            return;
          }
          if (polled.data?.status !== "waiting") break; // expired: a new code
        }
      }
    };
    void run();
    return () => {
      loop.stopped = true;
    };
  }, [queryClient, onPaired]);

  if (typing) {
    return (
      <PasswordPairing
        onCancel={() => {
          setTyping(false);
        }}
        onPaired={onPaired}
      />
    );
  }
  return (
    <>
      <Brand size="entry" />
      <h1 className="text-d-glance font-bold">Pair This Screen</h1>
      {pairing ? (
        <>
          <p
            aria-label={`Pair code: ${pairing.code.split("").join(" ")}`}
            data-testid="pair-code"
            className="text-d-code font-extrabold tracking-[0.12em]"
          >
            {pairing.display}
          </p>
          <div className="flex items-center gap-10 text-left">
            <QrCode value={pairing.pair_url} label="A code that opens Pair a Display on a phone" />
            <div className="flex max-w-xl flex-col gap-3">
              <p className="text-d-body">
                On a signed-in device, open Pair a Display (under More on a phone, Settings →
                Devices on a computer) and type this code.
              </p>
              <p className="text-d-secondary text-ink-soft">The code changes every 10 minutes.</p>
            </div>
          </div>
        </>
      ) : (
        <p className="text-d-body text-ink-soft">{problem ?? "Getting a code…"}</p>
      )}
      <Button
        variant="quiet"
        onClick={() => {
          setTyping(true);
        }}
      >
        Type the household password here instead
      </Button>
    </>
  );
}

function PasswordPairing({ onCancel, onPaired }: { onCancel: () => void; onPaired: () => void }) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const pair = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/auth/kiosk/pair-with-password", {
          body: { password, label: "Wall screen" },
        }),
      ),
    onSuccess: (session) => {
      queryClient.setQueryData<Session>(qk.session(), session);
      onPaired();
    },
  });

  // The password clears itself after a minute untouched: the wall is in everyone's view.
  useEffect(
    () =>
      whenIdle(PASSWORD_IDLE_MS, () => {
        setPassword("");
      }),
    [],
  );

  return (
    <form
      className="flex w-full max-w-3xl flex-col gap-6 text-left"
      onSubmit={(event) => {
        event.preventDefault();
        if (password) pair.mutate();
      }}
    >
      <Brand size="entry" />
      <h1 className="text-d-glance font-bold">Type the Household Password</h1>
      <TextField
        label="Household password"
        type={visible ? "text" : "password"}
        layout="password"
        autoComplete="off"
        autoCapitalize="none"
        value={password}
        error={pair.isError ? errorMessage(pair.error) : null}
        onChange={(event) => {
          setPassword(event.target.value);
        }}
      />
      <div className="flex flex-wrap items-center gap-3 whitespace-nowrap">
        <Button type="submit" pending={pair.isPending} disabled={!password}>
          Pair This Screen
        </Button>
        <Button
          variant="secondary"
          aria-pressed={visible}
          onClick={() => {
            setVisible((value) => !value);
          }}
        >
          {visible ? (
            <EyeOff aria-hidden="true" className="size-7" />
          ) : (
            <Eye aria-hidden="true" className="size-7" />
          )}
          {visible ? "Hide Password" : "Show Password"}
        </Button>
        <Button variant="quiet" onClick={onCancel}>
          Show the Code Instead
        </Button>
      </div>
    </form>
  );
}

/**
 * Name This Screen, right after pairing: a place picked from the chips names it ("Hallway
 * screen"), or Other and a name of its own. Nothing is chosen at first, so the screen assumes no
 * room (ADR 0042): Done with no place picked keeps the name it was paired with, "Wall screen".
 */
function NameThisScreen({
  onDone,
  action = "Done",
}: {
  onDone: () => void;
  /** Next while the wall sets Sunroom up, before All Done! */
  action?: "Done" | "Next";
}) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: async (name: string) =>
      unwrap(await api.PUT("/api/auth/device/label", { body: { label: name } })),
    onSuccess: (session) => {
      queryClient.setQueryData<Session>(qk.session(), session);
      onDone();
    },
  });
  const name = label === null ? null : label.trim();
  return (
    <form
      className="flex w-full max-w-3xl flex-col items-center gap-8"
      onSubmit={(event) => {
        event.preventDefault();
        if (name === null) onDone();
        else if (name) rename.mutate(name);
      }}
    >
      <Brand size="entry" />
      <h1 className="text-d-glance font-bold">Name This Screen</h1>
      <ScreenNameFields label={label} onChange={setLabel} field="other" />
      <Button type="submit" pending={rename.isPending} disabled={name === ""} className="min-w-64">
        {action}
      </Button>
      {rename.isError ? (
        <p role="alert" className="text-d-secondary font-semibold text-alert">
          {errorMessage(rename.error)}
        </p>
      ) : null}
    </form>
  );
}
