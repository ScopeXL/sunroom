import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { isLoopbackAddress } from "../../lib/address";
import { weekdayLong } from "../../lib/dates";
import { useMembers } from "../../lib/household";
import { setLanguage, tRich, useLanguage, useT, type Key } from "../../lib/lang";
import { keepPairing } from "../../lib/screenAgent";
import { rememberSignedIn } from "../../lib/session";
import { previewTheme, type ThemeChoice } from "../../lib/theme";
import { Avatar } from "../../ui/Avatar";
import { AddPersonRow, type RoleChoice } from "../settings/AddPersonRow";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { QrCode } from "../../ui/QrCode";
import { Segmented } from "../../ui/Segmented";
import { Select } from "../../ui/Select";
import { TextField } from "../../ui/TextField";
import { usePluginModules } from "../usePluginModules";
import { LanguageButton, LanguagePicker } from "./LanguageButton";
import { SetupEnd, SetupFrame, StepActions, useSetupType } from "./SetupFrame";

export type SetupStep =
  "welcome" | "password" | "household" | "place" | "people" | "pin" | "calendars" | "done";
export const SIGNED_IN_STEPS: SetupStep[] = ["place", "people", "pin", "calendars", "done"];

function phoneZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

/** 12- or 24-hour, as the phone shows time. */
function phoneTimeFormat(): "12h" | "24h" {
  try {
    const cycle = new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions()
      .hourCycle;
    return cycle === "h23" || cycle === "h24" ? "24h" : "12h";
  } catch {
    return "12h";
  }
}

/** The household password's least length (auth/password.py's MIN_PASSWORD_LENGTH; ADR 0034). */
const MIN_PASSWORD = 8;

/** Names to start from, in the page's language; the step starts with the first (ADR 0034). */
const IDEAS: readonly Key[] = [
  "setup.household.idea.home",
  "setup.household.idea.family",
  "setup.household.idea.our_home",
];

function zones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

/** The wizard on the wall screen itself (ADR 0039), which keeps its step and its ways out. */
export interface OnScreen {
  go: (next: SetupStep) => void;
  /** Back from the first step, to the page before setup. */
  leave: () => void;
  /** All Done!'s Open Sunroom: the board. */
  open: () => void;
  /** Where devices open Sunroom (All Done! shows it as a QR code). */
  address: string;
}

/**
 * First run (UX §6, PLAN §12.1): on whatever device opened Sunroom first, usually a phone. The
 * password and the household are set together in one request that closes setup for good and
 * signs this device in as a parent; the rest (the city, people, the PIN, calendars) uses the
 * normal routes, and each step can be done later from Settings. Pairing a screen isn't a step
 * (ADR 0030): the screen shows its code by itself once setup is done, and it's paired from More
 * → Pair a Display, or with the household password on the screen. The household step also
 * picks the theme, previewed on this page as it's chosen (ADR 0034).
 *
 * On the wall screen itself (`onScreen`, ADR 0039) the same steps make that screen a paired one
 * instead: nobody is bound to it, and the PIN it sets opens its ten minutes for the last step.
 */
export function SetupWizard({ step, onScreen }: { step: SetupStep; onScreen?: OnScreen }) {
  const t = useT();
  const navigate = useNavigate();
  const go =
    onScreen?.go ??
    ((next: SetupStep) => {
      void navigate({ to: "/setup", search: { step: next } });
    });
  const [password, setPassword] = useState("");
  switch (step) {
    case "welcome":
      return (
        <SetupEnd title={t("setup.welcome.title")}>
          <p>{t("setup.welcome.lead")}</p>
          <Button
            block
            className="lg:min-h-16 lg:w-auto lg:min-w-72 lg:text-d-body"
            onClick={() => {
              go("password");
            }}
          >
            {t("setup.welcome.start.action")}
          </Button>
          <LanguageButton />
        </SetupEnd>
      );
    case "password":
      return (
        <PasswordStep
          password={password}
          onPassword={setPassword}
          onBack={onScreen?.leave}
          onNext={() => {
            go("household");
          }}
        />
      );
    case "household":
      return (
        <HouseholdStep
          password={password}
          onScreen={onScreen !== undefined}
          onBack={() => {
            go("password");
          }}
          onDone={() => {
            go("place");
          }}
        />
      );
    case "place":
      return (
        <PlaceStep
          onNext={() => {
            go("people");
          }}
        />
      );
    case "people":
      return (
        <PeopleStep
          onScreen={onScreen !== undefined}
          onNext={() => {
            go("pin");
          }}
        />
      );
    case "pin":
      return (
        <PinStep
          onScreen={onScreen !== undefined}
          onNext={() => {
            go("calendars");
          }}
        />
      );
    case "calendars":
      return (
        <CalendarsStep
          onNext={() => {
            go("done");
          }}
        />
      );
    case "done":
      if (onScreen) return <ScreenDone address={onScreen.address} onOpen={onScreen.open} />;
      return (
        <SetupEnd title={t("setup.done.title")} done>
          <p>{t("setup.done.ready")}</p>
          <Button
            block
            className="lg:min-h-16 lg:w-auto lg:min-w-72 lg:text-d-body"
            onClick={() => {
              void navigate({ to: "/" });
            }}
          >
            {t("setup.done.open.action")}
          </Button>
          <p className="text-ink-soft">{t("setup.done.sign_in")}</p>
        </SetupEnd>
      );
  }
}

/** All Done! on the wall screen (ADR 0039, ADR 0042): how other devices join, then the board. */
function ScreenDone({ address, onOpen }: { address: string; onOpen: () => void }) {
  const t = useT();
  return (
    <SetupEnd title={t("setup.done.title")} done>
      {isLoopbackAddress(address) ? (
        <p>{t("setup.done.screen.loopback")}</p>
      ) : (
        <>
          <QrCode
            value={address}
            label={t("setup.done.screen.qr.aria", { address })}
            className="size-56"
          />
          <p>
            {tRich("setup.done.screen.address", {
              address,
              b: (words) => <span className="font-bold">{words}</span>,
            })}
          </p>
        </>
      )}
      <Button className="min-w-72" onClick={onOpen}>
        {t("setup.done.open.action")}
      </Button>
    </SetupEnd>
  );
}

function PasswordStep({
  password,
  onPassword,
  onBack,
  onNext,
}: {
  password: string;
  onPassword: (value: string) => void;
  /** On the wall, the way back to the page before setup. */
  onBack?: (() => void) | undefined;
  onNext: () => void;
}) {
  const t = useT();
  const { data: status } = useQuery({
    queryKey: qk.setupStatus(),
    queryFn: async () => unwrap(await api.GET("/api/setup/status")),
  });
  const [visible, setVisible] = useState(false);
  const fromServer = status?.password_from_env ?? false;
  const least = fromServer ? 1 : MIN_PASSWORD;
  const short = !fromServer && password.length > 0 && password.length < MIN_PASSWORD;
  return (
    <SetupFrame
      step="password"
      title={fromServer ? t("setup.password.type.title") : t("setup.password.set.title")}
      lead={fromServer ? t("setup.password.type.lead") : t("setup.password.set.lead")}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (password.length >= least) onNext();
        }}
      >
        <TextField
          label={t("setup.password.label")}
          type={visible ? "text" : "password"}
          layout="password"
          autoComplete="new-password"
          autoCapitalize="none"
          value={password}
          hint={fromServer ? null : t("setup.password.hint")}
          error={short ? t("setup.password.short.error") : null}
          onChange={(event) => {
            onPassword(event.target.value);
          }}
        />
        <Button
          variant="secondary"
          className="self-start"
          aria-pressed={visible}
          onClick={() => {
            setVisible((value) => !value);
          }}
        >
          {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          {visible ? t("setup.password.hide.action") : t("setup.password.show.action")}
        </Button>
        <StepActions
          back={
            onBack ? (
              <Button variant="quiet" block onClick={onBack}>
                {t("app.action.back")}
              </Button>
            ) : undefined
          }
        >
          <Button type="submit" block disabled={password.length < least}>
            {t("app.action.next")}
          </Button>
        </StepActions>
      </form>
    </SetupFrame>
  );
}

function HouseholdStep({
  password,
  onScreen,
  onBack,
  onDone,
}: {
  password: string;
  onScreen: boolean;
  onBack: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const type = useSetupType();
  // The page's language is the household's: chosen here or on Choose a Language before.
  const language = useLanguage();
  // Home until a name is typed or picked, in the page's language as it changes above.
  const [typed, setName] = useState<string | null>(null);
  const name = typed ?? t("setup.household.idea.home");
  const [zone, setZone] = useState(phoneZone);
  const [changingZone, setChangingZone] = useState(false);
  const [weekStart, setWeekStart] = useState<"6" | "0">("6");
  const [theme, setTheme] = useState<ThemeChoice>("auto");
  // The choice shows on this page at once, as the Display page's does on the wall.
  const pickTheme = (choice: ThemeChoice) => {
    setTheme(choice);
    previewTheme(choice, { display: onScreen });
  };
  const setup = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/setup", {
          body: {
            password,
            household_name: name.trim(),
            timezone: zone,
            week_starts_on: Number(weekStart),
            time_format: phoneTimeFormat(),
            theme,
            language: language === "pseudo" ? "en" : language,
            on_screen: onScreen,
          },
        }),
      ),
    onSuccess: async (session) => {
      // A paired screen is never offered the offline start a phone gets (lib/session), and its
      // browser writes the pairing to disk at once (ADR 0040).
      if (onScreen) keepPairing();
      else rememberSignedIn(true);
      queryClient.setQueryData(qk.session(), session);
      await queryClient.invalidateQueries({ queryKey: qk.setupStatus() });
      onDone();
    },
  });
  if (!password) {
    return (
      <SetupFrame step="household" title={t("setup.household.title")}>
        <p className={type.body}>{t("setup.household.no_password")}</p>
        <StepActions>
          <Button block onClick={onBack}>
            {t("app.action.back")}
          </Button>
        </StepActions>
      </SetupFrame>
    );
  }
  return (
    <SetupFrame step="household" title={t("setup.household.title")}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) setup.mutate();
        }}
      >
        <div className="flex flex-col gap-2">
          <span className={`${type.body} font-semibold`}>
            {t("setup.household.language.label")}
          </span>
          <LanguagePicker
            label={t("setup.household.language.label")}
            value={language}
            onChange={(code) => {
              void setLanguage(code);
            }}
          />
        </div>
        <TextField
          label={t("setup.household.name.label")}
          value={name}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <ChipRow label={t("setup.household.ideas.label")}>
          {IDEAS.map((idea) => (
            <Chip
              key={idea}
              on={name === t(idea)}
              onClick={() => {
                setName(t(idea));
              }}
            >
              {t(idea)}
            </Chip>
          ))}
        </ChipRow>
        <div className="flex flex-col gap-2">
          <span className={`${type.body} font-semibold`}>
            {t("setup.household.timezone.label")}
          </span>
          {changingZone ? (
            <Select
              aria-label={t("setup.household.timezone.label")}
              value={zone}
              onChange={(event) => {
                setZone(event.target.value);
              }}
            >
              {zones().map((option) => (
                <option key={option} value={option}>
                  {option.replaceAll("_", " ")}
                </option>
              ))}
            </Select>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <span className={type.body}>{zone.replaceAll("_", " ")}</span>
              <Button
                variant="quiet"
                onClick={() => {
                  setChangingZone(true);
                }}
              >
                {t("app.action.change")}
              </Button>
            </div>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <span className={`${type.body} font-semibold`}>
            {t("setup.household.week_start.label")}
          </span>
          <Segmented
            label={t("setup.household.week_start.label")}
            value={weekStart}
            onChange={setWeekStart}
            options={[
              { value: "6", label: weekdayLong(6) },
              { value: "0", label: weekdayLong(0) },
            ]}
          />
        </div>
        <div className="flex flex-col gap-2">
          <span className={`${type.body} font-semibold`}>{t("setup.household.theme.label")}</span>
          <Segmented
            label={t("setup.household.theme.label")}
            value={theme}
            onChange={pickTheme}
            options={[
              { value: "light", label: t("setup.household.theme.light") },
              { value: "dark", label: t("setup.household.theme.dark") },
              { value: "auto", label: t("setup.household.theme.auto") },
            ]}
          />
          <p className={`${type.secondary} text-ink-soft`}>{t("setup.household.theme.hint")}</p>
        </div>
        {setup.isError ? (
          <p role="alert" className="font-semibold text-alert">
            {errorMessage(setup.error)}
          </p>
        ) : null}
        <StepActions
          back={
            <Button variant="quiet" block onClick={onBack}>
              {t("app.action.back")}
            </Button>
          }
        >
          <Button type="submit" block pending={setup.isPending} disabled={!name.trim()}>
            {t("app.action.next")}
          </Button>
        </StepActions>
      </form>
    </SetupFrame>
  );
}

function PeopleStep({ onScreen, onNext }: { onScreen: boolean; onNext: () => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const type = useSetupType();
  const { data: members = [] } = useMembers();
  const first = members.length === 0;
  const add = useMutation({
    mutationFn: async ({ name, role }: { name: string; role: RoleChoice }) => {
      const member = unwrap(await api.POST("/api/members", { body: { name, role } }));
      if (first && !onScreen) {
        // The first person is whoever is setting up: this device is theirs (a screen is
        // everyone's).
        const session = unwrap(
          await api.PUT("/api/auth/member", { body: { member_id: member.id } }),
        );
        queryClient.setQueryData(qk.session(), session);
      }
      return member;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["members"] });
    },
  });
  return (
    <SetupFrame
      step="people"
      title={t("setup.people.title")}
      lead={first ? t("setup.people.first.lead") : t("setup.people.more.lead")}
    >
      {members.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {members.map((member) => (
            <li
              key={member.id}
              className={`flex items-center gap-3 border-2 border-line bg-surface ${
                onScreen ? "rounded-button-d px-4 py-3" : "rounded-button px-3 py-2"
              }`}
            >
              <Avatar member={member} size={onScreen ? "md" : "sm"} />
              <span className={`${onScreen ? "text-d-body" : "text-row"} font-semibold`}>
                {member.name}
              </span>
              <span className={`ml-auto ${type.secondary} text-ink-soft`}>
                {member.role === "kid"
                  ? t("setup.people.role.child")
                  : t("setup.people.role.parent")}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <AddPersonRow
        label={first ? t("setup.people.you.label") : t("setup.people.name.label")}
        action={first ? t("setup.people.add_me.action") : t("app.action.add")}
        primary={first}
        autoComplete={first ? "given-name" : "off"}
        pending={add.isPending}
        error={add.isError ? errorMessage(add.error) : null}
        onAdd={(name, role) => add.mutateAsync({ name, role })}
      />
      {!first ? (
        <StepActions>
          <Button block onClick={onNext}>
            {t("app.action.next")}
          </Button>
        </StepActions>
      ) : null}
    </SetupFrame>
  );
}

function PinStep({ onScreen, onNext }: { onScreen: boolean; onNext: () => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [pin, setPin] = useState("");
  const set = useMutation({
    mutationFn: async () => {
      const result = await api.PUT("/api/auth/pin", { body: { pin } });
      if (!result.response.ok) unwrap(result);
      // A paired screen is a parent's only with the PIN once there is one: the PIN just set
      // opens its ten minutes, for the calendars step (ADR 0039).
      if (onScreen) unwrap(await api.POST("/api/auth/pin/verify", { body: { pin } }));
    },
    onSuccess: async () => {
      if (onScreen) await queryClient.invalidateQueries({ queryKey: qk.session() });
      onNext();
    },
  });
  return (
    <SetupFrame step="pin" title={t("setup.pin.title")} lead={t("setup.pin.lead")}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (/^\d{4,6}$/.test(pin)) set.mutate();
        }}
      >
        <TextField
          label={t("setup.pin.label")}
          type="password"
          layout="numeric"
          inputMode="numeric"
          autoComplete="off"
          maxLength={6}
          value={pin}
          error={set.isError ? errorMessage(set.error) : null}
          onChange={(event) => {
            setPin(event.target.value.replace(/\D/g, ""));
          }}
        />
        <StepActions
          back={
            <Button variant="quiet" block onClick={onNext}>
              {t("setup.pin.action.later")}
            </Button>
          }
        >
          <Button type="submit" block pending={set.isPending} disabled={!/^\d{4,6}$/.test(pin)}>
            {t("setup.pin.action.set")}
          </Button>
        </StepActions>
      </form>
    </SetupFrame>
  );
}

/** Step 3: where home is, for the weather and the sunset, through the weather plugin's search.
 * With the plugin off, the step skips itself. */
function PlaceStep({ onNext }: { onNext: () => void }) {
  const t = useT();
  const Setup = usePluginModules().find((m) => m.id === "weather")?.onboarding;
  return (
    <SetupFrame step="place" title={t("setup.place.title")}>
      {Setup ? (
        <Setup onDone={onNext} />
      ) : (
        <StepActions>
          <Button block onClick={onNext}>
            {t("app.action.next")}
          </Button>
        </StepActions>
      )}
    </SetupFrame>
  );
}

/** Step 6 (UX first run): bring in calendars, through the calendar_sync plugin's own flows.
 * With the plugin off, the step skips itself. */
function CalendarsStep({ onNext }: { onNext: () => void }) {
  const t = useT();
  const Setup = usePluginModules().find((m) => m.id === "calendar_sync")?.onboarding;
  return (
    <SetupFrame step="calendars" title={t("setup.calendars.title")}>
      {Setup ? (
        <Setup onDone={onNext} />
      ) : (
        <StepActions>
          <Button block onClick={onNext}>
            {t("app.action.next")}
          </Button>
        </StepActions>
      )}
    </SetupFrame>
  );
}
