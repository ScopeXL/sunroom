import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useState } from "react";

import { errorMessage } from "../../api/client";
import { zonedParts } from "../../lib/dates";
import { useMembers, usePlugins, useSettings } from "../../lib/household";
import { useT, type Key } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { PanelActions } from "../../ui/PanelActions";
import { Chip, ChipRow } from "../../ui/Chip";
import { Field, useFieldLabel } from "../../ui/Field";
import { LengthField } from "../../ui/LengthField";
import { ListRow } from "../../ui/ListRow";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { Stepper } from "../../ui/Stepper";
import { TextField } from "../../ui/TextField";
import { TimeField } from "../../ui/TimeField";
import { WeekdayPicker } from "../../ui/WeekStrip";
import { WhoPicker } from "../../ui/WhoPicker";
import { Group, Text } from "../settings/parts";
import { PluginSettingsForm } from "../settings/PluginSettingsForm";
import { personOf } from "./ChoreBoard";
import {
  useChoreChanges,
  useChoreSettings,
  useRewards,
  useRoutines,
  type Reward,
  type Routine,
  type StepIn,
} from "./data";
import { STEP_ICONS, stepIcon } from "./icons";
import { RewardPanel } from "./RewardsPage";
import { clockText, customPoints } from "./words";

/** The steps a parent can add with a tap, each with its picture; a step's words are the
 * family's once added, in the language they were added in. */
const SUGGESTED_STEPS: { icon: string; title: Key }[] = [
  { icon: "toothbrush", title: "tasks.suggested_step.brush_teeth" },
  { icon: "shirt", title: "tasks.suggested_step.pajamas_on" },
  { icon: "bath", title: "tasks.suggested_step.bath" },
  { icon: "book", title: "tasks.suggested_step.read_book" },
  { icon: "bed", title: "tasks.suggested_step.into_bed" },
  { icon: "shirt", title: "tasks.suggested_step.get_dressed" },
  { icon: "plate", title: "tasks.suggested_step.breakfast" },
  { icon: "backpack", title: "tasks.suggested_step.pack_bag" },
  { icon: "shoes", title: "tasks.suggested_step.shoes_on" },
  { icon: "hands", title: "tasks.suggested_step.wash_hands" },
  { icon: "tidy", title: "tasks.suggested_step.tidy_up" },
  { icon: "dog", title: "tasks.suggested_step.feed_pet" },
];

/**
 * Settings → Chores (UX §3, §4): turn stars, rewards, routines and a parent's check on or off;
 * the rewards stars buy; the routines kids run; and giving or taking stars. Chores themselves
 * are added and changed in the Chores room.
 */
export function SettingsChores() {
  const t = useT();
  const { data: plugins = [] } = usePlugins();
  const plugin = plugins.find((p) => p.id === "chores");
  const settings = useChoreSettings();
  return (
    <>
      {plugin ? (
        <Group title={t("tasks.settings.include.title")}>
          <PluginSettingsForm
            pluginId="chores"
            spec={plugin.settings_spec}
            values={plugin.settings}
          />
        </Group>
      ) : null}
      {settings.rewards ? <RewardsGroup /> : null}
      {settings.routines ? <RoutinesGroup /> : null}
      {settings.stars ? <AdjustGroup /> : null}
    </>
  );
}

function RewardsGroup() {
  const t = useT();
  const display = useShell() === "display";
  const { data } = useRewards();
  const [editing, setEditing] = useState<Reward | "new" | null>(null);
  return (
    <Group title={t("tasks.settings.rewards.title")}>
      {data?.rewards.length === 0 ? (
        <div className={display ? "py-4" : "py-3"}>
          <Text soft>{t("tasks.rewards.none.hint")}</Text>
        </div>
      ) : null}
      {(data?.rewards ?? []).map((reward) => (
        <ListRow
          key={reward.id}
          label={t("tasks.edit.aria", { name: reward.title })}
          title={reward.title}
          value={`★${String(reward.cost_points)}`}
          onClick={() => {
            setEditing(reward);
          }}
        />
      ))}
      <div className={display ? "py-4" : "py-3"}>
        <Button
          variant="secondary"
          onClick={() => {
            setEditing("new");
          }}
        >
          {t("tasks.reward.add.action")}
        </Button>
      </div>
      <RewardPanel
        reward={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => {
          setEditing(null);
        }}
      />
    </Group>
  );
}

function RoutinesGroup() {
  const t = useT();
  const display = useShell() === "display";
  const today = zonedParts(useMinute()).day;
  const { data } = useRoutines(today);
  const { data: members = [] } = useMembers();
  const [editing, setEditing] = useState<Routine | "new" | null>(null);
  const routines = data?.routines ?? [];
  return (
    <Group title={t("tasks.settings.routines.title")}>
      {routines.length === 0 ? (
        <div className={display ? "py-4" : "py-3"}>
          <Text soft>{t("tasks.settings.routines.hint")}</Text>
        </div>
      ) : null}
      {routines.map((routine) => {
        const kid = personOf(members, routine.member_id);
        return (
          <ListRow
            key={routine.id}
            label={t("tasks.edit.aria", { name: routine.title })}
            title={routine.title}
            subtitle={`${kid ? kid.name : t("tasks.routine.every_child")} · ${clockText(routine.window_start)} · ${t("tasks.routine.step_count", { n: routine.steps.length })}`}
            onClick={() => {
              setEditing(routine);
            }}
          />
        );
      })}
      <div className={display ? "py-4" : "py-3"}>
        <Button
          variant="secondary"
          onClick={() => {
            setEditing("new");
          }}
        >
          {t("tasks.routine.add.action")}
        </Button>
      </div>
      <SidePanel
        open={editing !== null}
        title={
          editing && editing !== "new"
            ? t("tasks.edit.title", { name: editing.title })
            : t("tasks.routine.add.title")
        }
        onClose={() => {
          setEditing(null);
        }}
      >
        {editing !== null ? (
          <RoutineForm
            key={editing === "new" ? "new" : editing.id}
            routine={editing === "new" ? null : editing}
            onClose={() => {
              setEditing(null);
            }}
          />
        ) : null}
      </SidePanel>
    </Group>
  );
}

const minutesOf = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const hhmmOf = (minutes: number) => {
  const wrapped = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(wrapped / 60)).padStart(2, "0")}:${String(wrapped % 60).padStart(2, "0")}`;
};

/** A routine's fields and its steps, each with a picture from the step library. */
function RoutineForm({ routine, onClose }: { routine: Routine | null; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const weekStartsOn = useSettings().data?.week_starts_on ?? 6;
  const { stars: starsOn } = useChoreSettings();
  const { saveRoutine, removeRoutine } = useChoreChanges();
  const [title, setTitle] = useState(routine?.title ?? t("tasks.routine.default_name"));
  const [kid, setKid] = useState<string | null>(routine?.member_id ?? null);
  const [days, setDays] = useState<number[]>(routine?.days ?? [0, 1, 2, 3, 4, 5, 6]);
  const [start, setStart] = useState(routine?.window_start ?? "19:30");
  const initialLast = routine
    ? (minutesOf(routine.window_end) - minutesOf(routine.window_start) + 1440) % 1440
    : 60;
  const [last, setLast] = useState(initialLast || 60);
  const [points, setPoints] = useState(routine?.points ?? 0);
  const [steps, setSteps] = useState<StepIn[]>(
    routine?.steps.map((step) => ({ id: step.id, title: step.title, icon: step.icon ?? null })) ??
      [],
  );
  const [choosingIcon, setChoosingIcon] = useState<number | null>(null);
  const gap = display ? "gap-6" : "gap-5";
  const heading = useFieldLabel();
  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [step] = next.splice(from, 1);
    if (step) next.splice(to, 0, step);
    setSteps(next);
  };
  const ready =
    title.trim() !== "" &&
    days.length > 0 &&
    steps.length > 0 &&
    steps.every((s) => s.title.trim());
  return (
    <form
      className={`flex flex-col ${gap}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        saveRoutine.mutate(
          {
            routine,
            fields: {
              title: title.trim(),
              member_id: kid,
              days,
              window_start: start,
              window_end: hhmmOf(minutesOf(start) + last),
              icon: null,
              points: starsOn ? points : (routine?.points ?? 0),
            },
            steps: steps.map((step) => ({ ...step, title: step.title.trim() })),
          },
          { onSuccess: onClose },
        );
      }}
    >
      <TextField
        label={t("tasks.routine.name.label")}
        autoComplete="off"
        value={title}
        onChange={(event) => {
          setTitle(event.target.value);
        }}
      />
      <div className="flex flex-col gap-2">
        <p className={heading}>{t("tasks.routine.whose.label")}</p>
        <ChipRow label={t("tasks.routine.whose.label")}>
          <Chip
            on={kid === null}
            onClick={() => {
              setKid(null);
            }}
          >
            {t("tasks.routine.every_child")}
          </Chip>
        </ChipRow>
        <WhoPicker
          label={t("tasks.routine.which.label")}
          members={members}
          kidsOnly
          everyone={false}
          value={kid ? [kid] : []}
          onChange={(ids) => {
            setKid(ids[0] ?? null);
          }}
        />
      </div>
      <div className="flex flex-col gap-2">
        <p className={heading}>{t("tasks.routine.days.label")}</p>
        <WeekdayPicker
          label={t("tasks.routine.days.label")}
          weekStartsOn={weekStartsOn}
          value={days}
          onChange={setDays}
          minOne={false}
        />
      </div>
      {/* The same time and length pickers as Add's (ADR 0030): any start, not seven fixed ones. */}
      <TimeField
        label={t("tasks.routine.starts.label")}
        value={start}
        none={null}
        onChange={(time) => {
          if (time) setStart(time);
        }}
      />
      <LengthField label={t("tasks.routine.length.label")} value={last} onChange={setLast} />
      {starsOn ? (
        <div className="flex flex-col gap-2">
          <p className={heading}>{t("tasks.routine.stars.label")}</p>
          <ChipRow label={t("tasks.routine.stars.label")}>
            {[0, 1, 2, 3, 5].map((count) => (
              <Chip
                key={count}
                on={points === count}
                onClick={() => {
                  setPoints(count);
                }}
              >
                {count === 0 ? t("tasks.stars.none") : `★${String(count)}`}
              </Chip>
            ))}
          </ChipRow>
        </div>
      ) : null}
      <div className="flex flex-col gap-3">
        <p className={heading}>{t("tasks.routine.steps.label")}</p>
        <ol className="flex flex-col gap-3">
          {steps.map((step, index) => {
            const Icon = stepIcon(step.icon);
            return (
              <li
                key={step.id ?? `new-${String(index)}`}
                className="flex flex-col gap-2 rounded-button border-2 border-line p-3"
              >
                <div className="flex items-end gap-2">
                  <Button
                    variant="secondary"
                    icon
                    aria-label={t("tasks.routine.step.picture.aria", { n: index + 1 })}
                    onClick={() => {
                      setChoosingIcon(choosingIcon === index ? null : index);
                    }}
                  >
                    <Icon aria-hidden="true" className={display ? "size-8" : "size-6"} />
                  </Button>
                  <div className="min-w-0 flex-1">
                    <TextField
                      label={t("tasks.routine.step.label", { n: index + 1 })}
                      hideLabel
                      autoComplete="off"
                      value={step.title}
                      onChange={(event) => {
                        const next = [...steps];
                        next[index] = { ...step, title: event.target.value };
                        setSteps(next);
                      }}
                    />
                  </div>
                  <Button
                    variant="secondary"
                    icon
                    aria-label={t("tasks.routine.step.up.aria", { n: index + 1 })}
                    disabled={index === 0}
                    onClick={() => {
                      move(index, index - 1);
                    }}
                  >
                    <ArrowUp aria-hidden="true" />
                  </Button>
                  <Button
                    variant="secondary"
                    icon
                    aria-label={t("tasks.routine.step.down.aria", { n: index + 1 })}
                    disabled={index === steps.length - 1}
                    onClick={() => {
                      move(index, index + 1);
                    }}
                  >
                    <ArrowDown aria-hidden="true" />
                  </Button>
                  <Button
                    variant="secondary"
                    icon
                    aria-label={t("tasks.routine.step.remove.aria", { n: index + 1 })}
                    onClick={() => {
                      setSteps(steps.filter((_, at) => at !== index));
                    }}
                  >
                    <X aria-hidden="true" />
                  </Button>
                </div>
                {choosingIcon === index ? (
                  <ChipRow label={t("tasks.routine.pictures.label")}>
                    {Object.entries(STEP_ICONS).map(([key, { label, Icon: Option }]) => (
                      <Chip
                        key={key}
                        on={step.icon === key}
                        onClick={() => {
                          const next = [...steps];
                          next[index] = { ...step, icon: key };
                          setSteps(next);
                          setChoosingIcon(null);
                        }}
                      >
                        <Option aria-hidden="true" className={display ? "size-7" : "size-5"} />
                        {t(label)}
                      </Chip>
                    ))}
                  </ChipRow>
                ) : null}
              </li>
            );
          })}
        </ol>
        <p className={display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"}>
          {t("tasks.routine.add_step.label")}
        </p>
        <ChipRow label={t("tasks.routine.add_step.label")}>
          {SUGGESTED_STEPS.map((suggestion) => {
            const Icon = stepIcon(suggestion.icon);
            const words = t(suggestion.title);
            return (
              <Chip
                key={suggestion.title}
                onClick={() => {
                  setSteps([...steps, { id: null, title: words, icon: suggestion.icon }]);
                }}
              >
                <Icon aria-hidden="true" className={display ? "size-7" : "size-5"} />
                {words}
              </Chip>
            );
          })}
          <Chip
            onClick={() => {
              setSteps([...steps, { id: null, title: "", icon: "smile" }]);
            }}
          >
            {t("tasks.routine.another_step")}
          </Chip>
        </ChipRow>
      </div>
      {saveRoutine.isError || removeRoutine.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(saveRoutine.error ?? removeRoutine.error)}
        </p>
      ) : null}
      {routine ? (
        <Button
          variant="quiet-danger"
          pending={removeRoutine.isPending}
          onClick={() => {
            removeRoutine.mutate({ routine }, { onSuccess: onClose });
          }}
        >
          {t("tasks.remove.action", { name: routine.title })}
        </Button>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!ready} pending={saveRoutine.isPending}>
          {routine ? t("app.action.save_changes") : t("tasks.routine.add.action")}
        </Button>
      </PanelActions>
    </form>
  );
}

/** The ready-made amounts; Custom… picks any other (ADR 0034). */
const PRESETS = [-5, -1, 1, 5, 10];

/**
 * Give or take stars (a parent): for a reward outside the app, or a chore done twice. One child
 * or several at once, a preset or Custom… (Give or Take, 1 to 100), with a reason; the children
 * stay picked after, the reason clears (ADR 0034).
 */
function AdjustGroup() {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { adjust } = useChoreChanges();
  const [kids, setKids] = useState<string[]>([]);
  const [preset, setPreset] = useState(1);
  const [custom, setCustom] = useState(false);
  const [direction, setDirection] = useState<"give" | "take">("give");
  const [count, setCount] = useState(1);
  const [reason, setReason] = useState("");
  const chosen = kids.flatMap((id) => personOf(members, id) ?? []);
  const points = custom ? customPoints(direction, count) : preset;
  return (
    <Group title={t("tasks.stars.title")}>
      <div className={`flex flex-col ${display ? "gap-5 py-5" : "gap-4 py-4"}`}>
        <WhoPicker
          label={t("tasks.who.label")}
          members={members}
          kidsOnly
          everyone={false}
          multiple
          value={kids}
          onChange={setKids}
        />
        <ChipRow label={t("tasks.adjust.how_many.label")}>
          {PRESETS.map((value) => (
            <Chip
              key={value}
              on={!custom && preset === value}
              onClick={() => {
                setPreset(value);
                setCustom(false);
              }}
            >
              {value > 0 ? `+${String(value)}` : `−${String(-value)}`}
            </Chip>
          ))}
          <Chip
            opener
            expanded={custom}
            onClick={() => {
              if (!custom) {
                // It starts where the chosen amount was: +5 opens on Give, 5.
                setDirection(preset > 0 ? "give" : "take");
                setCount(Math.abs(preset));
              }
              setCustom(!custom);
            }}
          >
            {t("tasks.adjust.custom")}
          </Chip>
        </ChipRow>
        {custom ? (
          <>
            <Field label={t("tasks.adjust.direction.label")}>
              <Segmented
                label={t("tasks.adjust.direction.label")}
                value={direction}
                onChange={setDirection}
                options={[
                  { value: "give", label: t("tasks.adjust.direction.give") },
                  { value: "take", label: t("tasks.adjust.direction.take") },
                ]}
              />
            </Field>
            <Field label={t("tasks.adjust.count.label")}>
              <Stepper
                label={t("tasks.adjust.count.label")}
                value={count}
                min={1}
                max={100}
                words={(n) => t("tasks.stars.count", { n })}
                onChange={setCount}
              />
            </Field>
          </>
        ) : null}
        <TextField
          label={t("tasks.adjust.reason.label")}
          autoComplete="off"
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        {adjust.isError ? (
          <p role="alert" className="font-semibold text-alert">
            {errorMessage(adjust.error)}
          </p>
        ) : null}
        <div>
          <Button
            disabled={chosen.length === 0}
            pending={adjust.isPending}
            onClick={() => {
              if (chosen.length === 0) return;
              adjust.mutate(
                {
                  members: chosen.map((kid) => kid.id),
                  points,
                  reason: reason.trim(),
                  names: chosen.map((kid) => kid.name),
                },
                {
                  onSuccess: () => {
                    setReason("");
                  },
                },
              );
            }}
          >
            {points > 0 ? t("tasks.adjust.give.action") : t("tasks.adjust.take.action")}
          </Button>
        </div>
      </div>
    </Group>
  );
}
