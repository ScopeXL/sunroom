import { useState } from "react";

import { errorMessage } from "../../api/client";
import { shortDate, weekOf, zonedParts } from "../../lib/dates";
import { useMembers, useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { DayField } from "../../ui/DayField";
import { Field, FormSection, useFieldHint } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { ScrollRow } from "../../ui/ScrollRow";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { ChoiceRow, ValueRow } from "../../ui/ValueRow";
import { WhoPicker } from "../../ui/WhoPicker";
import { useBoardDay } from "../calendar/useBoardDay";
import type { AddEditorProps } from "../registry";
import {
  SLOT_WORDS,
  useAddToGroceries,
  useListsOn,
  useMealChanges,
  useSaved,
  useWeek,
  type Entry,
  type Saved,
  type Slot,
} from "./data";

/** Add's Meal (UX §4 "The Add panel for other things"). */
export function AddMeal({ day, initialTitle, onDone }: AddEditorProps) {
  return <MealEditor startDay={day} startText={initialTitle ?? ""} onDone={onDone} />;
}

/**
 * A meal's fields (UX §4 "Meals room", ADR 0030). One box, "What's cooking": what's typed is
 * the meal's name and, at the same time, the search of the saved meals, which sit under the box
 * as one row of chips (most made first, narrowing as you type). Tapping one fills the box and
 * keeps its emoji, recipe and ingredients; so does typing a saved meal's name exactly; changing
 * the words lets go of it. Then who cooks, the day and which meal (when the household plans
 * more than dinner). A saved meal with ingredients offers "Add 4 items to Groceries" while
 * Lists is on. Opened from a day's cell, the day and the meal are already chosen: they show as
 * rows that open their pickers only when tapped.
 */
export function MealEditor({
  entry,
  startDay = null,
  startSlot = null,
  startText = "",
  onDone,
}: {
  entry?: Entry;
  startDay?: string | null;
  startSlot?: Slot | null;
  startText?: string;
  onDone: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const today = zonedParts(useMinute()).day;
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const anchor = entry?.day ?? startDay ?? today;
  const weekStart = weekOf(anchor, settings?.week_starts_on ?? 6)[0] ?? anchor;
  const { data: week } = useWeek(weekStart);
  const slots = week?.slots ?? ["dinner"];
  const changes = useMealChanges();
  const groceries = useAddToGroceries();
  const listsOn = useListsOn();
  const [text, setText] = useState(entry?.text ?? startText);
  const [picked, setPicked] = useState<Saved | null>(null);
  const name = text.trim();
  // Still the one that was tapped: its chips stay as they were. Otherwise what's typed searches.
  const held = picked !== null && picked.text === name ? picked : null;
  const { data: saved = [] } = useSaved(held || entry ? "" : name);
  // The saved meal this is: the one tapped, or one whose name was typed out in full.
  const linked =
    held ??
    (entry ? null : (saved.find((meal) => meal.text.toLowerCase() === name.toLowerCase()) ?? null));
  // One row, the linked meal first so it's in view.
  const chips = linked ? [linked, ...saved.filter((meal) => meal.id !== linked.id)] : saved;
  const [day, setDay] = useState(entry?.day ?? startDay ?? today);
  // A day tapped on the board while Add is open moves a new meal's day.
  useBoardDay(startDay, (tapped) => {
    if (!entry) setDay(tapped);
  });
  const [slot, setSlot] = useState<Slot>(entry?.slot ?? startSlot ?? "dinner");
  const [cook, setCook] = useState<string[]>(entry?.member_id ? [entry.member_id] : []);
  const [shop, setShop] = useState(true);
  const ingredients = linked?.ingredients ?? [];
  const ready = name !== "";
  // Opened from a day's cell: the day and the meal are decided, and take one line each.
  const decided = !entry && startDay !== null && startSlot !== null;
  const [dayOpen, setDayOpen] = useState(false);
  const soft = useFieldHint();

  const pick = (meal: Saved) => {
    setPicked(meal);
    setText(meal.text);
  };

  const save = () => {
    if (!ready) return;
    const picked = linked;
    const sameAsPicked = picked !== null;
    changes.save.mutate(
      {
        body: {
          ...(entry ? { id: entry.id } : {}),
          day,
          slot,
          position: entry?.position ?? 0,
          text: sameAsPicked ? picked.text : name,
          emoji: sameAsPicked ? picked.emoji : (entry?.emoji ?? null),
          recipe_url: sameAsPicked ? picked.recipe_url : (entry?.recipe_url ?? null),
          note: entry?.note ?? null,
          member_id: cook[0] ?? null,
          saved_meal_id: sameAsPicked ? picked.id : null,
        },
        member: cook[0] ?? null,
        before: entry ?? null,
      },
      {
        onSuccess: () => {
          if (sameAsPicked && shop && listsOn && ingredients.length) {
            groceries.mutate({ items: ingredients, member: cook[0] ?? null });
          }
          onDone();
        },
      },
    );
  };

  const verb = entry ? t("app.action.save_changes") : t("meals.editor.add.action", { slot });
  return (
    <form
      className={`flex flex-col ${display ? "gap-8" : "gap-6"}`}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <FormSection title={t("meals.editor.what_who.title")} quiet>
        <div className="flex flex-col gap-3">
          <TextField
            label={entry ? t("meals.editor.what.label") : t("meals.editor.cooking.label")}
            autoComplete="off"
            placeholder={t("meals.editor.what.placeholder")}
            maxLength={120}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
          {entry ? null : chips.length ? (
            <ScrollRow label={t("meals.editor.saved.aria")}>
              {chips.slice(0, 12).map((meal) => (
                <Chip
                  key={meal.id}
                  on={linked?.id === meal.id}
                  onClick={() => {
                    pick(meal);
                  }}
                >
                  {meal.emoji ? `${meal.emoji} ${meal.text}` : meal.text}
                </Chip>
              ))}
            </ScrollRow>
          ) : name ? null : (
            <p className={soft}>{t("meals.editor.saved.empty")}</p>
          )}
        </div>
        <Field label={t("meals.editor.cook.label")}>
          <WhoPicker
            label={t("meals.editor.cook.label")}
            everyoneLabel={t("meals.editor.cook.anyone")}
            members={members}
            value={cook}
            onChange={setCook}
          />
        </Field>
      </FormSection>
      <FormSection title={t("meals.editor.when.title")}>
        {decided ? (
          <ValueRow
            label={t("meals.editor.day.label")}
            value={shortDate(day)}
            expanded={dayOpen}
            onToggle={() => {
              setDayOpen(!dayOpen);
            }}
          >
            <DayField
              inRow
              value={day}
              today={today}
              weekStartsOn={settings?.week_starts_on ?? 6}
              anchor={weekStart}
              onChange={setDay}
            />
          </ValueRow>
        ) : (
          <DayField
            value={day}
            today={today}
            weekStartsOn={settings?.week_starts_on ?? 6}
            anchor={weekStart}
            onChange={setDay}
          />
        )}
        {slots.length <= 1 ? null : decided ? (
          <ChoiceRow
            label={t("meals.editor.slot.label")}
            choices={slots.map((option) => ({ value: option, label: t(SLOT_WORDS[option]) }))}
            value={slot}
            onChange={setSlot}
          />
        ) : (
          <Field label={t("meals.editor.slot.label")}>
            <ChipRow label={t("meals.editor.slot.label")}>
              {slots.map((option) => (
                <Chip
                  key={option}
                  on={slot === option}
                  onClick={() => {
                    setSlot(option);
                  }}
                >
                  {t(SLOT_WORDS[option])}
                </Chip>
              ))}
            </ChipRow>
          </Field>
        )}
      </FormSection>
      {linked && ingredients.length > 0 && listsOn && !entry ? (
        <FormSection title={t("meals.editor.details.title")}>
          <Switch
            label={t("meals.editor.groceries.label", { n: ingredients.length })}
            hint={ingredients.join(", ")}
            checked={shop}
            onChange={setShop}
          />
        </FormSection>
      ) : null}
      {changes.save.error ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(changes.save.error)}
        </p>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!ready} pending={changes.save.isPending}>
          {verb}
        </Button>
      </PanelActions>
    </form>
  );
}
