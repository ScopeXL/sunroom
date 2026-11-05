import { useState } from "react";

import { errorMessage } from "../../api/client";
import { zonedParts } from "../../lib/dates";
import { useMembers, useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { DayField } from "../../ui/DayField";
import { Field, FormSection } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { TimeField } from "../../ui/TimeField";
import { WhoPicker } from "../../ui/WhoPicker";
import { firstDayOf, type KeptRule } from "../calendar/EventEditor";
import { RepeatField } from "../calendar/RepeatField";
import {
  repeatToRRule,
  repeatWords,
  rruleToRepeat,
  type Repeat,
  type RepeatEnd,
} from "../calendar/repeat";
import { useBoardDay } from "../calendar/useBoardDay";
import type { AddEditorProps } from "../registry";
import { useChoreChanges, useChoreSettings, type Chore, type ChoreIn } from "./data";
import { clockText } from "./words";

const STARS = [0, 1, 2, 3, 4, 5];
// A task repeats the simple ways; anything else is Custom.
const PRESETS = ["none", "daily", "weekdays", "weekly", "biweekly", "monthly-date"];
const DAILY: Repeat = { freq: "daily", interval: 1 };

/** Add → Task (UX §4 "The Add panel for other things"). */
export function AddChore({ day, onDone }: AddEditorProps) {
  return <ChoreEditor onDone={onDone} startDay={day} />;
}

/**
 * A task's fields (UX §4, ADR 0029; stored as a chore): what; who does it (anyone, or the people
 * picked, each doing it or taking turns); the day it starts; due by a time or any time; how it
 * repeats, Custom included; and its stars, when stars are on. Each on its own row, the button
 * pinned above the keyboard. Adding never asks for the PIN; changing an existing task does on
 * the wall screen.
 */
export function ChoreEditor({
  chore,
  startDay = null,
  onDone,
}: {
  chore?: Chore;
  startDay?: string | null;
  onDone: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const today = zonedParts(useMinute()).day;
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const weekStartsOn = settings?.week_starts_on ?? 6;
  const { stars: starsOn } = useChoreSettings();
  const changes = useChoreChanges();
  // An existing task's rule as one of the editor's shapes, or kept exactly as it is.
  const parsed = chore?.rrule ? rruleToRepeat(chore.rrule, chore.start_date, weekStartsOn) : null;
  const [title, setTitle] = useState(chore?.title ?? "");
  // No one picked is Anyone: whoever does it gets the credit.
  const [who, setWho] = useState<string[]>(
    chore && chore.assignee_mode !== "any" ? chore.assignee_member_ids : [],
  );
  const [turns, setTurns] = useState(chore?.assignee_mode === "rotate");
  const [day, setDay] = useState(chore?.start_date ?? startDay ?? today);
  const [time, setTime] = useState<string | null>(chore?.due_time ?? null);
  const [repeat, setRepeat] = useState<Repeat | null>(chore ? (parsed?.repeat ?? null) : DAILY);
  const [repeatEnd, setRepeatEnd] = useState<RepeatEnd>(parsed?.end ?? {});
  const [kept, setKept] = useState<KeptRule | null>(
    chore?.rrule && !parsed
      ? { rrule: chore.rrule, text: repeatWords(chore) ?? chore.repeat_text }
      : null,
  );
  // The rule and the day go back to the server only when one of them was changed here.
  const [whenTouched, setWhenTouched] = useState(false);
  const [points, setPoints] = useState(chore?.points ?? 1);
  // A day tapped on the board while Add is open is the day a new task starts.
  useBoardDay(startDay, (tapped) => {
    if (!chore) setDay(tapped);
  });
  const ready = title.trim() !== "";
  const gap = display ? "gap-8" : "gap-6";

  const fields = (): ChoreIn => {
    const first = firstDayOf(repeat, day);
    return {
      title: title.trim(),
      points: starsOn ? points : (chore?.points ?? 0),
      rrule: repeat ? repeatToRRule(repeat, first, repeatEnd, weekStartsOn) : (kept?.rrule ?? null),
      start_date: first,
      due_time: time,
      assignee_mode: who.length === 0 ? "any" : turns && who.length > 1 ? "rotate" : "fixed",
      assignee_member_ids: who,
      rotation_index: chore?.rotation_index ?? 0,
    };
  };

  const save = () => {
    if (!ready) return;
    if (!chore) {
      changes.addChore.mutate({ chore: fields() }, { onSuccess: onDone });
      return;
    }
    const next = fields();
    const ruleChanged = whenTouched && (next.rrule ?? null) !== (chore.rrule ?? null);
    const dayChanged = whenTouched && next.start_date !== chore.start_date;
    changes.changeChore.mutate(
      {
        chore,
        change: {
          title: next.title,
          ...(starsOn ? { points: next.points } : {}),
          ...(next.due_time ? { due_time: next.due_time } : { clear_due_time: true }),
          assignee_mode: next.assignee_mode,
          assignee_member_ids: next.assignee_member_ids ?? [],
          ...(ruleChanged ? (next.rrule ? { rrule: next.rrule } : { clear_rrule: true }) : {}),
          ...(ruleChanged || dayChanged ? { start_date: next.start_date ?? day } : {}),
        },
      },
      { onSuccess: onDone },
    );
  };

  const pending = changes.addChore.isPending || changes.changeChore.isPending;
  const error = changes.addChore.error ?? changes.changeChore.error;
  return (
    <form
      className={`flex flex-col ${gap}`}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <FormSection title={t("tasks.editor.what_who.title")} quiet>
        <TextField
          label={t("tasks.editor.what.label")}
          autoComplete="off"
          autoFocus={!chore}
          placeholder={t("tasks.editor.what.placeholder")}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
        <Field label={t("tasks.who.label")}>
          <WhoPicker
            label={t("tasks.who.label")}
            everyoneLabel={t("tasks.anyone")}
            members={members}
            value={who}
            multiple
            onChange={setWho}
          />
          {who.length > 1 ? (
            <Segmented
              label={t("tasks.editor.share.label")}
              value={turns ? "turns" : "each"}
              options={[
                { value: "each", label: t("tasks.editor.share.each") },
                { value: "turns", label: t("tasks.editor.share.turns") },
              ]}
              onChange={(value) => {
                setTurns(value === "turns");
              }}
            />
          ) : null}
        </Field>
      </FormSection>
      <FormSection title={t("tasks.editor.when.title")}>
        <DayField
          value={day}
          today={today}
          weekStartsOn={weekStartsOn}
          hint={repeat || kept ? t("tasks.editor.day.hint") : undefined}
          onChange={(next) => {
            setDay(next);
            setWhenTouched(true);
          }}
        />
        <TimeField
          label={t("tasks.editor.due.label")}
          value={time}
          none={{ label: t("tasks.editor.due.any") }}
          words={(hhmm) => t("tasks.box.by", { time: clockText(hhmm) })}
          onChange={setTime}
        />
        <RepeatField
          day={day}
          today={today}
          value={repeat}
          repeatEnd={repeatEnd}
          kept={kept}
          weekStartsOn={weekStartsOn}
          presetKeys={PRESETS}
          onChange={(change) => {
            setRepeat(change.repeat);
            setRepeatEnd(change.repeatEnd);
            setKept(change.kept);
            setWhenTouched(true);
          }}
        />
      </FormSection>
      {starsOn ? (
        <FormSection title={t("tasks.editor.details.title")}>
          <Field label={t("tasks.editor.stars.label")}>
            <ChipRow label={t("tasks.editor.stars.label")}>
              {STARS.map((count) => (
                <Chip
                  key={count}
                  on={points === count}
                  label={
                    count === 0 ? t("tasks.stars.none.aria") : t("tasks.stars.count", { n: count })
                  }
                  onClick={() => {
                    setPoints(count);
                  }}
                >
                  {count === 0 ? t("tasks.stars.none") : `★${String(count)}`}
                </Chip>
              ))}
            </ChipRow>
          </Field>
        </FormSection>
      ) : null}
      {error ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(error)}
        </p>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!ready} pending={pending}>
          {chore ? t("app.action.save_changes") : t("tasks.add.action")}
        </Button>
      </PanelActions>
    </form>
  );
}
