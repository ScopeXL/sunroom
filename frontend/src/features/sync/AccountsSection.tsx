import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { qk } from "../../api/keys";
import { useT, type Key } from "../../lib/lang";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { ListRow } from "../../ui/ListRow";
import { useShell } from "../../ui/shell";
import { AccountSheet } from "./AccountSheet";
import { AddAccountSheet } from "./AddAccount";
import { statusLine, useAccounts, type Account } from "./data";

type GoogleOutcome = "connected" | "denied" | "expired" | "failed";

/** What the app says when Google's sign-in sends the browser back (google_accounts.callback). */
const GOOGLE_WORDS: Record<GoogleOutcome, Key> = {
  connected: "sync.signin.connected.toast",
  denied: "sync.signin.denied.toast",
  expired: "sync.signin.expired.toast",
  failed: "sync.signin.failed.toast",
};

function isOutcome(value: string): value is GoogleOutcome {
  return Object.hasOwn(GOOGLE_WORDS, value);
}

/** Back from Google's sign-in: `?google=<how it went>`, and `&account=<id>` for a new account. */
function googleReturn(): { outcome: GoogleOutcome; account: string | null } | null {
  try {
    const search = new URLSearchParams(window.location.search);
    const outcome = search.get("google") ?? "";
    if (!isOutcome(outcome)) return null;
    return { outcome, account: outcome === "connected" ? search.get("account") : null };
  } catch {
    return null;
  }
}

/**
 * The accounts part of Settings → Calendars & Accounts (UX §4): a row for each account, with
 * where it comes from and how it's doing; a tap opens its sheet (AccountSheet: Refresh now,
 * Sync, Show on the screen, Remove account). Add an account opens the same steps on a phone, a
 * computer or the wall screen (ADR 0028); on the wall, the device's kind (not its size) hands
 * the two Google ways that need a phone to one. Back from Google's sign-in it says how it went,
 * and opens a new account's calendars.
 */
export function AccountsSection() {
  const t = useT();
  const display = useShell() === "display";
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const kiosk = session?.device_kind === "kiosk";
  const { data: accounts = [] } = useAccounts();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get("add") === "1";
    } catch {
      return false;
    }
  });
  const [landing] = useState(googleReturn);
  const [returnedId, setReturnedId] = useState(landing?.account ?? null);
  const returned = accounts.find((account) => account.id === returnedId) ?? null;
  useEffect(() => {
    if (!landing) return;
    // Once: the address loses ?google=…, so a reload (or React's second look) says nothing.
    const url = new URL(window.location.href);
    if (!url.searchParams.has("google")) return;
    url.searchParams.delete("google");
    url.searchParams.delete("account");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    showToast(t(GOOGLE_WORDS[landing.outcome]));
  }, [landing, t]);
  const title = display ? "text-d-title font-bold" : "text-row font-bold";
  // As Settings' other groups: the page's title is the h2 on the wall, the h1 on a phone.
  const Heading = display ? "h3" : "h2";
  return (
    <section className={display ? "mb-10" : "mb-8"} aria-labelledby="accounts-title">
      <Heading id="accounts-title" className={`${title} ${display ? "mb-3" : "mb-2"}`}>
        {t("sync.accounts.title")}
      </Heading>
      {accounts.length === 0 ? (
        <p
          className={
            display ? "mb-4 text-d-secondary text-ink-soft" : "mb-3 text-secondary text-ink-soft"
          }
        >
          {t("sync.accounts.empty")}
        </p>
      ) : (
        <div
          className={`divide-y divide-line rounded-chip border border-line bg-surface ${
            display ? "px-6" : "px-4"
          }`}
        >
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              onOpen={() => {
                setEditingId(account.id);
              }}
            />
          ))}
        </div>
      )}
      <div className={display ? "mt-5" : "mt-4"}>
        <Button
          variant="secondary"
          onClick={() => {
            setAdding(true);
          }}
        >
          {t("sync.accounts.add.action")}
        </Button>
      </div>
      <AccountSheet
        account={accounts.find((account) => account.id === editingId) ?? null}
        kiosk={kiosk}
        onClose={() => {
          setEditingId(null);
        }}
      />
      <AddAccountSheet
        open={adding || returned !== null}
        kiosk={kiosk}
        returned={returned}
        onClose={() => {
          setAdding(false);
          setReturnedId(null);
        }}
      />
    </section>
  );
}

/** An account's row: its name, where it comes from, how it's doing, and how many of its
 * calendars are on the board. */
function AccountRow({ account, onOpen }: { account: Account; onOpen: () => void }) {
  const t = useT();
  const synced = account.calendars.filter((calendar) => calendar.mapped).length;
  const trouble = account.status === "needs_reconnect" || account.status === "error";
  return (
    <ListRow
      label={t("sync.accounts.edit.aria", { name: account.label })}
      title={account.label}
      subtitle={[account.address, statusLine(account)].filter(Boolean).join(", ")}
      subtitleShown={
        <>
          {account.address ? <span className="block break-all">{account.address}</span> : null}{" "}
          <span className={`block ${trouble ? "font-semibold text-alert" : ""}`}>
            {statusLine(account)}
          </span>
        </>
      }
      value={t("sync.accounts.calendars", { n: synced })}
      onClick={onOpen}
    />
  );
}
