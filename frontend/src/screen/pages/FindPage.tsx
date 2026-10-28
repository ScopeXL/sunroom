import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { qk } from "../../api/keys";
import {
  screenClient,
  sunroomName,
  type ScreenFound,
  type ScreenState,
} from "../../lib/screenAgent";
import { Button } from "../../ui/Button";
import { TextField } from "../../ui/TextField";
import { go } from "../route";

const NO_ANSWER = "This screen didn’t answer. Try again in a moment.";

function agent() {
  const client = screenClient();
  if (!client) throw new Error(NO_ANSWER);
  return client;
}

/** The agent's plain sentence for a refusal, or that it didn't answer. */
function said(error: unknown): string {
  const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
  return message ?? NO_ANSWER;
}

/** "The Sample Family's Sunroom", or "A Sunroom" for one older than /api/discover. */
function title(found: ScreenFound): string {
  return found.older ? "A Sunroom" : sunroomName(found.name);
}

function detail(found: ScreenFound): string {
  return found.version ? `${found.url} · version ${found.version}` : found.url;
}

function Card({ heading, children }: { heading: string; children: ReactNode }) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className="flex min-w-0 flex-col gap-4 rounded-panel border border-line bg-surface p-6 text-left"
    >
      <h2 id={id} className="text-d-title font-bold">
        {heading}
      </h2>
      {children}
    </section>
  );
}

/** Use this Sunroom from now on: the agent checks it again, saves it and opens it. */
function useChoose() {
  return useMutation({
    mutationFn: async ({ url, found }: { url: string; found: "discovered" | "typed" }) => {
      const { error } = await agent().PUT("/api/screen/sunroom", { body: { url, found } });
      if (error !== undefined) throw new Error(said(error));
    },
    onSuccess: () => {
      go("/opening");
    },
  });
}

function OnYourNetwork() {
  const queryClient = useQueryClient();
  const choose = useChoose();
  // The results arrive on the event stream as they're found; while a scan runs the list is also
  // asked for every second, so it never waits on the stream having connected in time.
  const { data: scan } = useQuery({
    queryKey: qk.screen.sunrooms(),
    queryFn: async () => {
      const { data, error } = await agent().GET("/api/screen/sunrooms");
      if (error !== undefined) throw new Error(said(error));
      return data;
    },
    refetchInterval: (query) => (query.state.data?.scanning ? 1000 : false),
  });
  const look = useMutation({
    mutationFn: async () => {
      const { data, error } = await agent().POST("/api/screen/sunrooms/scan");
      if (error !== undefined) throw new Error(said(error));
      return data;
    },
    onSuccess: (started) => {
      queryClient.setQueryData(qk.screen.sunrooms(), started);
    },
  });
  const { mutate: lookNow } = look;
  // Looking starts the moment the page opens; the results arrive on the event stream.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    lookNow();
  }, [lookNow]);
  const scanning = look.isPending || (scan?.scanning ?? false);
  const found = scan?.found ?? [];
  return (
    <Card heading="On Your Network">
      {found.length === 0 ? (
        <p className="text-d-body text-ink-soft" role="status">
          {scanning ? "Looking…" : "No Sunroom answered on this network."}
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {found.map((sunroom) => (
            <li key={sunroom.url} className="flex flex-col gap-2 border-b border-line pb-3">
              <span className="text-d-body font-semibold">{title(sunroom)}</span>
              <span className="text-d-secondary break-all text-ink-soft">{detail(sunroom)}</span>
              <div>
                <Button
                  pending={choose.isPending && choose.variables.url === sunroom.url}
                  onClick={() => {
                    choose.mutate({ url: sunroom.url, found: "discovered" });
                  }}
                >
                  Use This Sunroom
                </Button>
              </div>
            </li>
          ))}
          {scanning ? (
            <li className="text-d-secondary text-ink-soft">
              {/* The status inside the item: a list holds list items only (axe). */}
              <span role="status">Still looking…</span>
            </li>
          ) : null}
        </ul>
      )}
      {choose.isError ? (
        <p role="alert" className="text-d-body font-semibold text-alert">
          {choose.error.message}
        </p>
      ) : null}
      {scanning ? null : (
        <div>
          <Button
            variant="secondary"
            onClick={() => {
              look.mutate();
            }}
          >
            Look Again
          </Button>
        </div>
      )}
    </Card>
  );
}

/** Nothing worth asking about: an empty field, or only a scheme ("https://"). */
function unfinished(address: string): boolean {
  return address === "" || /^https?:?\/{0,2}$/i.test(address);
}

/** Check Address's face: at rest, while the agent looks, and what it found (ADR 0042). */
function CheckFace({ state }: { state: "rest" | "checking" | "found" | "not-found" }) {
  switch (state) {
    case "rest":
      return "Check Address";
    case "checking":
      return "Checking…";
    case "found":
      return (
        <>
          <Check aria-hidden="true" className="size-7" strokeWidth={3} />
          Found
        </>
      );
    case "not-found":
      return (
        <>
          <X aria-hidden="true" className="size-7" strokeWidth={3} />
          Not Found
        </>
      );
  }
}

/**
 * An address typed on the wall's keyboard (ADR 0042): it's checked as soon as the field is left
 * (or ↵, which submits) with something new in it; Check Address tries again and shows how the
 * check went, and Use This Sunroom rises into the same row once a Sunroom answered.
 */
function SomewhereElse() {
  const [typed, setTyped] = useState("");
  // The last address asked about, so leaving the field again with it unchanged asks nothing.
  const [asked, setAsked] = useState<string | null>(null);
  const choose = useChoose();
  const check = useMutation({
    mutationFn: async (url: string) => {
      const { data, error } = await agent().POST("/api/screen/sunroom/check", { body: { url } });
      if (error !== undefined) throw new Error(said(error));
      return data;
    },
  });
  const address = typed.trim();
  const ask = (again: boolean) => {
    if (unfinished(address)) return;
    if (!again && address === asked) return;
    // A tap on Check Address leaves the field first: that check is already on its way.
    if (check.isPending && check.variables === address) return;
    setAsked(address);
    check.mutate(address);
  };
  const result = check.data;
  const found = result?.ok ? result.sunroom : null;
  const face = check.isPending
    ? "checking"
    : found
      ? "found"
      : result || check.isError
        ? "not-found"
        : "rest";
  return (
    <Card heading="Somewhere Else">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          ask(true);
        }}
      >
        <TextField
          label="Sunroom address"
          hint="The one you open on your other devices, like http://192.168.1.20:8080 or https://calendar.example.com"
          autoCapitalize="none"
          autoComplete="off"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            check.reset();
          }}
          onBlur={() => {
            ask(false);
          }}
        />
        <div className="flex flex-wrap items-center gap-4">
          <Button
            type="submit"
            variant="secondary"
            aria-busy={face === "checking" || undefined}
            disabled={face === "checking"}
            className={face === "found" ? "border-ink" : undefined}
          >
            <CheckFace state={face} />
          </Button>
          {found ? (
            <Button
              className="rise-in ml-auto"
              pending={choose.isPending}
              onClick={() => {
                choose.mutate({ url: found.url, found: "typed" });
              }}
            >
              Use This Sunroom
            </Button>
          ) : null}
        </div>
      </form>
      {result ? (
        <p role="status" className="text-d-body font-semibold">
          {found
            ? found.older
              ? `That’s a Sunroom, version ${found.version ?? "unknown"}.`
              : `That’s ${sunroomName(found.name)}.`
            : (result.message ?? NO_ANSWER)}
        </p>
      ) : null}
      {check.isError ? (
        <p role="alert" className="text-d-body font-semibold text-alert">
          {check.error.message}
        </p>
      ) : null}
      {choose.isError ? (
        <p role="alert" className="text-d-body font-semibold text-alert">
          {choose.error.message}
        </p>
      ) : null}
    </Card>
  );
}

/** Where Is Your Sunroom? On the network, or at an address someone was given (Connect to a
 * Sunroom, on Welcome; running it here is Welcome's other way, ADR 0038). */
export function FindPage({ state }: { state: ScreenState }) {
  const chosen = state.sunroom !== null;
  useEffect(() => {
    // Chosen here, or in another of this screen's pages meanwhile: open it.
    if (chosen) go("/opening", true);
  }, [chosen]);
  return (
    <div className="flex w-full max-w-[110rem] flex-col gap-8">
      <h1 className="text-d-glance font-bold">Where Is Your Sunroom?</h1>
      <div className="grid gap-6 portrait:grid-cols-1 landscape:grid-cols-2">
        <OnYourNetwork />
        <SomewhereElse />
      </div>
      <div>
        <Button
          variant="quiet"
          onClick={() => {
            go("/");
          }}
        >
          Back
        </Button>
      </div>
    </div>
  );
}
