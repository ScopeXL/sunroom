import { useMutation } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { copyText } from "../../lib/copy";
import { useMembers, type Member } from "../../lib/household";
import { pageLocale, tRich, useT, type Key } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { lengthWords } from "../../ui/LengthField";
import { QrCode } from "../../ui/QrCode";
import { Select } from "../../ui/Select";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { sourceName, useHolidayPlaces, useSyncChanges, type Account } from "./data";
import { GoogleKeys, useGoogleKeys } from "./GoogleKeys";
import {
  GoogleIntegrateArt,
  GoogleSecretAddressArt,
  GoogleSettingsArt,
  HelperCalendarApiArt,
  HelperKeyArt,
  HelperProjectArt,
  HelperServiceAccountArt,
  AppleCopyPasswordArt,
  AppleNewPasswordArt,
  AppleSignInArt,
} from "./drawings";

type Step =
  | "choose"
  | "google"
  | "google-address"
  | "google-helper"
  | "google-signin"
  | "apple"
  | "server"
  | "address"
  | "holidays"
  | "pick";

const TITLES: Record<Step, Key> = {
  choose: "sync.add.title",
  google: "sync.add.google.title",
  "google-address": "sync.add.google_address.title",
  "google-helper": "sync.add.google_helper.title",
  "google-signin": "sync.add.google_signin.title",
  apple: "sync.add.apple.title",
  server: "sync.add.server.title",
  address: "sync.add.address.title",
  holidays: "sync.add.holidays.title",
  pick: "sync.add.pick.title",
};

/** Examples of an address in an empty field: addresses, not words. */
const ADDRESS_EXAMPLE = "https://…/calendar.ics";
const SERVER_EXAMPLE = "https://cloud.example.com";

/** The words' sizes: the wall screen's (read from across the room), or a phone's. */
function useText(): { body: string; secondary: string } {
  return useShell() === "display"
    ? { body: "text-d-body", secondary: "text-d-secondary" }
    : { body: "text-body", secondary: "text-secondary" };
}

/** This server's Calendars & Accounts on a signed-in device; `add`: with this sheet open. */
function deviceAddress(add = true): string {
  const path = add ? "/settings/calendars?add=1" : "/settings/calendars";
  try {
    return `${window.location.origin}${path}`;
  } catch {
    return path;
  }
}

/**
 * Add an account (UX §6) on any signed-in device or a paired screen (ADR 0028): Google (three
 * ways), Apple, a calendar server, any calendar address, or holidays. Each flow ends on the
 * account's calendars, with a switch and a person each, then Done. On a paired screen passwords
 * are masked fields on its own keyboard, behind the PIN; the two Google ways that need a device
 * (a key file, Google's own page) show a code to scan instead, and so does "Or add it from a
 * device" under the choices. Back from Google's sign-in, it opens on the new account's calendars.
 */
export function AddAccountSheet({
  open,
  onClose,
  kiosk = false,
  returned = null,
}: {
  open: boolean;
  onClose: () => void;
  /** The wall screen: no files, no Google page, and nothing that opens a browser tab. */
  kiosk?: boolean;
  /** An account Google's sign-in just added: the sheet opens on its calendars. */
  returned?: Account | null;
}) {
  const t = useT();
  const [chosen, setStep] = useState<Step>("choose");
  const [connected, setAccount] = useState<Account | null>(null);
  const step = returned ? "pick" : chosen;
  const account = returned ?? connected;
  const close = () => {
    setStep("choose");
    setAccount(null);
    onClose();
  };
  const picked = (next: Account) => {
    setAccount(next);
    setStep("pick");
  };
  return (
    <Sheet open={open} title={t(TITLES[step])} onClose={close} step={step}>
      {step === "choose" ? (
        <div className="flex flex-col gap-6">
          <Choices
            options={[
              // Apple first: the owner's order (ADR 0032).
              { step: "apple", label: "sync.add.apple.label", line: "sync.add.apple.hint" },
              { step: "google", label: "sync.add.google.label", line: "sync.add.google.hint" },
              {
                step: "holidays",
                label: "sync.add.holidays.label",
                line: "sync.add.holidays.hint",
              },
              { step: "address", label: "sync.add.address.label", line: "sync.add.address.hint" },
              { step: "server", label: "sync.add.server.label", line: "sync.add.server.hint" },
            ]}
            onPick={setStep}
          />
          {kiosk ? (
            <DeviceShortcut lead={t("sync.add.device.label")} line={t("sync.add.device.hint")} />
          ) : null}
        </div>
      ) : step === "google" ? (
        <Choices
          options={[
            {
              step: "google-address",
              label: "sync.add.google_address.label",
              line: "sync.add.google_address.hint",
            },
            {
              step: "google-helper",
              label: "sync.add.google_helper.label",
              line: "sync.add.google_helper.hint",
              device: kiosk,
            },
            {
              step: "google-signin",
              label: "sync.add.google_signin.label",
              line: "sync.add.google_signin.hint",
              device: kiosk,
            },
          ]}
          onPick={setStep}
        />
      ) : step === "google-address" ? (
        <AddressFlow google kiosk={kiosk} onDone={close} />
      ) : step === "address" ? (
        <AddressFlow kiosk={kiosk} onDone={close} />
      ) : step === "holidays" ? (
        <HolidaysFlow onDone={close} />
      ) : step === "apple" ? (
        <ServerFlow apple kiosk={kiosk} onConnected={picked} />
      ) : step === "server" ? (
        <ServerFlow kiosk={kiosk} onConnected={picked} />
      ) : step === "google-helper" ? (
        kiosk ? (
          <FromDevice why={t("sync.add.google_helper.device")} />
        ) : (
          <HelperFlow onFound={picked} />
        )
      ) : step === "google-signin" ? (
        kiosk ? (
          <FromDevice why={t("sync.add.google_signin.device")} />
        ) : (
          <SignInFlow />
        )
      ) : account ? (
        <PickCalendars account={account} onDone={close} />
      ) : null}
    </Sheet>
  );
}

function Choices({
  options,
  onPick,
}: {
  /** `device`: on a paired screen, a way that needs a signed-in device, marked "From a device". */
  options: { step: Step; label: Key; line: Key; device?: boolean }[];
  onPick: (step: Step) => void;
}) {
  const t = useT();
  const text = useText();
  return (
    <ul className="flex flex-col gap-3">
      {options.map((option) => (
        <li key={option.step}>
          <button
            type="button"
            onClick={() => {
              onPick(option.step);
            }}
            className="press-row flex min-h-16 w-full flex-col items-start justify-center rounded-button border-2 border-line bg-surface px-4 py-3 text-left"
          >
            <span className={`${text.body} font-semibold`}>{t(option.label)}</span>
            <span className={`${text.secondary} text-ink-soft`}>{t(option.line)}</span>
            {option.device ? (
              <span className={`${text.secondary} mt-1 flex items-center gap-2 font-semibold`}>
                <Smartphone aria-hidden="true" className="size-6" />
                {t("sync.add.from_device")}
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * On a paired screen, what only a signed-in device can do, one scan away (ADR 0028, 0034): a
 * code that opens Calendars & Accounts there, beside what to do. Under Add an Account's choices
 * (with the sheet open); and in an account's sheet, where Google's own sign-in page is the one
 * thing a screen can't open (`add` false).
 */
export function DeviceShortcut({
  lead,
  line,
  add = true,
}: {
  lead: string;
  line?: string;
  add?: boolean;
}) {
  const t = useT();
  const text = useText();
  return (
    <div className="flex items-center gap-5 rounded-panel border border-line bg-wall p-4">
      <QrCode
        value={deviceAddress(add)}
        label={add ? t("sync.device.add.aria") : t("sync.device.calendars.aria")}
        className="size-32 shrink-0"
      />
      <div className="flex flex-col gap-1">
        <p className={`${text.body} font-semibold`}>{lead}</p>
        {line ? <p className={`${text.secondary} text-ink-soft`}>{line}</p> : null}
      </div>
    </div>
  );
}

/** A way a paired screen can't do itself (ADR 0028): a code that opens it on a device. */
function FromDevice({ why }: { why: string }) {
  const t = useT();
  const text = useText();
  return (
    <div className="flex flex-col items-center gap-5 text-center">
      <p className={`${text.body} font-semibold`}>{t("sync.device.lead")}</p>
      <p className={text.body}>{why}</p>
      <QrCode value={deviceAddress()} label={t("sync.device.add.aria")} />
      <p className={`${text.secondary} text-ink-soft`}>{t("sync.device.scan")}</p>
    </div>
  );
}

/** Numbered steps. With drawings under them, more room between, so each step's words sit with
 * its own drawing rather than the one above. */
function Steps({ children }: { children: ReactNode }) {
  const text = useText();
  return (
    <ol className={`flex list-decimal flex-col gap-2 pl-5 ${text.body} has-[svg]:gap-6`}>
      {children}
    </ol>
  );
}

function Who({
  members,
  value,
  onChange,
}: {
  members: Member[];
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const t = useT();
  const text = useText();
  return (
    <div className="flex flex-col gap-2">
      <p className={`${text.body} font-semibold`}>{t("sync.who.label")}</p>
      <ChipRow label={t("sync.who.label")}>
        <Chip
          on={value === null}
          onClick={() => {
            onChange(null);
          }}
        >
          <Avatar member={null} size="xs" />
          {t("sync.who.everyone")}
        </Chip>
        {members.map((member) => (
          <Chip
            key={member.id}
            on={value === member.id}
            onClick={() => {
              onChange(member.id);
            }}
          >
            <Avatar member={member} size="xs" />
            {member.name}
          </Chip>
        ))}
      </ChipRow>
    </div>
  );
}

/** How often a calendar address is checked, in minutes; each chip says it as a length does. */
const INTERVALS = [15, 30, 60, 360];

/** Paste a calendar address (on the wall screen, type it): Google's secret address, or any
 * .ics link. */
function AddressFlow({
  google = false,
  kiosk = false,
  onDone,
}: {
  google?: boolean;
  kiosk?: boolean;
  onDone: () => void;
}) {
  const t = useT();
  const text = useText();
  const { data: members = [] } = useMembers();
  const { addIcs } = useSyncChanges();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [owner, setOwner] = useState<string | null>(null);
  const [minutes, setMinutes] = useState(30);
  const [home, setHome] = useState(false);
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!url.trim()) return;
        addIcs.mutate(
          {
            url: url.trim(),
            label: name.trim() || null,
            owner_member_id: owner,
            interval_min: minutes,
            allow_private: home,
          },
          { onSuccess: onDone },
        );
      }}
    >
      {google ? (
        <Steps>
          <li>
            {t("sync.address.google.settings")}
            <GoogleSettingsArt />
          </li>
          <li>
            {t("sync.address.google.integrate")}
            <GoogleIntegrateArt />
          </li>
          <li>
            {kiosk ? t("sync.address.google.type") : t("sync.address.google.copy")}
            <GoogleSecretAddressArt />
          </li>
        </Steps>
      ) : (
        <p className={text.body}>{kiosk ? t("sync.address.type") : t("sync.address.paste")}</p>
      )}
      <TextField
        label={t("sync.address.url.label")}
        type="url"
        inputMode="url"
        autoCapitalize="none"
        autoComplete="off"
        placeholder={ADDRESS_EXAMPLE}
        value={url}
        onChange={(event) => {
          setUrl(event.target.value);
        }}
        error={addIcs.isError ? errorMessage(addIcs.error) : null}
      />
      <TextField
        label={t("sync.address.name.label")}
        autoComplete="off"
        maxLength={80}
        value={name}
        placeholder={google ? t("sync.address.name.family") : t("sync.address.name.school")}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <Who members={members} value={owner} onChange={setOwner} />
      <div className="flex flex-col gap-2">
        <p className={`${text.body} font-semibold`}>{t("sync.address.interval.label")}</p>
        <ChipRow label={t("sync.address.interval.label")}>
          {INTERVALS.map((every) => (
            <Chip
              key={every}
              on={minutes === every}
              onClick={() => {
                setMinutes(every);
              }}
            >
              {lengthWords(every)}
            </Chip>
          ))}
        </ChipRow>
      </div>
      {google ? null : (
        <Switch
          label={t("sync.home.label")}
          hint={t("sync.home.hint")}
          checked={home}
          onChange={setHome}
        />
      )}
      <Button type="submit" block pending={addIcs.isPending} disabled={!url.trim()}>
        {t("sync.address.add.action")}
      </Button>
    </form>
  );
}

/** A country's name in the page's language ("United States"), or its code if `Intl` lacks it. */
function regionName(code: string): string {
  try {
    return new Intl.DisplayNames([pageLocale()], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * The country to start on. The browser's own tag says where the family is (en-GB: the United
 * Kingdom, es-MX: Mexico), which the page's language can't (es-ES for every Spanish household),
 * so it comes first; the page's locale only when the browser's says nothing Intl can read.
 */
function guessCountry(): string {
  for (const tag of [navigator.language, pageLocale()]) {
    try {
      const region = new Intl.Locale(tag).maximize().region;
      if (region) return region;
    } catch {
      // Not a tag Intl knows: the next one.
    }
  }
  return "US";
}

function HolidaysFlow({ onDone }: { onDone: () => void }) {
  const t = useT();
  const text = useText();
  const { data: places = [] } = useHolidayPlaces();
  const { data: members = [] } = useMembers();
  const { addHolidays } = useSyncChanges();
  const [country, setCountry] = useState(guessCountry);
  const [region, setRegion] = useState("");
  const [owner, setOwner] = useState<string | null>(null);
  const locale = pageLocale();
  const sorted = [...places].sort((a, b) =>
    regionName(a.country).localeCompare(regionName(b.country), locale),
  );
  const regions = places.find((place) => place.country === country)?.subdivisions ?? [];
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        addHolidays.mutate(
          { country, subdivision: region || null, owner_member_id: owner },
          { onSuccess: onDone },
        );
      }}
    >
      <label className="flex flex-col gap-2">
        <span className={`${text.body} font-semibold`}>{t("sync.holidays.country.label")}</span>
        <Select
          value={country}
          onChange={(event) => {
            setCountry(event.target.value);
            setRegion("");
          }}
        >
          {sorted.map((place) => (
            <option key={place.country} value={place.country}>
              {regionName(place.country)}
            </option>
          ))}
        </Select>
      </label>
      {regions.length ? (
        <label className="flex flex-col gap-2">
          <span className={`${text.body} font-semibold`}>{t("sync.holidays.region.label")}</span>
          <Select
            value={region}
            onChange={(event) => {
              setRegion(event.target.value);
            }}
          >
            <option value="">{t("sync.holidays.region.all")}</option>
            {regions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </label>
      ) : null}
      <Who members={members} value={owner} onChange={setOwner} />
      {addHolidays.isError ? (
        <p role="alert" className={`${text.body} font-semibold text-alert`}>
          {errorMessage(addHolidays.error)}
        </p>
      ) : null}
      <Button type="submit" block pending={addHolidays.isPending}>
        {t("sync.holidays.add.action")}
      </Button>
    </form>
  );
}

/**
 * Apple (iCloud's CalDAV, with an app-specific password) or another CalDAV server (its address
 * and login). On a paired screen, the steps at Apple happen on another device, and the password
 * is typed here.
 */
function ServerFlow({
  apple = false,
  kiosk = false,
  onConnected,
}: {
  apple?: boolean;
  kiosk?: boolean;
  onConnected: (account: Account) => void;
}) {
  const t = useT();
  const text = useText();
  const { addCaldav } = useSyncChanges();
  const [server, setServer] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [home, setHome] = useState(false);
  const ready = user.trim() && password.trim() && (apple || server.trim());
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        addCaldav.mutate(
          {
            server_url: apple ? "https://caldav.icloud.com" : server.trim(),
            username: user.trim(),
            app_password: password.trim(),
            label: null,
            allow_private: !apple && home,
          },
          { onSuccess: onConnected },
        );
      }}
    >
      {apple ? (
        <>
          <Steps>
            <li>
              {kiosk
                ? tRich("sync.apple.step.sign_in_elsewhere", {
                    address: "appleid.apple.com",
                    b: (words) => <span className="font-semibold">{words}</span>,
                  })
                : tRich("sync.apple.step.sign_in", {
                    address: "appleid.apple.com",
                    link: (words) => (
                      <a
                        href="https://appleid.apple.com"
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold underline"
                      >
                        {words}
                      </a>
                    ),
                  })}
              <AppleSignInArt />
            </li>
            <li>
              {t("sync.apple.step.new_password")}
              <AppleNewPasswordArt />
            </li>
            <li>
              {kiosk ? t("sync.apple.step.type_password") : t("sync.apple.step.copy_password")}
              <AppleCopyPasswordArt />
            </li>
          </Steps>
          <p className={`${text.secondary} text-ink-soft`}>{t("sync.apple.note")}</p>
        </>
      ) : (
        <TextField
          label={t("sync.server.address.label")}
          type="url"
          inputMode="url"
          autoCapitalize="none"
          autoComplete="off"
          placeholder={SERVER_EXAMPLE}
          value={server}
          onChange={(event) => {
            setServer(event.target.value);
          }}
        />
      )}
      <TextField
        label={apple ? t("sync.apple.email.label") : t("sync.server.user.label")}
        type={apple ? "email" : "text"}
        autoCapitalize="none"
        autoComplete="username"
        value={user}
        onChange={(event) => {
          setUser(event.target.value);
        }}
      />
      <TextField
        label={apple ? t("sync.apple.password.label") : t("sync.server.password.label")}
        type="password"
        layout="password"
        autoComplete="off"
        value={password}
        onChange={(event) => {
          setPassword(event.target.value);
        }}
        error={addCaldav.isError ? errorMessage(addCaldav.error) : null}
      />
      {apple ? null : (
        <Switch
          label={t("sync.home.label")}
          hint={t("sync.home.hint")}
          checked={home}
          onChange={setHome}
        />
      )}
      <Button type="submit" block pending={addCaldav.isPending} disabled={!ready}>
        {addCaldav.isPending
          ? t("sync.account.connecting.action")
          : t("sync.account.connect.action")}
      </Button>
    </form>
  );
}

/** Google's helper (a service account the family makes once, never called that here). */
function HelperFlow({ onFound }: { onFound: (account: Account) => void }) {
  const t = useT();
  const text = useText();
  const display = useShell() === "display";
  const [account, setAccount] = useState<Account | null>(null);
  const [calendarId, setCalendarId] = useState("");
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text();
      return asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/google/service-account", {
            body: { key_json: text, label: null },
          }),
        ),
      );
    },
    onSuccess: setAccount,
  });
  const find = useMutation({
    mutationFn: async () =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/{account_id}/google/add-calendar", {
            params: { path: { account_id: account?.id ?? "" } },
            body: { calendar_id: calendarId.trim() },
          }),
        ),
      ),
    onSuccess: onFound,
  });
  if (!account) {
    return (
      <div className="flex flex-col gap-5">
        <p className={text.body}>{t("sync.helper.intro")}</p>
        <Steps>
          <li>
            {tRich("sync.helper.step.project", {
              address: "console.cloud.google.com",
              link: (words) => (
                <a
                  href="https://console.cloud.google.com"
                  target="_blank"
                  rel="noreferrer"
                  className="font-semibold underline"
                >
                  {words}
                </a>
              ),
            })}
            <HelperProjectArt />
          </li>
          <li>
            {t("sync.helper.step.api")}
            <HelperCalendarApiArt />
          </li>
          <li>
            {t("sync.helper.step.service_account")}
            <HelperServiceAccountArt />
          </li>
          <li>
            {t("sync.helper.step.key")}
            <HelperKeyArt />
          </li>
        </Steps>
        {/* The app's own button, not the browser's "Choose File" (as Add photos). */}
        <label
          className={`press inline-flex cursor-pointer items-center justify-center self-start border-2 border-line bg-surface font-semibold has-focus-visible:outline-[3px] has-focus-visible:outline-offset-2 has-focus-visible:outline-ink ${
            display ? "min-h-tap rounded-button-d px-7" : "min-h-11 rounded-button px-5"
          } ${text.body}`}
        >
          {t("sync.helper.upload.action")}
          <input
            type="file"
            accept="application/json,.json"
            className="sr-only"
            disabled={upload.isPending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) upload.mutate(file);
            }}
          />
        </label>
        {upload.isError ? (
          <p role="alert" className={`${text.body} font-semibold text-alert`}>
            {errorMessage(upload.error)}
          </p>
        ) : null}
        {upload.isPending ? (
          <p className={`${text.secondary} text-ink-soft`}>{t("sync.helper.checking")}</p>
        ) : null}
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (calendarId.trim()) find.mutate();
      }}
    >
      <div className="flex flex-col gap-2">
        <p className={`${text.body} font-semibold`}>{t("sync.helper.address.label")}</p>
        <p className={`rounded-button bg-wall px-3 py-2 ${text.secondary} break-all select-all`}>
          {account.helper_email}
        </p>
        <div>
          <Button
            variant="secondary"
            onClick={() => {
              void copyText(account.helper_email ?? "").then((copied) => {
                showToast(
                  copied ? t("sync.helper.copied.toast") : t("sync.helper.copy_failed.toast"),
                );
              });
            }}
          >
            {t("app.action.copy")}
          </Button>
        </div>
      </div>
      <p className={text.body}>{t("sync.helper.share")}</p>
      <TextField
        label={t("sync.helper.calendar_id.label")}
        autoCapitalize="none"
        hint={t("sync.helper.calendar_id.hint")}
        autoComplete="off"
        value={calendarId}
        onChange={(event) => {
          setCalendarId(event.target.value);
        }}
        error={find.isError ? errorMessage(find.error) : null}
      />
      <Button type="submit" block pending={find.isPending} disabled={!calendarId.trim()}>
        {t("sync.helper.find.action")}
      </Button>
    </form>
  );
}

/** Sign in with Google: only where Google allows the way back (https, or this computer itself,
 * as the server's check: google_accounts.sign_in_allowed). */
function SignInFlow() {
  const t = useT();
  const text = useText();
  const keys = useGoogleKeys();
  const secure = (() => {
    try {
      const { protocol, hostname } = window.location;
      return protocol === "https:" || hostname === "localhost" || hostname === "127.0.0.1";
    } catch {
      return false;
    }
  })();
  const start = useMutation({
    mutationFn: async () =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/calendar-sync/accounts/google/start", {
            body: { account_id: null },
          }),
        ),
      ),
    onSuccess: (result) => {
      window.location.assign(result.authorize_url);
    },
  });
  if (!secure) {
    return <p className={text.body}>{t("sync.signin.insecure")}</p>;
  }
  return (
    <div className="flex flex-col gap-5">
      <Steps>
        <li>{t("sync.signin.step.client")}</li>
        <li>
          {t("sync.signin.step.redirect", {
            address: `${window.location.origin}/api/calendar-sync/google/callback`,
          })}
        </li>
        <li>{t("sync.signin.step.consent")}</li>
        <li>{t("sync.signin.step.paste")}</li>
      </Steps>
      {/* The keys live here, the one step that uses them (ADR 0030). */}
      <GoogleKeys firstSave={t("sync.keys.save_continue.action")} />
      {keys.ready ? (
        <>
          <p className={`${text.secondary} text-ink-soft`}>{t("sync.signin.unverified")}</p>
          {start.isError ? (
            <p role="alert" className={`${text.body} font-semibold text-alert`}>
              {errorMessage(start.error)}
            </p>
          ) : null}
          <Button
            block
            pending={start.isPending}
            onClick={() => {
              start.mutate();
            }}
          >
            {t("sync.signin.action")}
          </Button>
        </>
      ) : null}
    </div>
  );
}

/** After connecting: which calendars go on the board, and whose each is. */
function PickCalendars({ account, onDone }: { account: Account; onDone: () => void }) {
  const t = useT();
  const text = useText();
  const { data: members = [] } = useMembers();
  const { map } = useSyncChanges();
  const [choices, setChoices] = useState(() =>
    Object.fromEntries(
      account.calendars.map((c) => [c.id, { on: true, owner: c.suggested_owner_id ?? null }]),
    ),
  );
  const [saving, setSaving] = useState(false);
  const chosen = account.calendars.filter((c) => choices[c.id]?.on);
  const done = async () => {
    setSaving(true);
    try {
      for (const calendar of chosen) {
        await map.mutateAsync({
          account: account.id,
          calendar: calendar.id,
          body: { mapped: true, owner_member_id: choices[calendar.id]?.owner ?? null },
        });
      }
      showToast(t("sync.pick.connected.toast", { source: sourceName(account), n: chosen.length }));
      onDone();
    } finally {
      setSaving(false);
    }
  };
  if (account.calendars.length === 0) {
    return <p className={text.body}>{t("sync.pick.empty")}</p>;
  }
  return (
    <div className="flex flex-col gap-5">
      {account.calendars.map((calendar) => {
        const choice = choices[calendar.id] ?? { on: false, owner: null };
        return (
          <div key={calendar.id} className="flex flex-col gap-2 border-b border-line pb-4">
            <Switch
              label={calendar.name}
              hint={calendar.read_only ? t("sync.calendar.read_only") : undefined}
              checked={choice.on}
              onChange={(on) => {
                setChoices({ ...choices, [calendar.id]: { ...choice, on } });
              }}
            />
            {choice.on ? (
              <ChipRow label={t("sync.calendar.whose.aria", { name: calendar.name })}>
                <Chip
                  on={choice.owner === null}
                  onClick={() => {
                    setChoices({ ...choices, [calendar.id]: { ...choice, owner: null } });
                  }}
                >
                  {t("sync.who.everyone")}
                </Chip>
                {members.map((member) => (
                  <Chip
                    key={member.id}
                    on={choice.owner === member.id}
                    onClick={() => {
                      setChoices({ ...choices, [calendar.id]: { ...choice, owner: member.id } });
                    }}
                  >
                    <Avatar member={member} size="xs" />
                    {member.name}
                  </Chip>
                ))}
              </ChipRow>
            ) : null}
          </div>
        );
      })}
      {map.isError ? (
        <p role="alert" className={`${text.body} font-semibold text-alert`}>
          {errorMessage(map.error)}
        </p>
      ) : null}
      <Button block pending={saving} onClick={() => void done()}>
        {t("app.action.done")}
      </Button>
    </div>
  );
}
