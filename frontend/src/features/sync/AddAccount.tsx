import { useMutation } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { copyText } from "../../lib/copy";
import { useMembers, type Member } from "../../lib/household";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
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

const TITLES: Record<Step, string> = {
  choose: "Add an Account",
  google: "Google",
  "google-address": "Google: The Secret Address",
  "google-helper": "Google: Share with a Helper",
  "google-signin": "Sign in with Google",
  apple: "Apple",
  server: "A Calendar Server",
  address: "Another Calendar",
  holidays: "Holidays",
  pick: "Pick Calendars",
};

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
    <Sheet open={open} title={TITLES[step]} onClose={close} step={step}>
      {step === "choose" ? (
        <div className="flex flex-col gap-6">
          <Choices
            options={[
              // Apple first: the owner's order (ADR 0032).
              {
                step: "apple",
                label: "Apple",
                line: "Your iPhone's and Mac's calendars, both ways.",
              },
              { step: "google", label: "Google", line: "Google Calendar, three ways to connect." },
              { step: "holidays", label: "Holidays", line: "Public holidays, no address needed." },
              {
                step: "address",
                label: "Another calendar",
                line: "Any calendar address (.ics): school, team, Outlook.",
              },
              {
                step: "server",
                label: "A calendar server",
                line: "Nextcloud, Fastmail and others, with a user name and password.",
              },
            ]}
            onPick={setStep}
          />
          {kiosk ? (
            <DeviceShortcut
              lead="Or add it from a device"
              line="Scan this with a parent's phone."
            />
          ) : null}
        </div>
      ) : step === "google" ? (
        <Choices
          options={[
            {
              step: "google-address",
              label: "Paste the secret address",
              line: "Easiest. Shows events only; you can't add from Sunroom. Google updates it slowly (sometimes hours).",
            },
            {
              step: "google-helper",
              label: "Share with a Sunroom helper",
              line: "About 10 minutes, once. Lets you add and change events from Sunroom.",
              device: kiosk,
            },
            {
              step: "google-signin",
              label: "Sign in with Google",
              line: "Needs Sunroom at an https:// address on the internet and your own Google app keys, which it asks for here.",
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
          <FromDevice why="It needs a key file from Google, and this screen can't open files." />
        ) : (
          <HelperFlow onFound={picked} />
        )
      ) : step === "google-signin" ? (
        kiosk ? (
          <FromDevice why="Google's sign-in page doesn't work on this screen." />
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
  options: { step: Step; label: string; line: string; device?: boolean }[];
  onPick: (step: Step) => void;
}) {
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
            <span className={`${text.body} font-semibold`}>{option.label}</span>
            <span className={`${text.secondary} text-ink-soft`}>{option.line}</span>
            {option.device ? (
              <span className={`${text.secondary} mt-1 flex items-center gap-2 font-semibold`}>
                <Smartphone aria-hidden="true" className="size-6" />
                From a device
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
  const text = useText();
  return (
    <div className="flex items-center gap-5 rounded-panel border border-line bg-wall p-4">
      <QrCode
        value={deviceAddress(add)}
        label={
          add
            ? "A code that opens Add an Account on a device"
            : "A code that opens Calendars & Accounts on a device"
        }
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
  const text = useText();
  return (
    <div className="flex flex-col items-center gap-5 text-center">
      <p className={`${text.body} font-semibold`}>Do this from a device</p>
      <p className={text.body}>{why}</p>
      <QrCode value={deviceAddress()} label="A code that opens Add an Account on a device" />
      <p className={`${text.secondary} text-ink-soft`}>
        Scan this with a parent's phone, or open Settings → Calendars & Accounts on a signed-in
        device.
      </p>
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
  const text = useText();
  return (
    <div className="flex flex-col gap-2">
      <p className={`${text.body} font-semibold`}>Whose calendar</p>
      <ChipRow label="Whose calendar">
        <Chip
          on={value === null}
          onClick={() => {
            onChange(null);
          }}
        >
          <Avatar member={null} size="xs" />
          Everyone
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

const INTERVALS = [
  { minutes: 15, label: "15 min" },
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 360, label: "6 hours" },
];

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
            On a computer, open Google Calendar's settings.
            <GoogleSettingsArt />
          </li>
          <li>
            Under “Settings for my calendars”, pick the calendar, then Integrate calendar.
            <GoogleIntegrateArt />
          </li>
          <li>
            {kiosk
              ? "Type the address under “Secret address in iCal format” here."
              : "Copy “Secret address in iCal format” and paste it here."}
            <GoogleSecretAddressArt />
          </li>
        </Steps>
      ) : (
        <p className={text.body}>
          {kiosk ? "Type" : "Paste"} the calendar's address. School and team sites, Outlook's
          “Publish calendar” and Apple's public calendars all give one.
        </p>
      )}
      <TextField
        label="Calendar address"
        type="url"
        inputMode="url"
        autoCapitalize="none"
        autoComplete="off"
        placeholder="https://…/calendar.ics"
        value={url}
        onChange={(event) => {
          setUrl(event.target.value);
        }}
        error={addIcs.isError ? errorMessage(addIcs.error) : null}
      />
      <TextField
        label="Name (optional)"
        autoComplete="off"
        maxLength={80}
        value={name}
        placeholder={google ? "Family" : "School"}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <Who members={members} value={owner} onChange={setOwner} />
      <div className="flex flex-col gap-2">
        <p className={`${text.body} font-semibold`}>Check for changes every</p>
        <ChipRow label="Check for changes every">
          {INTERVALS.map((option) => (
            <Chip
              key={option.minutes}
              on={minutes === option.minutes}
              onClick={() => {
                setMinutes(option.minutes);
              }}
            >
              {option.label}
            </Chip>
          ))}
        </ChipRow>
      </div>
      {google ? null : (
        <Switch
          label="This server is on your home network"
          hint="Only for a server at home: a parent's tick lets Sunroom reach a home address."
          checked={home}
          onChange={setHome}
        />
      )}
      <Button type="submit" block pending={addIcs.isPending} disabled={!url.trim()}>
        Add Calendar
      </Button>
    </form>
  );
}

function regionName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

function HolidaysFlow({ onDone }: { onDone: () => void }) {
  const text = useText();
  const { data: places = [] } = useHolidayPlaces();
  const { data: members = [] } = useMembers();
  const { addHolidays } = useSyncChanges();
  const guess = (() => {
    try {
      return new Intl.Locale(navigator.language).maximize().region ?? "US";
    } catch {
      return "US";
    }
  })();
  const [country, setCountry] = useState(guess);
  const [region, setRegion] = useState("");
  const [owner, setOwner] = useState<string | null>(null);
  const sorted = [...places].sort((a, b) =>
    regionName(a.country).localeCompare(regionName(b.country)),
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
        <span className={`${text.body} font-semibold`}>Country</span>
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
          <span className={`${text.body} font-semibold`}>State or region (optional)</span>
          <Select
            value={region}
            onChange={(event) => {
              setRegion(event.target.value);
            }}
          >
            <option value="">The whole country</option>
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
        Add Holidays
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
              {kiosk ? (
                <>
                  On another device, open <span className="font-semibold">appleid.apple.com</span>{" "}
                  and sign in.
                </>
              ) : (
                <>
                  Open{" "}
                  <a
                    href="https://appleid.apple.com"
                    target="_blank"
                    rel="noreferrer"
                    className="font-semibold underline"
                  >
                    appleid.apple.com
                  </a>{" "}
                  and sign in.
                </>
              )}
              <AppleSignInArt />
            </li>
            <li>
              Under Sign-In and Security, tap App-Specific Passwords, then the plus, and name it
              Sunroom.
              <AppleNewPasswordArt />
            </li>
            <li>
              {kiosk
                ? "Type the password it shows (xxxx-xxxx-xxxx-xxxx) below."
                : "Copy the password it shows (xxxx-xxxx-xxxx-xxxx) and paste it below."}
              <AppleCopyPasswordArt />
            </li>
          </Steps>
          <p className={`${text.secondary} text-ink-soft`}>
            Two-factor authentication has to be on for your Apple Account. Your Apple Account's own
            doesn't work here.
          </p>
        </>
      ) : (
        <TextField
          label="Server address"
          type="url"
          inputMode="url"
          autoCapitalize="none"
          autoComplete="off"
          placeholder="https://cloud.example.com"
          value={server}
          onChange={(event) => {
            setServer(event.target.value);
          }}
        />
      )}
      <TextField
        label={apple ? "Apple Account email" : "User name"}
        type={apple ? "email" : "text"}
        autoCapitalize="none"
        autoComplete="username"
        value={user}
        onChange={(event) => {
          setUser(event.target.value);
        }}
      />
      <TextField
        label={apple ? "App-specific password" : "Password"}
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
          label="This server is on your home network"
          hint="Only for a server at home: a parent's tick lets Sunroom reach a home address."
          checked={home}
          onChange={setHome}
        />
      )}
      <Button type="submit" block pending={addCaldav.isPending} disabled={!ready}>
        {addCaldav.isPending ? "Connecting…" : "Connect"}
      </Button>
    </form>
  );
}

/** Google's helper (a service account the family makes once, never called that here). */
function HelperFlow({ onFound }: { onFound: (account: Account) => void }) {
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
        <p className={text.body}>
          You'll make a helper account at Google and share your calendar with it.
        </p>
        <Steps>
          <li>
            Open{" "}
            <a
              href="https://console.cloud.google.com"
              target="_blank"
              rel="noreferrer"
              className="font-semibold underline"
            >
              console.cloud.google.com
            </a>{" "}
            and make a project named Sunroom.
            <HelperProjectArt />
          </li>
          <li>
            In APIs & Services, enable the Google Calendar API.
            <HelperCalendarApiArt />
          </li>
          <li>
            In IAM & Admin → Service accounts, create one named sunroom.
            <HelperServiceAccountArt />
          </li>
          <li>
            Open it, then Keys → Add key → JSON. A file downloads.
            <HelperKeyArt />
          </li>
        </Steps>
        {/* The app's own button, not the browser's "Choose File" (as Add photos). */}
        <label
          className={`press inline-flex cursor-pointer items-center justify-center self-start border-2 border-line bg-surface font-semibold has-focus-visible:outline-[3px] has-focus-visible:outline-offset-2 has-focus-visible:outline-ink ${
            display ? "min-h-tap rounded-button-d px-7" : "min-h-11 rounded-button px-5"
          } ${text.body}`}
        >
          Upload the Key File
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
          <p className={`${text.secondary} text-ink-soft`}>Checking the key…</p>
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
        <p className={`${text.body} font-semibold`}>Your helper's address:</p>
        <p className={`rounded-button bg-wall px-3 py-2 ${text.secondary} break-all select-all`}>
          {account.helper_email}
        </p>
        <div>
          <Button
            variant="secondary"
            onClick={() => {
              void copyText(account.helper_email ?? "").then((copied) => {
                showToast(
                  copied
                    ? "Copied the helper's address"
                    : "Couldn't copy here. Hold the address to copy it.",
                );
              });
            }}
          >
            Copy
          </Button>
        </div>
      </div>
      <p className={text.body}>
        In Google Calendar's settings, pick the calendar, go to Share with specific people, paste
        the helper's address, choose Make changes to events, and Send.
      </p>
      <TextField
        label="The calendar's ID"
        autoCapitalize="none"
        hint="Your Gmail address for your main calendar; another calendar's ID is under Integrate calendar."
        autoComplete="off"
        value={calendarId}
        onChange={(event) => {
          setCalendarId(event.target.value);
        }}
        error={find.isError ? errorMessage(find.error) : null}
      />
      <Button type="submit" block pending={find.isPending} disabled={!calendarId.trim()}>
        Find Calendar
      </Button>
    </form>
  );
}

/** Sign in with Google: only where Google allows the way back (https, or this computer itself,
 * as the server's check: google_accounts.sign_in_allowed). */
function SignInFlow() {
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
    return (
      <p className={text.body}>
        Google only signs in to apps at an https:// address. Use Share with a Sunroom helper
        instead, or set up an https address for Sunroom first (docs/REMOTE-ACCESS.md).
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      <Steps>
        <li>In Google Cloud, make an OAuth client of type Web application.</li>
        <li>
          Add this redirect address to it: {window.location.origin}
          /api/calendar-sync/google/callback
        </li>
        <li>
          Set the consent screen to External and publish it. If it stays in Testing, Google signs
          Sunroom out every 7 days.
        </li>
        <li>Paste the client ID and secret below.</li>
      </Steps>
      {/* The keys live here, the one step that uses them (ADR 0030). */}
      <GoogleKeys firstSave="Save Keys and Continue" />
      {keys.ready ? (
        <>
          <p className={`${text.secondary} text-ink-soft`}>
            Google may say the app isn't verified: tap Advanced, then Go to Sunroom. It's your own
            app.
          </p>
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
            Sign in with Google
          </Button>
        </>
      ) : null}
    </div>
  );
}

/** After connecting: which calendars go on the board, and whose each is. */
function PickCalendars({ account, onDone }: { account: Account; onDone: () => void }) {
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
      showToast(
        `Connected ${sourceName(account)} · ${String(chosen.length)} ${chosen.length === 1 ? "calendar" : "calendars"}`,
      );
      onDone();
    } finally {
      setSaving(false);
    }
  };
  if (account.calendars.length === 0) {
    return (
      <p className={text.body}>
        No calendars there yet. Sharing can take a minute; try again from Calendars & Accounts.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {account.calendars.map((calendar) => {
        const choice = choices[calendar.id] ?? { on: false, owner: null };
        return (
          <div key={calendar.id} className="flex flex-col gap-2 border-b border-line pb-4">
            <Switch
              label={calendar.name}
              hint={calendar.read_only ? "Shows events only" : undefined}
              checked={choice.on}
              onChange={(on) => {
                setChoices({ ...choices, [calendar.id]: { ...choice, on } });
              }}
            />
            {choice.on ? (
              <ChipRow label={`Whose is ${calendar.name}`}>
                <Chip
                  on={choice.owner === null}
                  onClick={() => {
                    setChoices({ ...choices, [calendar.id]: { ...choice, owner: null } });
                  }}
                >
                  Everyone
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
        Done
      </Button>
    </div>
  );
}
