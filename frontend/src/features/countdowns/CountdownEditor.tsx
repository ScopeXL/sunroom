import { useState } from "react";

import { errorMessage } from "../../api/client";
import { addDays, zonedParts } from "../../lib/dates";
import { useMembers, useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { Chip } from "../../ui/Chip";
import { ColorDots } from "../../ui/ColorDots";
import { DayField } from "../../ui/DayField";
import { Field, FormSection } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { ScrollRow } from "../../ui/ScrollRow";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { WhoPicker } from "../../ui/WhoPicker";
import { useBoardDay } from "../calendar/useBoardDay";
import type { AddEditorProps } from "../registry";
import { useCountdownChanges, type Countdown, type CountdownIn } from "./data";

const EMOJI = ["🎂", "🎉", "🏖️", "⛺", "✈️", "🎃", "🎄", "🏫", "⚽", "🎁"];

/** Add's Countdown (UX §4 "The Add panel for other things"). */
export function AddCountdown({ day, initialTitle, onDone }: AddEditorProps) {
  return <CountdownEditor onDone={onDone} startDay={day} startTitle={initialTitle ?? ""} />;
}

/**
 * A countdown's fields (UX §4): what it counts down to, the day, whose it is (or everyone's),
 * an emoji and a color if wanted, every year, and whether the wall screen shows it (off for
 * a surprise). Nothing asks for the PIN: countdowns are the family's.
 */
export function CountdownEditor({
  countdown,
  startDay = null,
  startTitle = "",
  onDone,
}: {
  countdown?: Countdown;
  startDay?: string | null;
  startTitle?: string;
  onDone: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const today = zonedParts(useMinute()).day;
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const changes = useCountdownChanges();
  const [title, setTitle] = useState(countdown?.title ?? startTitle);
  const [day, setDay] = useState(
    countdown?.date ?? (startDay && startDay >= today ? startDay : addDays(today, 7)),
  );
  // A day tapped on the board while Add is open moves a new countdown's day (never to the past).
  useBoardDay(startDay, (tapped) => {
    if (!countdown && tapped >= today) setDay(tapped);
  });
  const [who, setWho] = useState<string[]>(countdown?.member_id ? [countdown.member_id] : []);
  const [emoji, setEmoji] = useState<string | null>(countdown?.emoji ?? null);
  const [color, setColor] = useState<NonNullable<CountdownIn["color"]> | null>(
    countdown?.color ?? null,
  );
  const [yearly, setYearly] = useState(countdown?.repeat_yearly ?? false);
  const [onWall, setOnWall] = useState(countdown?.show_on_display ?? true);
  const ready = title.trim() !== "" && (yearly || day >= today || countdown !== undefined);

  const save = () => {
    if (!ready) return;
    const fields: CountdownIn = {
      title: title.trim(),
      date: day,
      emoji,
      color,
      time: countdown?.time ?? null,
      repeat_yearly: yearly,
      member_id: who[0] ?? null,
      show_on_display: onWall,
    };
    if (!countdown) {
      changes.add.mutate({ body: fields, member: who[0] ?? null }, { onSuccess: onDone });
      return;
    }
    changes.update.mutate(
      {
        id: countdown.id,
        patch: {
          title: fields.title,
          date: day,
          emoji: emoji ?? "",
          ...(color ? { color } : { clear_color: true }),
          repeat_yearly: yearly,
          ...(who[0] ? { member_id: who[0] } : { clear_member: true }),
          show_on_display: onWall,
        },
      },
      { onSuccess: onDone },
    );
  };

  const pending = changes.add.isPending || changes.update.isPending;
  const error = changes.add.error ?? changes.update.error;
  return (
    <form
      className={`flex flex-col ${display ? "gap-8" : "gap-6"}`}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <FormSection title={t("countdowns.editor.what_who.title")} quiet>
        <TextField
          label={t("countdowns.editor.what.label")}
          autoComplete="off"
          autoFocus={!countdown && !startTitle}
          placeholder={t("countdowns.editor.what.placeholder")}
          maxLength={80}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
        <Field label={t("countdowns.editor.whose.label")}>
          <WhoPicker
            label={t("countdowns.editor.whose.label")}
            members={members}
            value={who}
            onChange={setWho}
          />
        </Field>
      </FormSection>
      <FormSection title={t("countdowns.editor.when.title")}>
        {/* The month is open from the start: what's counted down to is rarely this week. */}
        <DayField
          value={day}
          today={today}
          weekStartsOn={settings?.week_starts_on ?? 6}
          grid="open"
          min={yearly ? undefined : today}
          onChange={setDay}
        />
      </FormSection>
      <FormSection title={t("countdowns.editor.details.title")}>
        <Field label={t("countdowns.editor.emoji.label")}>
          <ScrollRow label={t("countdowns.editor.emoji.label")}>
            <Chip
              on={emoji === null}
              onClick={() => {
                setEmoji(null);
              }}
            >
              {t("countdowns.editor.emoji.none")}
            </Chip>
            {EMOJI.map((mark) => (
              <Chip
                key={mark}
                on={emoji === mark}
                onClick={() => {
                  setEmoji(mark);
                }}
              >
                {mark}
              </Chip>
            ))}
          </ScrollRow>
        </Field>
        <Field label={t("ui.color.label")}>
          <ColorDots
            value={color}
            noneLabel={
              who.length ? t("countdowns.editor.color.theirs") : t("countdowns.editor.color.none")
            }
            onChange={setColor}
          />
        </Field>
        <div className="flex flex-col divide-y divide-line">
          <Switch label={t("countdowns.every_year")} checked={yearly} onChange={setYearly} />
          <Switch
            label={t("countdowns.editor.on_wall.label")}
            hint={t("countdowns.editor.on_wall.hint")}
            checked={onWall}
            onChange={setOnWall}
          />
        </div>
      </FormSection>
      {error ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(error)}
        </p>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!ready} pending={pending}>
          {countdown ? t("app.action.save_changes") : t("countdowns.add.action")}
        </Button>
      </PanelActions>
    </form>
  );
}
