import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Wifi, WifiHigh, WifiLow } from "lucide-react";
import { useState } from "react";

import { qk } from "../../api/keys";
import { t, tRich, tSaid, useT, type Key } from "../../lib/lang";
import {
  openScreenPage,
  screenProgress,
  sunroomName,
  useScreenAgent,
  useScreenAgentAway,
  type ScreenCapability,
  type ScreenState,
  type ScreenWifi,
} from "../../lib/screenAgent";
import { useStore } from "../../lib/store";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { useShell } from "../../ui/shell";
import { Digits } from "../../ui/Digits";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { TextField } from "../../ui/TextField";
import { agent, answer, refusal, reinstall } from "./agentCalls";
import { Group, Row, Text } from "./parts";
import { UninstallSheet } from "./UninstallSheet";

type Rotation = 0 | 90 | 180 | 270;

/** This Screen's word tables: each choice's words are a key, said where it's shown. */
const ROTATIONS: readonly { value: `${Rotation}`; label: Key }[] = [
  { value: "0", label: "settings.this_screen.rotation.landscape" },
  { value: "90", label: "settings.this_screen.rotation.left" },
  { value: "270", label: "settings.this_screen.rotation.right" },
  { value: "180", label: "settings.this_screen.rotation.upside_down" },
];

const UPDATES: readonly { value: "nightly" | "off"; label: Key }[] = [
  { value: "nightly", label: "settings.this_screen.updates.nightly" },
  { value: "off", label: "settings.this_screen.updates.off" },
];

/** Where the Sunroom runs, not how it was found (ADR 0042). */
const FOUND_WORDS: Readonly<Record<"discovered" | "typed" | "local", Key>> = {
  discovered: "settings.this_screen.address.elsewhere",
  typed: "settings.this_screen.address.elsewhere",
  local: "settings.this_screen.address.here",
};

type Action = "restart" | "shutdown" | "quit" | "update";

/** What a tap on each action says while the screen does it. */
const DOING: Readonly<Record<Action, Key>> = {
  restart: "settings.this_screen.restart.toast",
  shutdown: "settings.this_screen.shutdown.toast",
  quit: "settings.this_screen.quit.toast",
  update: "settings.this_screen.update.toast",
};

/** Change Address leaves for Where Is Your Sunroom? once its toast has shown. */
const LEAVE_AFTER_MS = 1500;

/** A signal's strength as the messages choose their words by it. */
function strength(percent: number | null | undefined): "strong" | "fair" | "weak" | "none" {
  if (percent == null) return "none";
  if (percent >= 67) return "strong";
  if (percent >= 34) return "fair";
  return "weak";
}

/** "Wired", "Wi-Fi: HomeNet, strong", "Not connected". */
function networkWords(state: ScreenState): string {
  const { network } = state;
  if (network.kind === "wired") return t("settings.this_screen.network.wired");
  if (network.kind === "wifi") {
    return t("settings.this_screen.network.wifi", {
      name: network.ssid ?? t("settings.this_screen.network.unnamed"),
      signal: strength(network.strength),
    });
  }
  return t("settings.this_screen.network.none");
}

/**
 * Settings → This Screen (UX §4, ADR 0035): the wall's own device, through Sunroom Screen beside
 * its browser. Parent-only like the rest of Settings, on a wall the launcher named an agent for
 * (`?screen=`), and every row and button only when the agent says this screen can do it.
 */
export function ThisScreenPage({ onForgot }: { onForgot?: () => void } = {}) {
  const t = useT();
  const state = useScreenAgent();
  const queryClient = useQueryClient();
  const progress = useStore(screenProgress);
  const away = useScreenAgentAway();
  const [wifiOpen, setWifiOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [asking, setAsking] = useState<
    "shutdown" | "address" | "uninstall" | "update" | "reinstall" | null
  >(null);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.screen.state() });
  };
  const act = useMutation({
    mutationFn: async (action: Action) => {
      answer(await agent().POST(`/api/screen/${action}`));
      return action;
    },
    onSuccess: (action) => {
      setAsking(null);
      showToast(t(DOING[action]));
    },
    onError: (error) => {
      showToast(refusal(error));
    },
  });
  const again = useMutation({
    mutationFn: reinstall,
    onSuccess: () => {
      setAsking(null);
      showToast(t("settings.this_screen.reinstall.toast"));
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
      showToast(t("settings.this_screen.rotation.error", { why: refusal(error) }));
    },
  });
  const updateSunroom = useMutation({
    mutationFn: async () => {
      answer(await agent().POST("/api/screen/update-sunroom"));
    },
    onSuccess: () => {
      showToast(t("settings.this_screen.software.update_sunroom.toast"));
    },
    onError: (error) => {
      showToast(refusal(error));
    },
  });
  const policy = useMutation({
    mutationFn: async (check: "nightly" | "off") => {
      answer(await agent().PUT("/api/screen/update-policy", { body: { check } }));
    },
    onSettled: refresh,
    onError: (error) => {
      showToast(t("app.not_saved", { why: refusal(error) }));
    },
  });
  const forget = useMutation({
    mutationFn: async () => {
      answer(await agent().DELETE("/api/screen/sunroom"));
    },
    onSuccess: () => {
      setAsking(null);
      showToast(t("settings.this_screen.address.changed.toast"));
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
  const percent = <Digits value={`${String(progress?.percent ?? 0)}%`} />;
  // Mid-update the agent goes away to start itself again; the row says so until it's back.
  const doing =
    away && progress !== null
      ? t("settings.this_screen.software.starting_again")
      : progress !== null
        ? tRich("settings.this_screen.software.step", {
            step: tSaid(progress.step, progress.key),
            percent,
          })
        : tRich("settings.this_screen.software.updating", { percent });
  const behind = update.sunroom_pinned
    ? t("settings.this_screen.software.sunroom_pinned", { version: update.sunroom_pinned })
    : update.sunroom_outdated && state.sunroom?.version
      ? t("settings.this_screen.software.sunroom_behind", {
          sunroom: state.sunroom.version,
          version: update.latest ?? update.installed,
        })
      : null;

  return (
    <>
      <Group>
        <Row label={t("settings.this_screen.network.label")}>
          <Text>{networkWords(state)}</Text>
          {can("wifi") ? (
            <Button
              variant="secondary"
              onClick={() => {
                setWifiOpen(true);
              }}
            >
              {t("settings.this_screen.wifi.change.action")}
            </Button>
          ) : null}
        </Row>
        <Row
          label={t("settings.this_screen.address.label")}
          hint={
            // The one way a found Sunroom still differs: the screen follows it when it moves.
            state.sunroom?.found === "discovered"
              ? t("settings.this_screen.address.found.hint")
              : undefined
          }
        >
          <Text>
            {state.sunroom
              ? `${state.sunroom.url} · ${t(FOUND_WORDS[state.sunroom.found])}`
              : t("settings.this_screen.address.none")}
          </Text>
          <Button
            variant="secondary"
            onClick={() => {
              setAsking("address");
            }}
          >
            {t("settings.this_screen.address.change.action")}
          </Button>
        </Row>
        {/* The hint is Sunroom Screen's own sentence, in the page's language when it knows it. */}
        <Row
          label={t("settings.this_screen.software.label")}
          hint={
            update.message
              ? tSaid(update.message, update.message_key, update.message_params)
              : (behind ?? undefined)
          }
        >
          {installing ? (
            <Text>{doing}</Text>
          ) : (
            <Text>
              {update.state === "available" && update.latest
                ? t("settings.this_screen.software.ready", { version: update.latest })
                : update.state === "up_to_date"
                  ? t("settings.this_screen.software.up_to_date", { version: update.installed })
                  : t("settings.this_screen.software.installed", { version: update.installed })}
            </Text>
          )}
          {can("update") && update.state === "available" && !installing ? (
            <Button
              onClick={() => {
                setAsking("update");
              }}
            >
              {t("settings.this_screen.update.action")}
            </Button>
          ) : null}
          {/* An all-in-one Pi's Sunroom, left behind by a pull that failed (ADR 0046). */}
          {update.sunroom_can_update && !installing ? (
            <Button
              variant="secondary"
              pending={updateSunroom.isPending}
              onClick={() => {
                updateSunroom.mutate();
              }}
            >
              {t("settings.this_screen.software.update_sunroom.action")}
            </Button>
          ) : null}
          {/* For a screen that misbehaves: the version it runs, set up again (ADR 0044). An
              update does the same on its way, so it's offered only without one. */}
          {can("update") && update.state !== "available" && !installing ? (
            <Button
              variant="quiet"
              onClick={() => {
                setAsking("reinstall");
              }}
            >
              {t("settings.this_screen.reinstall.open.action")}
            </Button>
          ) : null}
        </Row>
        {update.needs_terminal ? <InstallCommand command={update.needs_terminal} /> : null}
        {can("update") ? (
          <Row label={t("settings.this_screen.updates.label")}>
            <Segmented
              label={t("settings.this_screen.updates.label")}
              options={UPDATES.map((option) => ({ value: option.value, label: t(option.label) }))}
              value={update.check}
              onChange={(check) => {
                policy.mutate(check);
              }}
            />
          </Row>
        ) : null}
        {can("rotate") ? (
          <Row label={t("settings.this_screen.rotation.label")}>
            <Segmented
              label={t("settings.this_screen.rotation.label")}
              options={ROTATIONS.map((option) => ({
                value: option.value,
                label: t(option.label),
              }))}
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
            {t("settings.this_screen.restart.action")}
          </Button>
        ) : null}
        {can("shutdown") ? (
          <Button
            variant="secondary"
            onClick={() => {
              setAsking("shutdown");
            }}
          >
            {t("settings.this_screen.shutdown.action")}
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
            {t("settings.this_screen.quit.action")}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => {
            setHelpOpen(true);
          }}
        >
          {t("settings.this_screen.help.action")}
        </Button>
      </div>
      {/* The wall's alone (ADR 0042): the screen's own pages (`onForgot`) have no Sunroom to
          unpair it with. */}
      {can("uninstall") && !onForgot ? (
        <div className="mt-10">
          <Group
            title={t("settings.this_screen.remove.title")}
            note={t("settings.this_screen.remove.note")}
          >
            <div className="py-5">
              <Button
                variant="quiet-danger"
                onClick={() => {
                  setAsking("uninstall");
                }}
              >
                {t("settings.this_screen.uninstall.open.action")}
              </Button>
            </div>
          </Group>
        </div>
      ) : null}
      <UninstallSheet
        open={asking === "uninstall"}
        sunroomHere={can("remove_sunroom")}
        onClose={() => {
          setAsking(null);
        }}
        onStarted={() => {
          setAsking(null);
        }}
      />

      <Sheet
        open={asking === "update"}
        title={t("settings.this_screen.update.title")}
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          tone="primary"
          text={t("settings.this_screen.update.body", {
            version: update.latest ?? update.installed,
          })}
          act={t("settings.this_screen.update.confirm.action")}
          keep={t("app.action.cancel")}
          pending={act.isPending}
          onAct={() => {
            act.mutate("update");
          }}
          onKeep={() => {
            setAsking(null);
          }}
        />
      </Sheet>
      <Sheet
        open={asking === "reinstall"}
        title={t("settings.this_screen.reinstall.title")}
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          tone="primary"
          text={t("settings.this_screen.reinstall.body", { version: update.installed })}
          act={t("settings.this_screen.reinstall.action")}
          keep={t("app.action.cancel")}
          pending={again.isPending}
          onAct={() => {
            again.mutate();
          }}
          onKeep={() => {
            setAsking(null);
          }}
        />
      </Sheet>
      <Sheet
        open={asking === "shutdown"}
        title={t("settings.this_screen.shutdown.title")}
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          text={t("settings.this_screen.shutdown.body")}
          act={t("settings.this_screen.shutdown.action")}
          keep={t("app.action.cancel")}
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
        title={t("settings.this_screen.address.title")}
        onClose={() => {
          setAsking(null);
        }}
      >
        <Confirm
          text={t("settings.this_screen.address.body", { name })}
          act={t("settings.this_screen.address.change.action")}
          keep={t("app.action.cancel")}
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

/**
 * The installer's one line, for a screen whose root helper is too old to finish an update by
 * itself (ADR 0044): to be typed in a terminal on that computer, so it's read from across the
 * room, with nothing to tap.
 */
function InstallCommand({ command }: { command: string }) {
  const t = useT();
  const display = useShell() === "display";
  return (
    <div className={`flex flex-col gap-3 ${display ? "pb-5" : "pb-4"}`}>
      <Text soft>{t("settings.this_screen.software.needs_terminal.hint")}</Text>
      <code
        className={`block rounded-xl border-2 border-line bg-wall px-4 py-3 font-mono break-all select-all ${
          display ? "text-d-body" : "text-body"
        }`}
      >
        {command}
      </code>
    </div>
  );
}

function Confirm({
  text,
  act,
  keep,
  pending,
  onAct,
  onKeep,
  tone = "danger",
}: {
  text: string;
  act: string;
  keep: string;
  pending: boolean;
  onAct: () => void;
  onKeep: () => void;
  /** What the action is: one that stops something, or one that carries on as asked. */
  tone?: "danger" | "primary";
}) {
  return (
    <div className="flex flex-col gap-5 pb-2">
      <p className="text-d-body">{text}</p>
      <div className="flex flex-wrap gap-3">
        <Button variant={tone} pending={pending} onClick={onAct}>
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
  const t = useT();
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
      showToast(t("settings.this_screen.wifi.joined.toast", { name: network.ssid }));
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
            label={t("settings.this_screen.wifi.password.label")}
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
          <Text soft>{t("settings.this_screen.wifi.open")}</Text>
        )}
        {!chosen.secured && problem ? (
          <p role="alert" className="font-semibold text-alert">
            {problem}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" pending={join.isPending}>
            {t("settings.this_screen.wifi.connect.action")}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              choose(null);
            }}
          >
            {t("settings.this_screen.wifi.others.action")}
          </Button>
        </div>
      </form>
    );
  }
  return (
    <div className="flex flex-col gap-2 pb-2 text-left">
      {networks === undefined ? (
        <Text soft>
          {isFetching
            ? t("settings.this_screen.wifi.looking")
            : t("settings.this_screen.wifi.not_found")}
        </Text>
      ) : networks.length === 0 ? (
        <Text soft>{t("settings.this_screen.wifi.empty")}</Text>
      ) : (
        <ul className="divide-y divide-line rounded-chip border border-line bg-surface px-4">
          {networks.map((network) => (
            <li key={network.ssid}>
              <button
                type="button"
                disabled={network.connected}
                className="press-row flex min-h-20 w-full items-center gap-4 py-3 text-left disabled:opacity-100"
                aria-label={t("settings.this_screen.wifi.network.aria", {
                  name: network.ssid,
                  signal: strength(network.strength),
                  secured: network.secured ? "yes" : "no",
                  connected: network.connected ? "yes" : "no",
                })}
                onClick={() => {
                  choose(network);
                }}
              >
                <SignalIcon strength={network.strength} />
                <span className="min-w-0 flex-1 text-d-body font-semibold">{network.ssid}</span>
                {network.connected ? (
                  <span className="text-d-secondary text-ink-soft">
                    {t("settings.this_screen.wifi.connected")}
                  </span>
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
  const t = useT();
  const [chosen, setChosen] = useState<ScreenWifi | null>(null);
  const close = () => {
    setChosen(null);
    onClose();
  };
  return (
    <Sheet
      open={open}
      title={chosen ? chosen.ssid : t("settings.this_screen.wifi.title")}
      onClose={close}
      {...(chosen ? { step: chosen.ssid } : {})}
    >
      {open ? <WifiChooser chosen={chosen} onChoose={setChosen} onJoined={close} /> : null}
    </Sheet>
  );
}

/** "2 days, 3 hours", "1 hour, 5 min", "12 min". */
function seconds(total: number): string {
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return t("settings.this_screen.uptime.days", { days, hours });
  if (hours) return t("settings.this_screen.uptime.hours", { hours, minutes });
  return t("settings.this_screen.uptime.minutes", { minutes });
}

/** Help: what this screen is and runs, for whoever helps the family with it. */
function HelpSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const { data: about } = useQuery({
    queryKey: qk.screen.about(),
    queryFn: async () => {
      return answer(await agent().GET("/api/screen/about"));
    },
    enabled: open,
  });
  return (
    <Sheet open={open} title={t("settings.this_screen.about.title")} onClose={onClose}>
      <div className="flex flex-col gap-4 pb-2">
        {about ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-d-body">
            <dt className="text-ink-soft">{t("settings.this_screen.about.version.label")}</dt>
            <dd>{about.version}</dd>
            <dt className="text-ink-soft">{t("settings.this_screen.about.model.label")}</dt>
            <dd>{about.model}</dd>
            <dt className="text-ink-soft">{t("settings.this_screen.about.system.label")}</dt>
            <dd>{about.system}</dd>
            {about.browser ? (
              <>
                <dt className="text-ink-soft">{t("settings.this_screen.about.browser.label")}</dt>
                <dd>{about.browser}</dd>
              </>
            ) : null}
            <dt className="text-ink-soft">{t("settings.this_screen.about.name.label")}</dt>
            <dd>{about.hostname}</dd>
            {about.ip ? (
              <>
                <dt className="text-ink-soft">{t("settings.this_screen.about.ip.label")}</dt>
                <dd>{about.ip}</dd>
              </>
            ) : null}
            <dt className="text-ink-soft">{t("settings.this_screen.about.shows.label")}</dt>
            <dd className="break-all">
              {about.sunroom_url ?? t("settings.this_screen.about.shows.none")}
            </dd>
            <dt className="text-ink-soft">{t("settings.this_screen.about.uptime.label")}</dt>
            <dd>{seconds(about.uptime_s)}</dd>
          </dl>
        ) : (
          <Text soft>{t("settings.this_screen.about.asking")}</Text>
        )}
        {about?.log?.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="text-d-body font-bold">{t("settings.this_screen.about.log.title")}</h3>
            {/* Sunroom Screen's own log lines, as it wrote them. */}
            <ol className="max-h-72 overflow-y-auto rounded-chip border border-line bg-surface px-4 py-3 text-d-secondary">
              {about.log.slice(-20).map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ol>
          </section>
        ) : null}
        <Text soft>{t("settings.this_screen.about.trouble")}</Text>
      </div>
    </Sheet>
  );
}
