import { useState } from "react";

import { useSettings, useUpdateSettings } from "../../lib/household";
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
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  if (!settings) return null;
  // The same test the wall's sun makes (lib/sun): without a place, 7 AM and 7 PM.
  const placed = settings.latitude !== null && settings.longitude !== null;
  return (
    <>
      <Group title="Look">
        <Row
          label="Theme"
          hint={
            placed
              ? "Auto turns dark at sunset and light at sunrise."
              : "Auto turns dark at 7 PM until a location is set in Household."
          }
        >
          <Segmented
            label="Theme"
            value={settings.theme}
            onChange={(theme) => {
              update.mutate({ theme });
            }}
            options={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
              { value: "auto", label: "Auto" },
            ]}
          />
        </Row>
        <Row label="Text size" hint="Small suits a screen around 1920×1080 that's read up close.">
          <Segmented
            label="Text size"
            value={settings.text_size}
            onChange={(text_size) => {
              update.mutate({ text_size });
            }}
            options={[
              { value: "small", label: "Small" },
              { value: "standard", label: "Standard" },
              { value: "large", label: "Large" },
              { value: "xl", label: "Extra large" },
            ]}
          />
        </Row>
        <Switch
          label="Daylight tint"
          hint="The background warms through the day: cool in the morning, golden in the afternoon, rosy at dusk. Off keeps the midday shade."
          checked={settings.daylight_tint}
          onChange={(daylight_tint) => {
            update.mutate({ daylight_tint });
          }}
        />
        <Switch
          label="Reduce motion"
          hint="Everything changes at once, without moving."
          checked={settings.display_reduce_motion}
          onChange={(display_reduce_motion) => {
            update.mutate({ display_reduce_motion });
          }}
        />
      </Group>
      <Group title="Layout">
        <Row label="Rail side" hint="Where the rooms sit, for a screen hung to one side.">
          <Segmented
            label="Rail side"
            value={settings.display_rail_side}
            onChange={(display_rail_side) => {
              update.mutate({ display_rail_side });
            }}
            options={[
              { value: "left", label: "Left" },
              { value: "right", label: "Right" },
            ]}
          />
        </Row>
        <Switch
          label="Compact rail"
          hint="Only the rooms' icons, so the board gets more room. Anyone can open it back out from the header."
          checked={settings.display_rail_compact}
          onChange={(display_rail_compact) => {
            update.mutate({ display_rail_compact });
          }}
        />
        <Row label="Home view" hint="What the screen shows until someone picks another view.">
          <Segmented
            label="Home view"
            value={settings.display_home_view}
            onChange={(display_home_view) => {
              update.mutate({ display_home_view });
            }}
            options={[
              { value: "week", label: "Week" },
              { value: "rolling", label: "Rolling Week" },
              { value: "today", label: "Today" },
              { value: "people", label: "People" },
            ]}
          />
        </Row>
        <Row
          label="When it starts"
          hint="What the screen shows after a refresh, an update or a restart."
        >
          <Segmented
            label="When it starts"
            value={settings.display_start}
            onChange={(display_start) => {
              update.mutate({ display_start });
            }}
            options={[
              { value: "last", label: "Where it left off" },
              { value: "home", label: "The home view" },
            ]}
          />
        </Row>
        <Row
          label="Week layout"
          hint="Agenda stacks each day's events; Hours draws them on a 24-hour grid."
        >
          <Segmented
            label="Week layout"
            value={settings.display_week_layout}
            onChange={(display_week_layout) => {
              update.mutate({ display_week_layout });
            }}
            options={[
              { value: "agenda", label: "Agenda" },
              { value: "hours", label: "Hours" },
            ]}
          />
        </Row>
        <Switch
          label="Show tips"
          hint="A line under the board with one thing Sunroom can do, changing every half hour. Not on phones."
          checked={settings.show_tips}
          onChange={(show_tips) => {
            update.mutate({ show_tips });
          }}
        />
        <Switch
          label="Dim past events"
          hint="Today's events that are over fade, so what's next stands out."
          checked={settings.display_dim_past}
          onChange={(display_dim_past) => {
            update.mutate({ display_dim_past });
          }}
        />
        <Switch
          label="Today panel"
          hint="Up next and the rest of today, beside the week."
          checked={settings.display_show_today_panel}
          onChange={(display_show_today_panel) => {
            update.mutate({ display_show_today_panel });
          }}
        />
        <Row
          label="Return to the calendar after"
          hint="How long Lists, Tasks, Settings and the other rooms stay open with nobody touching the screen. The board itself still comes back to today after 2 minutes."
        >
          <Segmented
            label="Return to the calendar after"
            value={String(settings.display_return_minutes) as "2" | "5" | "10" | "0"}
            onChange={(value) => {
              update.mutate({ display_return_minutes: Number(value) as 0 | 2 | 5 | 10 });
            }}
            options={[
              { value: "0", label: "Never" },
              { value: "2", label: "2 min" },
              { value: "5", label: "5 min" },
              { value: "10", label: "10 min" },
            ]}
          />
        </Row>
      </Group>
      <SleepGroup />
    </>
  );
}

function SleepGroup() {
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
      ? "Set both times."
      : from === to
        ? "Pick two different times."
        : null;
  return (
    <Group
      title="Sleep"
      note="At night the screen shows a dim clock, or goes dark. A tap wakes it for 2 minutes."
    >
      <Switch
        label="Sleep at night"
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
                label="From"
                type="time"
                layout="numeric"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                }}
                onBlur={saveTimes}
              />
              <TextField
                label="Until"
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
          <Row label="While asleep">
            <Segmented
              label="While asleep"
              value={settings.sleep_mode}
              onChange={(sleep_mode) => {
                update.mutate({ sleep_mode });
              }}
              options={[
                { value: "dim_clock", label: "Dim clock" },
                { value: "screen_off", label: "Screen off" },
              ]}
            />
          </Row>
          <Switch
            label="Dim in the evening"
            hint="From this time until it sleeps, the screen is less bright."
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
                    label="Dim from"
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
              <Row label="Brightness">
                <Segmented
                  label="Brightness"
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
