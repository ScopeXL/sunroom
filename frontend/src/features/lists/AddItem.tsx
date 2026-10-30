import { useRouterState } from "@tanstack/react-router";
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
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { WhoPicker } from "../../ui/WhoPicker";
import { useBoardDay } from "../calendar/useBoardDay";
import type { AddEditorProps } from "../registry";
import { useListChanges, useLists } from "./data";
import { useWallActor } from "./ListItems";
import { SUGGESTED } from "./ListsRoom";
import { splitItems } from "./words";

/**
 * Add → Item (UX §4 "The Add panel for other things", ADR 0029): what (commas make several:
 * "Milk, eggs, bread"), which list (the open one first), and, if it matters, who and which day:
 * each on its own row, with the button pinned above the keyboard. A day tapped on the board
 * while the panel is open sets the day.
 */
export function AddItem({ day: boardDay, onDone }: AddEditorProps) {
  const t = useT();
  const display = useShell() === "display";
  const { data: lists = [] } = useLists();
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const { addItems, createList } = useListChanges();
  const [actor] = useWallActor();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const today = zonedParts(useMinute()).day;
  const openList = /^\/lists\/([^/]+)/.exec(pathname)?.[1];
  const [listId, setListId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [who, setWho] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(boardDay);
  useBoardDay(boardDay, setDay);
  const chosen =
    lists.find((list) => list.id === listId) ??
    lists.find((list) => list.id === openList) ??
    lists.find((list) => list.kind === "grocery") ??
    lists[0];
  const texts = splitItems(text);
  const gap = display ? "gap-8" : "gap-6";
  const heading = display ? "text-d-body font-semibold" : "text-body font-semibold";

  if (!chosen) {
    return (
      <div className={`flex flex-col ${gap}`}>
        <p className={heading}>{t("lists.add.first")}</p>
        <ChipRow label={t("lists.usual_lists.aria")}>
          {SUGGESTED.map((suggestion) => {
            const name = t(suggestion);
            return (
              <Chip
                key={suggestion}
                onClick={() => {
                  createList.mutate({ name });
                }}
              >
                {name}
              </Chip>
            );
          })}
        </ChipRow>
      </div>
    );
  }
  return (
    <form
      className={`flex flex-col ${gap}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!texts.length) return;
        addItems.mutate(
          { listId: chosen.id, texts, member: actor, dueDate: day, assignee: who },
          { onSuccess: onDone },
        );
      }}
    >
      <FormSection title={t("lists.add.what_who.title")} quiet>
        <TextField
          label={t("lists.field.what.label")}
          hint={t("lists.add.what.hint")}
          autoComplete="off"
          autoFocus
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <Field label={t("lists.field.which.label")}>
          <ChipRow label={t("lists.field.which.label")}>
            {lists.map((list) => (
              <Chip
                key={list.id}
                on={list.id === chosen.id}
                onClick={() => {
                  setListId(list.id);
                }}
              >
                {list.name}
              </Chip>
            ))}
          </ChipRow>
        </Field>
        <Field label={t("lists.field.who.label")}>
          <WhoPicker
            label={t("lists.field.who.label")}
            members={members}
            value={who ? [who] : []}
            onChange={(ids) => {
              setWho(ids[0] ?? null);
            }}
          />
        </Field>
      </FormSection>
      <FormSection title={t("lists.add.when.title")}>
        <DayField
          value={day}
          today={today}
          weekStartsOn={settings?.week_starts_on ?? 6}
          onChange={setDay}
          optional={{
            label: t("lists.field.no_day.label"),
            onChoose: () => {
              setDay(null);
            },
          }}
        />
      </FormSection>
      {addItems.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(addItems.error)}
        </p>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!texts.length} pending={addItems.isPending}>
          {t("lists.add.action", { n: Math.max(texts.length, 1) })}
        </Button>
      </PanelActions>
    </form>
  );
}
