import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { useMembers, type Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { useFieldLabel } from "../../ui/Field";
import { ColorPicker, usedBy } from "../../ui/ColorPicker";
import { ListRow } from "../../ui/ListRow";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { DeviceShortcut } from "./AddAccount";
import { sourceName, statusLine, useSyncChanges, type Account, type RemoteCalendar } from "./data";
import { GoogleKeys } from "./GoogleKeys";

type View =
  | { kind: "account" }
  | { kind: "calendar"; id: string }
  | { kind: "reconnect" }
  | { kind: "remove" };

/** The color picker's radio group: a name for the form, never shown. */
const COLOR_GROUP = "synced-calendar-color";

function useText() {
  const display = useShell() === "display";
  return {
    display,
    body: display ? "text-d-body" : "text-body",
    soft: display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft",
  };
}

/** The paired screens' names, for "Show on Kitchen": none until a parent may ask. */
function useScreens(enabled: boolean): string[] {
  const { data: devices = [] } = useQuery({
    queryKey: qk.devices(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/auth/devices"))),
    enabled,
    staleTime: 30_000,
  });
  return devices.filter((device) => device.kind === "kiosk").map((device) => device.label);
}

/**
 * One account, opened from its row in Settings → Calendars & Accounts (UX §4, ADR 0029): how
 * it's doing, with Refresh now or the way to connect it again; **Sync**, a switch for each
 * calendar it has, a synced one's name opening that calendar's own page of the sheet (whose it
 * is, and its color when it's everyone's); **Show on Kitchen**, a switch for each synced
 * calendar, once a screen is paired; and Remove account, which asks first. Every switch and chip
 * saves as it changes: the sheet keeps no draft and shows what the server holds.
 */
/** An account's calendars as its sheet lists them: the ones that sync first, then by name. */
export function syncedFirst(calendars: readonly RemoteCalendar[]): string[] {
  return [...calendars]
    .sort((a, b) => Number(b.mapped) - Number(a.mapped) || a.name.localeCompare(b.name))
    .map((calendar) => calendar.id);
}

/** The calendars in an order fixed earlier; any found since go last, by name. */
function inOrder(calendars: readonly RemoteCalendar[], order: readonly string[]): RemoteCalendar[] {
  const at = (id: string) => {
    const index = order.indexOf(id);
    return index === -1 ? order.length : index;
  };
  return [...calendars].sort((a, b) => at(a.id) - at(b.id) || a.name.localeCompare(b.name));
}

export function AccountSheet({
  account,
  kiosk,
  onClose,
}: {
  account: Account | null;
  kiosk: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const [view, setView] = useState<View>({ kind: "account" });
  // The calendars that sync first, then by name: ordered as the sheet opens and kept while it's
  // open, so a row never moves under the finger that just switched it (ADR 0032).
  const [order, setOrder] = useState(() => syncedFirst(account?.calendars ?? []));
  // Another account (or this one opened again) starts on its first page, freshly ordered.
  const [shown, setShown] = useState(account?.id ?? null);
  if ((account?.id ?? null) !== shown) {
    setShown(account?.id ?? null);
    setView({ kind: "account" });
    setOrder(syncedFirst(account?.calendars ?? []));
  }
  const { data: members = [] } = useMembers();
  const screens = useScreens(account !== null);
  const calendar =
    view.kind === "calendar"
      ? (account?.calendars.find((candidate) => candidate.id === view.id) ?? null)
      : null;
  const back = () => {
    setView({ kind: "account" });
  };
  const title = !account
    ? t("sync.account.title")
    : calendar
      ? t("sync.account.edit.title", { name: calendar.name })
      : view.kind === "remove"
        ? t("sync.remove.title", { name: account.label })
        : view.kind === "reconnect"
          ? t("sync.reconnect.title", { source: sourceName(account) })
          : t("sync.account.edit.title", { name: account.label });
  return (
    <Sheet
      open={account !== null}
      title={title}
      step={calendar ? view.kind + calendar.id : view.kind}
      onClose={onClose}
    >
      {!account ? null : calendar ? (
        <CalendarPage account={account} calendar={calendar} members={members} onBack={back} />
      ) : view.kind === "remove" ? (
        <RemovePage account={account} onKeep={back} onRemoved={onClose} />
      ) : view.kind === "reconnect" ? (
        <ReconnectPage account={account} kiosk={kiosk} onBack={back} />
      ) : (
        <AccountPage
          account={account}
          order={order}
          members={members}
          screens={screens}
          kiosk={kiosk}
          onView={setView}
        />
      )}
    </Sheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const { display } = useText();
  return (
    <section className="flex flex-col">
      <h3 className={display ? "text-d-body font-bold" : "text-body font-bold"}>{title}</h3>
      <div className="flex flex-col divide-y divide-line">{children}</div>
    </section>
  );
}

function AccountPage({
  account,
  order,
  members,
  screens,
  kiosk,
  onView,
}: {
  account: Account;
  /** The calendars' order, fixed when the sheet opened (synced first, then by name). */
  order: readonly string[];
  members: Member[];
  screens: string[];
  kiosk: boolean;
  onView: (view: View) => void;
}) {
  const t = useT();
  const text = useText();
  const changes = useSyncChanges();
  const broken = account.status === "needs_reconnect";
  const google = account.provider === "google";
  // Google has no password to type again: its own page signs in, or the helper needs a new key.
  const signIn = useMutation({
    mutationFn: async () =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/google/start", {
            body: { account_id: account.id },
          }),
        ),
      ),
    onSuccess: (result) => {
      window.location.assign(result.authorize_url);
    },
  });
  const calendars = inOrder(account.calendars, order);
  const synced = calendars.filter((calendar) => calendar.mapped);
  const error = signIn.error ?? (changes.syncNow.isError ? changes.syncNow.error : null);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col">
          {account.address ? (
            <span className={`${text.soft} break-all`}>{account.address}</span>
          ) : null}
          <span
            className={
              broken || account.status === "error"
                ? `${text.display ? "text-d-secondary" : "text-secondary"} font-semibold text-alert`
                : text.soft
            }
          >
            {statusLine(account)}
          </span>
        </div>
        {!broken ? (
          <div className="flex">
            <Button
              variant="secondary"
              pending={changes.syncNow.isPending}
              disabled={account.syncing}
              onClick={() => {
                changes.syncNow.mutate(account);
              }}
            >
              {t("sync.account.refresh.action")}
            </Button>
          </div>
        ) : !google ? (
          <div className="flex">
            <Button
              onClick={() => {
                onView({ kind: "reconnect" });
              }}
            >
              {t("sync.account.reconnect.action")}
            </Button>
          </div>
        ) : account.helper_email ? (
          <p className={text.body}>{t("sync.account.helper_broken")}</p>
        ) : kiosk ? (
          <DeviceShortcut lead={t("sync.account.sign_in_device.label")} add={false} />
        ) : (
          <div className="flex">
            <Button
              pending={signIn.isPending}
              onClick={() => {
                signIn.mutate();
              }}
            >
              {t("sync.account.sign_in.action")}
            </Button>
          </div>
        )}
        {error ? (
          <p role="alert" className={`${text.body} font-semibold text-alert`}>
            {errorMessage(error)}
          </p>
        ) : null}
      </div>
      {/* An account that signed in with Google's own page: its app keys can be changed here,
          without starting the account over (ADR 0030). */}
      {google && !account.helper_email ? (
        <Section title={t("sync.account.keys.title")}>
          <div className={text.display ? "py-4" : "py-3"}>
            <GoogleKeys removable={false} />
          </div>
        </Section>
      ) : null}
      {account.calendars.length > 0 ? (
        <Section title={t("sync.account.sync.title")}>
          {calendars.map((calendar) => (
            <SyncRow
              key={calendar.id}
              account={account}
              calendar={calendar}
              members={members}
              onEdit={() => {
                onView({ kind: "calendar", id: calendar.id });
              }}
            />
          ))}
        </Section>
      ) : null}
      {screens.length > 0 && synced.length > 0 ? (
        <Section
          title={
            screens.length === 1
              ? t("sync.account.show_on.title", { screen: screens[0] ?? "" })
              : t("sync.account.show_on_screens.title")
          }
        >
          {synced.map((calendar) => (
            <Switch
              key={calendar.id}
              label={calendar.name}
              checked={calendar.visible_on_display}
              onChange={(visible) => {
                changes.map.mutate({
                  account: account.id,
                  calendar: calendar.id,
                  body: { visible_on_display: visible },
                });
              }}
            />
          ))}
        </Section>
      ) : null}
      <Button
        variant="quiet-danger"
        block
        onClick={() => {
          onView({ kind: "remove" });
        }}
      >
        {t("sync.account.remove.action")}
      </Button>
    </div>
  );
}

/** One of the account's calendars under Sync: its switch, and once it's synced, its name is a
 * row that opens its page. */
function SyncRow({
  account,
  calendar,
  members,
  onEdit,
}: {
  account: Account;
  calendar: RemoteCalendar;
  members: Member[];
  onEdit: () => void;
}) {
  const t = useT();
  const text = useText();
  const changes = useSyncChanges();
  const owner = members.find((member) => member.id === calendar.owner_member_id) ?? null;
  const notes = [
    calendar.mapped
      ? owner
        ? t("sync.calendar.owner", { name: owner.name })
        : t("sync.calendar.everyones")
      : null,
    calendar.read_only ? t("sync.calendar.read_only") : null,
    calendar.last_error,
  ].filter(Boolean);
  return (
    <div className="flex items-center gap-3">
      {calendar.mapped ? (
        <ListRow
          label={t("sync.calendar.edit.aria", { name: calendar.name })}
          leading={
            owner ? (
              <Avatar member={owner} size="sm" />
            ) : (
              <span
                aria-hidden="true"
                data-person={calendar.color ?? undefined}
                className={`shrink-0 rounded-full bg-p ${text.display ? "size-8" : "size-6"}`}
              />
            )
          }
          title={calendar.name}
          subtitle={notes.join(" · ")}
          onClick={onEdit}
        />
      ) : (
        <div
          className={`flex min-w-0 flex-1 flex-col justify-center py-2 ${
            text.display ? "min-h-tap-primary" : "min-h-14"
          }`}
        >
          <span className={`truncate ${text.display ? "text-d-body" : "text-row"}`}>
            {calendar.name}
          </span>
          {notes.length ? <span className={text.soft}>{notes.join(" · ")}</span> : null}
        </div>
      )}
      <label
        className={`flex shrink-0 cursor-pointer items-center justify-center ${
          text.display ? "min-h-tap min-w-tap" : "min-h-11 min-w-11"
        }`}
      >
        <input
          type="checkbox"
          role="switch"
          aria-label={t("sync.calendar.sync.aria", { name: calendar.name })}
          checked={calendar.mapped}
          onChange={(event) => {
            const mapped = event.target.checked;
            changes.map.mutate({
              account: account.id,
              calendar: calendar.id,
              body: {
                mapped,
                owner_member_id: mapped ? (calendar.suggested_owner_id ?? null) : null,
              },
            });
          }}
          className={`switch ${text.display ? "switch-d" : ""}`}
        />
      </label>
    </div>
  );
}

/** A synced calendar's own page: whose it is, and its color when it's everyone's. */
function CalendarPage({
  account,
  calendar,
  members,
  onBack,
}: {
  account: Account;
  calendar: RemoteCalendar;
  members: Member[];
  onBack: () => void;
}) {
  const t = useT();
  const text = useText();
  const label = useFieldLabel();
  const changes = useSyncChanges();
  const owner = members.find((member) => member.id === calendar.owner_member_id) ?? null;
  const map = (body: Parameters<typeof changes.map.mutate>[0]["body"]) => {
    changes.map.mutate({ account: account.id, calendar: calendar.id, body });
  };
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <p className={label}>{t("sync.calendar.whose.label")}</p>
        <ChipRow label={t("sync.calendar.whose.aria", { name: calendar.name })}>
          <Chip
            on={owner === null}
            onClick={() => {
              map({ clear_owner: true });
            }}
          >
            <Avatar member={null} size="xs" />
            {t("sync.who.everyone")}
          </Chip>
          {members.map((member) => (
            <Chip
              key={member.id}
              on={owner?.id === member.id}
              onClick={() => {
                map({ owner_member_id: member.id });
              }}
            >
              <Avatar member={member} size="xs" />
              {member.name}
            </Chip>
          ))}
        </ChipRow>
      </div>
      {owner === null ? (
        <ColorPicker
          name={COLOR_GROUP}
          value={calendar.color}
          used={usedBy(members)}
          onChange={(color) => {
            map({ color });
          }}
        />
      ) : (
        <p className={text.soft}>{t("sync.calendar.owner_color", { name: owner.name })}</p>
      )}
      {changes.map.isError ? (
        <p role="alert" className={`${text.body} font-semibold text-alert`}>
          {errorMessage(changes.map.error)}
        </p>
      ) : null}
      <Button variant="secondary" block onClick={onBack}>
        {t("sync.account.back.action", { name: account.label })}
      </Button>
    </div>
  );
}

function RemovePage({
  account,
  onKeep,
  onRemoved,
}: {
  account: Account;
  onKeep: () => void;
  onRemoved: () => void;
}) {
  const t = useT();
  const text = useText();
  const changes = useSyncChanges();
  return (
    <div className="flex flex-col gap-4">
      <p className={text.body}>
        {account.provider === "holidays"
          ? t("sync.remove.holidays")
          : t("sync.remove.account", { source: sourceName(account) })}
      </p>
      {changes.disconnect.isError ? (
        <p role="alert" className={`${text.body} font-semibold text-alert`}>
          {errorMessage(changes.disconnect.error)}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="danger"
          pending={changes.disconnect.isPending}
          onClick={() => {
            changes.disconnect.mutate(account, { onSuccess: onRemoved });
          }}
        >
          {t("sync.remove.confirm.action", { name: account.label })}
        </Button>
        <Button variant="secondary" onClick={onKeep}>
          {t("sync.remove.keep.action")}
        </Button>
      </div>
    </div>
  );
}

/** A new password or address for an account that stopped working; on the wall screen it's
 * typed on the screen's own keyboard, and Apple's page is opened on a phone or computer. */
function ReconnectPage({
  account,
  kiosk,
  onBack,
}: {
  account: Account;
  kiosk: boolean;
  onBack: () => void;
}) {
  const t = useT();
  const text = useText();
  const changes = useSyncChanges();
  const [value, setValue] = useState("");
  const feed = account.provider === "ics";
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!value.trim()) return;
        changes.reconnect.mutate(
          feed ? { account, url: value.trim() } : { account, password: value.trim() },
          { onSuccess: onBack },
        );
      }}
    >
      <p className={text.body}>
        {feed
          ? kiosk
            ? t("sync.reconnect.address.type")
            : t("sync.reconnect.address.paste")
          : sourceName(account) === "Apple"
            ? kiosk
              ? t("sync.reconnect.apple.type", { address: "appleid.apple.com" })
              : t("sync.reconnect.apple.paste", { address: "appleid.apple.com" })
            : t("sync.reconnect.password")}
      </p>
      <TextField
        label={feed ? t("sync.address.url.label") : t("sync.server.password.label")}
        type={feed ? "url" : "password"}
        layout={feed ? "text" : "password"}
        autoCapitalize="none"
        autoComplete="off"
        value={value}
        error={changes.reconnect.isError ? errorMessage(changes.reconnect.error) : null}
        onChange={(event) => {
          setValue(event.target.value);
        }}
      />
      <Button type="submit" block pending={changes.reconnect.isPending} disabled={!value.trim()}>
        {t("sync.account.connect.action")}
      </Button>
      <Button variant="secondary" block onClick={onBack}>
        {t("sync.account.back.action", { name: account.label })}
      </Button>
    </form>
  );
}
