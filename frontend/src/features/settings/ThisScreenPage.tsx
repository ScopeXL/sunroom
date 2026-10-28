import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Wifi, WifiHigh, WifiLow } from "lucide-react";
import { useState } from "react";

import { qk } from "../../api/keys";
import {
  openScreenPage,
  screenClient,
  screenProgress,
  sunroomName,
  useScreenAgent,
  type ScreenCapability,
  type ScreenState,
  type ScreenWifi,
} from "../../lib/screenAgent";
import { useStore } from "../../lib/store";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { Digits } from "../../ui/Digits";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { TextField } from "../../ui/TextField";
import { Group, Row, Text } from "./parts";

type Rotation = 0 | 90 | 180 | 270;

const ROTATIONS = [
  { value: "0", label: "Landscape" },
  { value: "90", label: "Portrait, left" },
  { value: "270", label: "Portrait, right" },
  { value: "180", label: "Upside down" },
] as const;

const UPDATES = [
  { value: "nightly", label: "Install overnight" },
  { value: "off", label: "Off" },
] as const;

/** Where the Sunroom runs, not how it was found (ADR 0042). */
const FOUND_WORDS = {
  discovered: "on another computer",
  typed: "on another computer",
  local: "on this computer",
} as const;

const NO_ANSWER = "This screen didn’t answer. Try again in a moment.";

/** Change Address leaves for Where Is Your Sunroom? once its toast has shown. */
const LEAVE_AFTER_MS = 1500;

/** A refusal from the agent: its message is the agent's own plain sentence. */
class Refusal extends Error {}

function refusal(error: unknown): string {
  return error instanceof Refusal ? error.message : NO_ANSWER;
}

/** The agent's answer, or a Refusal with what it said (its error envelope). */
function answer<T>(result: { data?: T; error?: unknown }): T {
  if (result.error !== undefined) {
    const said = (result.error as { error?: { message?: string } }).error?.message;
    throw new Refusal(said ?? NO_ANSWER);
  }
  return result.data as T;
}

function agent() {
  const client = screenClient();
  if (!client) throw new Refusal(NO_ANSWER);
  return client;
}

function strength(percent: number | null | undefined): string {
  if (percent == null) return "";
  if (percent >= 67) return "strong";
  if (percent >= 34) return "fair";
  return "weak";
}

function networkWords(state: ScreenState): string {
  const { network } = state;
  if (network.kind === "wired") return "Wired";
  if (network.kind === "wifi") {
    const signal = strength(network.strength);
    return `Wi-Fi: ${network.ssid ?? "connected"}${signal ? `, ${signal}` : ""}`;
  }
  return "Not connected";
}

/**
 * Settings → This Screen (UX §4, ADR 0035): the wall's own device, through Sunroom Screen beside
 * its browser. Parent-only like the rest of Settings, on a wall the launcher named an agent for
 * (`?screen=`), and every row and button only when the agent says this screen can do it.
 */
export function ThisScreenPage({ onForgot }: { onForgot?: () => void } = {}) {
  const state = useScreenAgent();
  const queryClient = useQueryClient();
  const progress = useStore(screenProgress);
  const [wifiOpen, setWifiOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [asking, setAsking] = useState<"shutdown" | "address" | null>(null);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.screen.state() });
  };
  const act = useMutation({
    mutationFn: async (action: "restart" | "shutdown" | "quit" | "update" | "update-sunroom") => {
      answer(await agent().POST(`/api/screen/${action}`));
      return action;
    },
    onSuccess: (action) => {
      setAsking(null);
      const said = {
        restart: "Restarting…",
        shutdown: "Shutting down…",
        quit: "Quitting Sunroom Screen…",
        update: "Updating… this takes a few minutes",
        "update-sunroom": "Updating Sunroom… this takes a few minutes",
      } as const;
      showToast(said[action]);
    },
    onError: (error) => {
      showToast(refusal(error));
    },
  });
  const rotate = useMutation({
    mutationFn: async (rotation: Rotation) => {
      return answer(await agent().PUT("/api/screen/display", { body: { rotation } }));
    },
    onSuccess: (fresh) => {
      queryClient.setQueryData(qk.screen.state(), fresh);
    },
    onError: (error) => {
      showToast(`Not turned — ${refusal(error)}`);
    },
  });
  const policy = useMutation({
    mutationFn: async (check: "nightly" | "off") => {
      answer(await agent().PUT("/api/screen/update-policy", { body: { check } }));
    },
    onSettled: refresh,
    onError: (error) => {
      showToast(`Not saved — ${refusal(error)}`);
    },
  });
  const forget = useMutation({
    mutationFn: async () => {
      answer(await agent().DELETE("/api/screen/sunroom"));
    },
    onSuccess: () => {
      setAsking(null);
      showToast("Address changed. Looking for another Sunroom…");
      // The agent's own twin of this page goes to its Find page itself.
      if (onForgot) {
        onForgot();
        return;
      }
      // The wall leaves for the agent's Find page a moment after the toast, as the agent's own
      // restart waits for its toast.
      window.setTimeout(() => {
        openScreenPage("/find");
      }, LEAVE_AFTER_MS);
    },
    onError: (error) => {
      showToast(refusal(error));
    },
  });

  if (!state) return null;
  const can = (capability: ScreenCapability) => state.capabilities.includes(capability);
  const update = state.update;
  const installing = update.state === "installing" || progress !== null;
  const name = sunroomName(state.sunroom?.name);

  return (
    <>
      <Group>
        <Row label="Network">
          <Text>{networkWords(state)}</Text>
          {can("wifi") ? (
            <Button
              variant="secondary"
              onClick={() => {
                setWifiOpen(true);
              }}
            >
              Change Wi-Fi
            </Button>
          ) : null}
        </Row>
        <Row
          label="Address"
          hint={
            // The one way a found Sunroom still differs: the screen follows it when it moves.
            state.sunroom?.found === "discovered"
              ? "Found on your network: this screen follows it if its address changes."
              : undefined
          }
        >
          <Text>
            {state.sunroom
              ? `${state.sunroom.url} · ${FOUND_WORDS[state.sunroom.found]}`
              : "None yet"}
          </Text>
          <Button
            variant="secondary"
            onClick={() => {
              setAsking("address");
            }}
          >
            Change Address
          </Button>
        </Row>
        <Row label="Software" hint={update.message ?? undefined}>
          {installing ? (
            <Text>
              Updating… <Digits value={`${String(progress?.percent ?? 0)}%`} />
            </Text>
          ) : (
            <Text>
              {update.state === "available" && update.latest
                ? `${update.latest} is ready`
                : `Sunroom Screen ${update.installed}${update.state === "up_to_date" ? " · up to date" : ""}`}
            </Text>
          )}
          {can("update") && update.state === "available" && !installing ? (
            <Button
              pending={act.isPending && act.variables === "update"}
              onClick={() => {
                act.mutate("update");
              }}
            >
              Update Now
            </Button>
          ) : null}
          {can("update_sunroom") && update.sunroom_outdated ? (
            <Button
              variant="secondary"
              pending={act.isPending && act.variables === "update-sunroom"}
              onClick={() => {
                act.mutate("update-sunroom");
              }}
            >
              Update Sunroom Too
            </Button>
          ) : null}
        </Row>
        {can("update") ? (
          <Row label="Updates">
            <Segmented
              label="Updates"
              options={UPDATES}
              value={update.check}
              onChange={(check) => {
                policy.mutate(check);
              }}
            />
          </Row>
        ) : null}
        {can("rotate") ? (
          <Row label="Rotation">
            <Segmented
              label="Rotation"
              options={ROTATIONS}
              value={String(state.display.rotation) as `${Rotation}`}
              onChange={(value) => {
                rotate.mutate(Number(value) as Rotation);
              }}
            />
          </Row>
        ) : null}
      </Group>
      <div className="flex flex-wrap gap-3">
        {can("restart") ? (
          <Button
            variant="secondary"
            pending={act.isPending && act.variables === "restart"}
            onClick={() => {
              act.mutate("restart");
            }}
          >
            Restart
          </Button>
        ) : null}
        {can("shutdown") ? (
          <Button
            variant="secondary"
            onClick={() => {
              setAsking("shutdown");
            }}
          >
            Shut Down
          </Button>
        ) : null}
        {can("quit") ? (
          <Button
            variant="secondary"
            pending={act.isPending && act.variables === "quit"}
            onClick={() => {
              act.mutate("quit");
            }}
          >
            Quit Sunroom Screen
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => {
            setHelpOpen(true);
          }}
        >
          Help
        </Button>
      </div>

      <Sheet
        open={asking === "shutdown"}
        title="Shut Down This Screen?"
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          text="This turns off the computer this screen runs on. It stays off until someone turns it on again."
          act="Shut Down"
          keep="Cancel"
          pending={act.isPending}
          onAct={() => {
            act.mutate("shutdown");
          }}
          onKeep={() => {
            setAsking(null);
          }}
        />
      </Sheet>
      <Sheet
        open={asking === "address"}
        title="Use a Different Sunroom?"
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          text={`This screen leaves ${name} and looks for another. Its pairing is kept.`}
          act="Change Address"
          keep="Cancel"
          pending={forget.isPending}
          onAct={() => {
            forget.mutate();
          }}
          onKeep={() => {
            setAsking(null);
          }}
        />
      </Sheet>
      <WifiSheet
        open={wifiOpen}
        onClose={() => {
          setWifiOpen(false);
        }}
      />
      <HelpSheet
        open={helpOpen}
        onClose={() => {
          setHelpOpen(false);
        }}
      />
    </>
  );
}

function Confirm({
  text,
  act,
  keep,
  pending,
  onAct,
  onKeep,
}: {
  text: string;
  act: string;
  keep: string;
  pending: boolean;
  onAct: () => void;
  onKeep: () => void;
}) {
  return (
    <div className="flex flex-col gap-5 pb-2">
      <p className="text-d-body">{text}</p>
      <div className="flex flex-wrap gap-3">
        <Button variant="danger" pending={pending} onClick={onAct}>
          {act}
        </Button>
        <Button variant="secondary" onClick={onKeep}>
          {keep}
        </Button>
      </div>
    </div>
  );
}

function SignalIcon({ strength: percent }: { strength: number }) {
  const Icon = percent >= 67 ? Wifi : percent >= 34 ? WifiHigh : WifiLow;
  return <Icon aria-hidden="true" className="size-8 shrink-0" />;
}

/**
 * The networks in range, and the password of the one tapped, typed on the wall's keyboard
 * (Change Wi-Fi's sheet, and the screen's own Wi-Fi page). `chosen` is held by the caller, which
 * titles itself after it.
 */
export function WifiChooser({
  chosen,
  onChoose,
  onJoined,
}: {
  chosen: ScreenWifi | null;
  onChoose: (network: ScreenWifi | null) => void;
  onJoined: () => void;
}) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const { data: networks, isFetching } = useQuery({
    queryKey: qk.screen.wifi(),
    queryFn: async () => answer(await agent().GET("/api/screen/wifi")).networks,
  });
  const join = useMutation({
    mutationFn: async (network: ScreenWifi) =>
      answer(await agent().POST("/api/screen/wifi", { body: { ssid: network.ssid, password } }))
        .networks,
    onSuccess: async (fresh, network) => {
      queryClient.setQueryData(qk.screen.wifi(), fresh);
      await queryClient.invalidateQueries({ queryKey: qk.screen.state() });
      showToast(`Joined ${network.ssid}`);
      setPassword("");
      onJoined();
    },
    onError: (error) => {
      setProblem(refusal(error));
    },
  });
  const choose = (network: ScreenWifi | null) => {
    setPassword("");
    setProblem(null);
    onChoose(network);
  };
  if (chosen) {
    return (
      <form
        className="flex flex-col gap-5 pb-2 text-left"
        onSubmit={(event) => {
          event.preventDefault();
          join.mutate(chosen);
        }}
      >
        {chosen.secured ? (
          <TextField
            label="Password"
            type="password"
            layout="password"
            autoCapitalize="none"
            autoComplete="off"
            value={password}
            error={problem}
            onChange={(event) => {
              setPassword(event.target.value);
              setProblem(null);
            }}
          />
        ) : (
          <Text soft>This network has no password.</Text>
        )}
        {!chosen.secured && problem ? (
          <p role="alert" className="font-semibold text-alert">
            {problem}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" pending={join.isPending}>
            Connect
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              choose(null);
            }}
          >
            Other Networks
          </Button>
        </div>
      </form>
    );
  }
  return (
    <div className="flex flex-col gap-2 pb-2 text-left">
      {networks === undefined ? (
        <Text soft>{isFetching ? "Looking for networks…" : "No networks found."}</Text>
      ) : networks.length === 0 ? (
        <Text soft>No networks found. Move the screen closer to the router, or try again.</Text>
      ) : (
        <ul className="divide-y divide-line rounded-chip border border-line bg-surface px-4">
          {networks.map((network) => (
            <li key={network.ssid}>
              <button
                type="button"
                disabled={network.connected}
                className="press-row flex min-h-20 w-full items-center gap-4 py-3 text-left disabled:opacity-100"
                aria-label={`${network.ssid}, ${strength(network.strength)} signal${network.secured ? ", needs a password" : ""}${network.connected ? ", connected" : ""}`}
                onClick={() => {
                  choose(network);
                }}
              >
                <SignalIcon strength={network.strength} />
                <span className="min-w-0 flex-1 text-d-body font-semibold">{network.ssid}</span>
                {network.connected ? (
                  <span className="text-d-secondary text-ink-soft">Connected</span>
                ) : null}
                {network.secured ? (
                  <Lock aria-hidden="true" className="size-7 shrink-0 text-ink-soft" />
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Change Wi-Fi, in a sheet over This Screen. */
function WifiSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [chosen, setChosen] = useState<ScreenWifi | null>(null);
  const close = () => {
    setChosen(null);
    onClose();
  };
  return (
    <Sheet
      open={open}
      title={chosen ? chosen.ssid : "Wi-Fi"}
      onClose={close}
      {...(chosen ? { step: chosen.ssid } : {})}
    >
      {open ? <WifiChooser chosen={chosen} onChoose={setChosen} onJoined={close} /> : null}
    </Sheet>
  );
}

function seconds(total: number): string {
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${String(days)} day${days === 1 ? "" : "s"}, ${String(hours)} hours`;
  if (hours) return `${String(hours)} hour${hours === 1 ? "" : "s"}, ${String(minutes)} min`;
  return `${String(minutes)} min`;
}

/** Help: what this screen is and runs, for whoever helps the family with it. */
function HelpSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: about } = useQuery({
    queryKey: qk.screen.about(),
    queryFn: async () => {
      return answer(await agent().GET("/api/screen/about"));
    },
    enabled: open,
  });
  return (
    <Sheet open={open} title="About This Screen" onClose={onClose}>
      <div className="flex flex-col gap-4 pb-2">
        {about ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-d-body">
            <dt className="text-ink-soft">Sunroom Screen</dt>
            <dd>{about.version}</dd>
            <dt className="text-ink-soft">Computer</dt>
            <dd>{about.model}</dd>
            <dt className="text-ink-soft">System</dt>
            <dd>{about.system}</dd>
            {about.browser ? (
              <>
                <dt className="text-ink-soft">Browser</dt>
                <dd>{about.browser}</dd>
              </>
            ) : null}
            <dt className="text-ink-soft">Name</dt>
            <dd>{about.hostname}</dd>
            {about.ip ? (
              <>
                <dt className="text-ink-soft">Its address</dt>
                <dd>{about.ip}</dd>
              </>
            ) : null}
            <dt className="text-ink-soft">Shows</dt>
            <dd className="break-all">{about.sunroom_url ?? "Nothing yet"}</dd>
            <dt className="text-ink-soft">Running for</dt>
            <dd>{seconds(about.uptime_s)}</dd>
          </dl>
        ) : (
          <Text soft>Asking this screen…</Text>
        )}
        {about?.log?.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="text-d-body font-bold">What It Did Lately</h3>
            <ol className="max-h-72 overflow-y-auto rounded-chip border border-line bg-surface px-4 py-3 text-d-secondary">
              {about.log.slice(-20).map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ol>
          </section>
        ) : null}
        <Text soft>Having trouble? Settings → Support Sunroom.</Text>
      </div>
    </Sheet>
  );
}
