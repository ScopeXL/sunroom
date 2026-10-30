import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { qk } from "../../api/keys";
import { t, useT } from "../../lib/lang";
import { sunroomName, type ScreenFound, type ScreenState } from "../../lib/screenAgent";
import { Button } from "../../ui/Button";
import { TextField } from "../../ui/TextField";
import { agent, said, saying } from "../calls";
import { go } from "../route";

/** "The Sample Family's Sunroom", or "A Sunroom" for one older than /api/discover. */
function title(found: ScreenFound): string {
  return found.older ? t("screen.find.older") : sunroomName(found.name);
}

function detail(found: ScreenFound): string {
  return found.version
    ? t("screen.find.detail", { url: found.url, version: found.version })
    : found.url;
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
  const t = useT();
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
    <Card heading={t("screen.find.network.title")}>
      {found.length === 0 ? (
        <p className="text-d-body text-ink-soft" role="status">
          {scanning ? t("screen.find.network.looking") : t("screen.find.network.none")}
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
                  {t("screen.find.use.action")}
                </Button>
              </div>
            </li>
          ))}
          {scanning ? (
            <li className="text-d-secondary text-ink-soft">
              {/* The status inside the item: a list holds list items only (axe). */}
              <span role="status">{t("screen.find.network.still_looking")}</span>
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
            {t("screen.find.network.again.action")}
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
  const t = useT();
  switch (state) {
    case "rest":
      return t("screen.find.check.action");
    case "checking":
      return t("screen.find.check.checking");
    case "found":
      return (
        <>
          <Check aria-hidden="true" className="size-7" strokeWidth={3} />
          {t("screen.find.check.found")}
        </>
      );
    case "not-found":
      return (
        <>
          <X aria-hidden="true" className="size-7" strokeWidth={3} />
          {t("screen.find.check.not_found")}
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
  const t = useT();
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
    <Card heading={t("screen.find.elsewhere.title")}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          ask(true);
        }}
      >
        <TextField
          label={t("screen.find.address.label")}
          hint={t("screen.find.address.hint")}
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
              {t("screen.find.use.action")}
            </Button>
          ) : null}
        </div>
      </form>
      {result ? (
        <p role="status" className="text-d-body font-semibold">
          {found
            ? found.older
              ? found.version
                ? t("screen.find.found.older", { version: found.version })
                : t("screen.find.found.older_unknown")
              : t("screen.find.found.named", { name: sunroomName(found.name) })
            : saying(result)}
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
  const t = useT();
  const chosen = state.sunroom !== null;
  useEffect(() => {
    // Chosen here, or in another of this screen's pages meanwhile: open it.
    if (chosen) go("/opening", true);
  }, [chosen]);
  return (
    <div className="flex w-full max-w-[110rem] flex-col gap-8">
      <h1 className="text-d-glance font-bold">{t("screen.find.title")}</h1>
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
          {t("app.action.back")}
        </Button>
      </div>
    </div>
  );
}
