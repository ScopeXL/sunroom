import { useState } from "react";

import { useSettings, useUpdateSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useSavedFlash } from "../../lib/savedFlash";
import { SavedMark } from "../../ui/SavedMark";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { Group, Row } from "./parts";

/**
 * Settings → Display (UX §4): how the wall screen looks and when it sleeps. Settings whose
 * effect arrives with a later milestone (sounds, the screensaver, forcing an orientation) join
 * this page with it.
 */
export function DisplayPage() {
  const t = useT();
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  if (!settings) return null;
  // The same test the wall's sun makes (lib/sun): without a place, 7 AM and 7 PM.
  const placed = settings.latitude !== null && settings.longitude !== null;
  return (
    <>
      <Group title={t("settings.display.look.title")}>
        <Row
          label={t("settings.display.theme.label")}
          hint={
            placed ? t("settings.display.theme.hint") : t("settings.display.theme.unplaced.hint")
          }
        >
          <Segmented
            label={t("settings.display.theme.label")}
            value={settings.theme}
            onChange={(theme) => {
              update.mutate({ theme });
            }}
            options={[
              { value: "light", label: t("settings.display.theme.light") },
              { value: "dark", label: t("settings.display.theme.dark") },
              { value: "auto", label: t("settings.display.theme.auto") },
            ]}
          />
        </Row>
        <Row
          label={t("settings.display.text_size.label")}
          hint={t("settings.display.text_size.hint")}
        >
          <Segmented
            label={t("settings.display.text_size.label")}
            value={settings.text_size}
            onChange={(text_size) => {
              update.mutate({ text_size });
            }}
            options={[
              { value: "small", label: t("settings.display.text_size.small") },
              { value: "standard", label: t("settings.display.text_size.standard") },
              { value: "large", label: t("settings.display.text_size.large") },
              { value: "xl", label: t("settings.display.text_size.xl") },
            ]}
          />
        </Row>
        <Switch
          label={t("settings.display.tint.label")}
          hint={t("settings.display.tint.hint")}
          checked={settings.daylight_tint}
          onChange={(daylight_tint) => {
            update.mutate({ daylight_tint });
          }}
        />
        <Switch
          label={t("settings.display.motion.label")}
          hint={t("settings.display.motion.hint")}
          checked={settings.display_reduce_motion}
          onChange={(display_reduce_motion) => {
            update.mutate({ display_reduce_motion });
          }}
        />
      </Group>
      <Group title={t("settings.display.layout.title")}>
        <Row
          label={t("settings.display.rail_side.label")}
          hint={t("settings.display.rail_side.hint")}
        >
          <Segmented
            label={t("settings.display.rail_side.label")}
            value={settings.display_rail_side}
            onChange={(display_rail_side) => {
              update.mutate({ display_rail_side });
            }}
            options={[
              { value: "left", label: t("settings.display.rail_side.left") },
              { value: "right", label: t("settings.display.rail_side.right") },
            ]}
          />
        </Row>
        <Switch
          label={t("settings.display.compact.label")}
          hint={t("settings.display.compact.hint")}
          checked={settings.display_rail_compact}
          onChange={(display_rail_compact) => {
            update.mutate({ display_rail_compact });
          }}
        />
        <Row
          label={t("settings.display.home_view.label")}
          hint={t("settings.display.home_view.hint")}
        >
          <Segmented
            label={t("settings.display.home_view.label")}
            value={settings.display_home_view}
            onChange={(display_home_view) => {
              update.mutate({ display_home_view });
            }}
            options={[
              { value: "week", label: t("settings.display.home_view.week") },
              { value: "rolling", label: t("settings.display.home_view.rolling") },
              { value: "today", label: t("settings.display.home_view.today") },
              { value: "people", label: t("settings.display.home_view.people") },
            ]}
          />
        </Row>
        <Row label={t("settings.display.start.label")} hint={t("settings.display.start.hint")}>
          <Segmented
            label={t("settings.display.start.label")}
            value={settings.display_start}
            onChange={(display_start) => {
              update.mutate({ display_start });
            }}
            options={[
              { value: "last", label: t("settings.display.start.last") },
              { value: "home", label: t("settings.display.start.home") },
            ]}
          />
        </Row>
        <Row
          label={t("settings.display.week_layout.label")}
          hint={t("settings.display.week_layout.hint")}
        >
          <Segmented
            label={t("settings.display.week_layout.label")}
            value={settings.display_week_layout}
            onChange={(display_week_layout) => {
              update.mutate({ display_week_layout });
            }}
            options={[
              { value: "agenda", label: t("settings.display.week_layout.agenda") },
              { value: "hours", label: t("settings.display.week_layout.hours") },
            ]}
          />
        </Row>
        <Switch
          label={t("settings.display.tips.label")}
          hint={t("settings.display.tips.hint")}
          checked={settings.show_tips}
          onChange={(show_tips) => {
            update.mutate({ show_tips });
          }}
        />
        <Switch
          label={t("settings.display.dim_past.label")}
          hint={t("settings.display.dim_past.hint")}
          checked={settings.display_dim_past}
          onChange={(display_dim_past) => {
            update.mutate({ display_dim_past });
          }}
        />
        <Switch
          label={t("settings.display.today_panel.label")}
          hint={t("settings.display.today_panel.hint")}
          checked={settings.display_show_today_panel}
          onChange={(display_show_today_panel) => {
            update.mutate({ display_show_today_panel });
          }}
        />
        <Row label={t("settings.display.return.label")} hint={t("settings.display.return.hint")}>
          <Segmented
            label={t("settings.display.return.label")}
            value={String(settings.display_return_minutes) as "2" | "5" | "10" | "0"}
            onChange={(value) => {
              update.mutate({ display_return_minutes: Number(value) as 0 | 2 | 5 | 10 });
            }}
            options={[
              { value: "0", label: t("settings.display.return.never") },
              { value: "2", label: t("settings.display.return.minutes", { n: 2 }) },
              { value: "5", label: t("settings.display.return.minutes", { n: 5 }) },
              { value: "10", label: t("settings.display.return.minutes", { n: 10 }) },
            ]}
          />
        </Row>
      </Group>
      <SleepGroup />
    </>
  );
}

function SleepGroup() {
  const t = useT();
  const display = useShell() === "display";
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const [from, setFrom] = useState(settings?.sleep_from ?? "22:00");
  const [to, setTo] = useState(settings?.sleep_to ?? "06:30");
  const [dimFrom, setDimFrom] = useState(settings?.dim_from ?? "20:00");
  const timesSaved = useSavedFlash();
  const dimSaved = useSavedFlash();
  if (!settings) return null;
  const on = settings.sleep_from !== null && settings.sleep_to !== null;
  const isTime = (value: string) => /^\d{2}:\d{2}$/.test(value);
  const valid = isTime(from) && isTime(to) && from !== to;
  // The two times save together, when either field is left with both set (ADR 0029).
  const saveTimes = () => {
    if (!valid || (from === settings.sleep_from && to === settings.sleep_to)) return;
    update.mutate({ sleep_from: from, sleep_to: to }, { onSuccess: timesSaved.flash });
  };
  const saveDim = () => {
    if (!isTime(dimFrom) || dimFrom === settings.dim_from) return;
    update.mutate({ dim_from: dimFrom }, { onSuccess: dimSaved.flash });
  };
  const timesHint =
    !isTime(from) || !isTime(to)
      ? t("settings.display.sleep.both.hint")
      : from === to
        ? t("settings.display.sleep.different.hint")
        : null;
  return (
    <Group title={t("settings.display.sleep.title")} note={t("settings.display.sleep.note")}>
      <Switch
        label={t("settings.display.sleep.label")}
        checked={on}
        onChange={(value) => {
          update.mutate(
            value ? { sleep_from: from, sleep_to: to } : { sleep_from: null, sleep_to: null },
          );
        }}
      />
      {on ? (
        <>
          <div className={`flex flex-col gap-1 ${display ? "py-5" : "py-4"}`}>
            <form
              className="flex flex-wrap items-end gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                saveTimes();
              }}
            >
              <TextField
                label={t("settings.display.sleep.from.label")}
                type="time"
                layout="numeric"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                }}
                onBlur={saveTimes}
              />
              <TextField
                label={t("settings.display.sleep.until.label")}
                type="time"
                layout="numeric"
                value={to}
                onChange={(event) => {
                  setTo(event.target.value);
                }}
                onBlur={saveTimes}
              />
            </form>
            {timesHint ? (
              <p
                className={
                  display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"
                }
              >
                {timesHint}
              </p>
            ) : (
              <SavedMark show={timesSaved.saved} />
            )}
          </div>
          <Row label={t("settings.display.asleep.label")}>
            <Segmented
              label={t("settings.display.asleep.label")}
              value={settings.sleep_mode}
              onChange={(sleep_mode) => {
                update.mutate({ sleep_mode });
              }}
              options={[
                { value: "dim_clock", label: t("settings.display.asleep.dim_clock") },
                { value: "screen_off", label: t("settings.display.asleep.screen_off") },
              ]}
            />
          </Row>
          <Switch
            label={t("settings.display.dim.label")}
            hint={t("settings.display.dim.hint")}
            checked={settings.dim_from !== null}
            onChange={(value) => {
              update.mutate({ dim_from: value ? dimFrom : null });
            }}
          />
          {settings.dim_from !== null ? (
            <>
              <form
                className={`flex flex-col gap-1 ${display ? "py-5" : "py-4"}`}
                onSubmit={(event) => {
                  event.preventDefault();
                  saveDim();
                }}
              >
                <div className="flex">
                  <TextField
                    label={t("settings.display.dim.from.label")}
                    type="time"
                    layout="numeric"
                    value={dimFrom}
                    onChange={(event) => {
                      setDimFrom(event.target.value);
                    }}
                    onBlur={saveDim}
                  />
                </div>
                <SavedMark show={dimSaved.saved} />
              </form>
              <Row label={t("settings.display.brightness.label")}>
                <Segmented
                  label={t("settings.display.brightness.label")}
                  value={String(settings.dim_level) as "60" | "40" | "20"}
                  onChange={(value) => {
                    update.mutate({ dim_level: Number(value) as 20 | 40 | 60 });
                  }}
                  options={[
                    { value: "60", label: "60%" },
                    { value: "40", label: "40%" },
                    { value: "20", label: "20%" },
                  ]}
                />
              </Row>
            </>
          ) : null}
        </>
      ) : null}
    </Group>
  );
}
