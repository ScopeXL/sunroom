import { ChevronDown, ChevronRight, ChevronUp } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import { addDays, shortWeekday, zonedParts } from "../../lib/dates";
import { useMembers, useSettings, type Member } from "../../lib/household";
import { whenIdle } from "../../lib/idle";
import { t, useT } from "../../lib/lang";
import { createStore, useStore } from "../../lib/store";
import { showToast } from "../../lib/toast";
import { useMinute } from "../../lib/time";
import { GLIDE } from "../../lib/motion";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Chip } from "../../ui/Chip";
import { DayField } from "../../ui/DayField";
import { Field } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { SwipeRow } from "../../ui/SwipeRow";
import { TextField } from "../../ui/TextField";
import { TickBox } from "../../ui/TickBox";
import { WhoPicker } from "../../ui/WhoPicker";
import { useListChanges, type Item, type ListDetail } from "./data";
import { splitItems } from "./words";

const STRIKE_MS = 600;
const RESET_MS = 2 * 60_000;

/**
 * Who is adding and checking on the wall screen (UX §4 "List detail"): nobody (Everyone) until
 * someone taps the avatar in the add row; it goes back to Everyone after 2 minutes idle. Phones
 * act as their own person, so they never set it.
 */
const wallActor = createStore<string | null>(null);

export function useWallActor(): [string | null, (id: string | null) => void] {
  const display = useShell() === "display";
  const actor = useStore(wallActor);
  useEffect(() => {
    if (!display) return;
    return whenIdle(RESET_MS, () => {
      wallActor.set(null);
    });
  }, [display]);
  return [display ? actor : null, wallActor.set];
}

function nameOf(members: Member[], id: string | null | undefined): Member | undefined {
  return id ? members.find((member) => member.id === id) : undefined;
}

/** What a row says on its right: who has it and when, who added it, or who checked it off. */
export function itemMeta(item: Item, members: Member[], today: string): string {
  if (item.checked_at) {
    const by = nameOf(members, item.checked_by_member_id);
    return by ? t("lists.item.checked_by", { name: by.name }) : t("lists.item.checked");
  }
  const parts: string[] = [];
  const who = nameOf(members, item.assigned_member_id);
  if (who) parts.push(who.name);
  if (item.due_date) {
    parts.push(
      item.due_date === today
        ? t("lists.item.today")
        : item.due_date === addDays(today, 1)
          ? t("lists.item.tomorrow")
          : item.due_date < today
            ? t("lists.item.since", { day: shortWeekday(item.due_date) })
            : shortWeekday(item.due_date),
    );
  }
  if (parts.length) return parts.join(" · ");
  const by = nameOf(members, item.created_by_member_id);
  return by ? t("lists.item.added_by", { name: by.name }) : "";
}

/**
 * The list itself (UX §4 "List detail", §5 "Lists"): items to get, each a 72 px row with its box
 * at the left; checking one draws the marker line in the checker's color, then after 600 ms the
 * row folds into Done. Done is collapsed under its count; ticking a done box puts it back.
 */
export function ItemRows({ detail }: { detail: ListDetail }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const changes = useListChanges();
  const [actor] = useWallActor();
  const today = zonedParts(useMinute()).day;
  // Just checked: still shown, struck, until they fold into Done.
  const [striking, setStriking] = useState<Record<string, { item: Item; by: string | null }>>({});
  const [showDone, setShowDone] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);

  const actingMember = (): string | null => actor ?? null;
  const check = (item: Item) => {
    const by = actingMember();
    setStriking((now) => ({ ...now, [item.id]: { item, by } }));
    changes.check(item, true, by);
    setTimeout(() => {
      setStriking((now) =>
        Object.fromEntries(Object.entries(now).filter(([id]) => id !== item.id)),
      );
    }, STRIKE_MS);
  };

  const open = [
    ...detail.items.filter((item) => !(item.id in striking)),
    ...Object.values(striking).map(({ item }) => item),
  ].sort((a, b) => a.position - b.position);
  const done = detail.done.filter((item) => !(item.id in striking));
  const shownDone = showDone ? done : done.slice(0, 1);
  // A phone's swipe: the sheet's own Remove, toast and Undo.
  const remove = (item: Item) => {
    changes.removeItem.mutate(
      { item },
      {
        onError: (error) => {
          showToast(errorMessage(error));
        },
      },
    );
  };

  return (
    <>
      <ul aria-label={t("lists.items.aria", { name: detail.list.name })} className="flex flex-col">
        {open.map((item) => {
          const strike = striking[item.id];
          const checker = strike ? nameOf(members, strike.by) : undefined;
          return (
            <ItemRow
              key={item.id}
              item={item}
              checked={strike !== undefined}
              person={strike ? (checker?.color ?? "everyone") : undefined}
              meta={itemMeta(item, members, today)}
              onToggle={() => {
                if (!strike) check(item);
              }}
              onOpen={() => {
                setEditing(item);
              }}
              onRemove={() => {
                remove(item);
              }}
            />
          );
        })}
      </ul>
      {done.length ? (
        <section aria-label={t("lists.done.aria")} className="mt-2">
          <ul className="flex flex-col">
            {shownDone.map((item) => {
              const checker = nameOf(members, item.checked_by_member_id);
              return (
                <ItemRow
                  key={item.id}
                  item={item}
                  checked
                  person={checker?.color ?? "everyone"}
                  meta={itemMeta(item, members, today)}
                  onToggle={() => {
                    changes.check(item, false, actingMember());
                  }}
                  onOpen={() => {
                    setEditing(item);
                  }}
                  onRemove={() => {
                    remove(item);
                  }}
                />
              );
            })}
          </ul>
          {done.length > 1 ? (
            <button
              type="button"
              aria-expanded={showDone}
              onClick={() => {
                setShowDone(!showDone);
              }}
              className={`press-row flex w-full items-center gap-2 rounded-button px-3 font-semibold text-ink-soft ${
                display ? "min-h-16 text-d-secondary" : "min-h-12 text-secondary"
              }`}
            >
              {showDone ? (
                <ChevronUp aria-hidden="true" className={display ? "size-7" : "size-5"} />
              ) : (
                <ChevronDown aria-hidden="true" className={display ? "size-7" : "size-5"} />
              )}
              {showDone ? t("lists.done.show_less") : t("lists.done.more", { n: done.length - 1 })}
            </button>
          ) : null}
        </section>
      ) : null}
      <ItemSheet
        item={editing}
        onClose={() => {
          setEditing(null);
        }}
      />
    </>
  );
}

/**
 * An item's row: its box, then its words as one button that opens the item, ending in a chevron
 * because that's what the row is (ADR 0036). On a phone a swipe to the left shows Remove.
 */
function ItemRow({
  item,
  checked,
  person,
  meta,
  onToggle,
  onOpen,
  onRemove,
}: {
  item: Item;
  checked: boolean;
  /** The checker's color while it's struck or done. */
  person: string | undefined;
  meta: string;
  onToggle: () => void;
  onOpen: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const text = item.quantity ? `${item.text} (${item.quantity})` : item.text;
  return (
    // The row glides to where it belongs next (UX §9 "The done row folds"): into Done once its
    // line is drawn, back up when it's unchecked, and the others close the gap.
    <motion.li
      layout="position"
      layoutId={`item ${item.id}`}
      transition={GLIDE}
      data-person={person ?? "everyone"}
      className="border-b border-line"
    >
      <SwipeRow
        action={t("app.action.remove")}
        label={t("lists.remove.action", { name: item.text })}
        onAction={onRemove}
      >
        <div className={`flex items-stretch gap-2 ${display ? "min-h-[72px]" : "min-h-20"}`}>
          <TickBox
            checked={checked}
            person={person}
            label={meta ? `${text}, ${meta}` : text}
            onToggle={onToggle}
          />
          <button
            type="button"
            onClick={onOpen}
            className={`press-row flex min-w-0 flex-1 items-center gap-3 rounded-button py-2 pr-3 text-left ${
              display ? "text-d-body" : "text-body"
            }`}
          >
            <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4">
              <span
                className={`font-semibold break-words hyphens-auto ${checked ? "strike text-ink-soft" : ""}`}
              >
                {text}
              </span>
              {meta ? (
                <span
                  className={`text-ink-soft ${display ? "text-d-secondary" : "text-secondary"}`}
                >
                  {meta}
                </span>
              ) : null}
            </span>
            <ChevronRight
              aria-hidden="true"
              className={`shrink-0 text-ink-soft ${display ? "size-6" : "size-5"}`}
            />
          </button>
        </div>
      </SwipeRow>
    </motion.li>
  );
}

/**
 * The add row (UX §4): the Usuals as chips, the field, and on the wall screen the avatar of who
 * is adding (Everyone until tapped). Add keeps the field focused for the next one; commas add
 * several at once.
 */
export function AddBar({ detail }: { detail: ListDetail }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const changes = useListChanges();
  const [actor, setActor] = useWallActor();
  const [text, setText] = useState("");
  const [choosing, setChoosing] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const me = nameOf(members, actor) ?? null;
  const add = (texts: string[]) => {
    if (!texts.length) return;
    changes.addItems.mutate({ listId: detail.list.id, texts, member: actor });
  };
  return (
    <div className={`flex flex-col ${display ? "gap-3" : "gap-2"}`}>
      {detail.usuals.length ? (
        <div className="flex items-center gap-3 overflow-x-auto pb-1">
          <span
            className={`shrink-0 font-semibold text-ink-soft ${display ? "text-d-secondary" : "text-secondary"}`}
          >
            {t("lists.usuals.label")}
          </span>
          <div
            role="group"
            aria-label={t("lists.usuals.label")}
            className={`flex ${display ? "gap-3" : "gap-2"}`}
          >
            {detail.usuals.map((usual) => (
              <Chip
                key={usual}
                onClick={() => {
                  add([usual]);
                }}
              >
                {usual}
              </Chip>
            ))}
          </div>
        </div>
      ) : null}
      <form
        className="flex items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          add(splitItems(text));
          setText("");
          field.current?.focus();
        }}
      >
        <div className="min-w-0 flex-1">
          <TextField
            ref={field}
            label={t("lists.add_to.label", { name: detail.list.name })}
            hideLabel
            placeholder={t("lists.add_to.label", { name: detail.list.name })}
            autoComplete="off"
            enterKeyHint="done"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </div>
        {display ? (
          <div className="relative">
            <button
              type="button"
              aria-label={
                me ? t("lists.actor.aria", { name: me.name }) : t("lists.actor.everyone.aria")
              }
              aria-expanded={choosing}
              onClick={() => {
                setChoosing(!choosing);
              }}
              className="press flex size-16 items-center justify-center rounded-full"
            >
              <Avatar member={me} size="lg" />
            </button>
            {choosing ? (
              <div className="absolute right-0 bottom-full z-30 mb-3 w-[36rem] rounded-panel border border-line bg-surface p-5 shadow-[0_8px_32px_rgb(0_0_0/0.18)]">
                <p className="mb-3 text-d-body font-semibold">{t("lists.actor.label")}</p>
                <WhoPicker
                  label={t("lists.actor.label")}
                  members={members}
                  value={actor ? [actor] : []}
                  onChange={(ids) => {
                    setActor(ids[0] ?? null);
                    setChoosing(false);
                  }}
                />
              </div>
            ) : null}
          </div>
        ) : null}
        <Button type="submit" disabled={!text.trim()} pending={changes.addItems.isPending}>
          {t("app.action.add")}
        </Button>
      </form>
    </div>
  );
}

/** Tapping an item's words (UX §4): rename it, give it a person or a day, or remove it. */
function ItemSheet({ item, onClose }: { item: Item | null; onClose: () => void }) {
  return (
    <SidePanel open={item !== null} title={item?.text ?? ""} onClose={onClose}>
      {item ? <ItemEditor key={item.id} item={item} onClose={onClose} /> : null}
    </SidePanel>
  );
}

function ItemEditor({ item, onClose }: { item: Item; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const changes = useListChanges();
  const [actor] = useWallActor();
  const today = zonedParts(useMinute()).day;
  const [text, setText] = useState(item.text);
  const [who, setWho] = useState<string | null>(item.assigned_member_id);
  const [day, setDay] = useState<string | null>(item.due_date);
  const save = () => {
    changes.patchItem.mutate(
      {
        item,
        member: actor,
        change: {
          ...(text.trim() && text.trim() !== item.text ? { text: text.trim() } : {}),
          ...(who ? { assigned_member_id: who } : { clear_assignee: true }),
          ...(day ? { due_date: day } : { clear_due_date: true }),
        },
      },
      { onSuccess: onClose },
    );
  };
  const gap = display ? "gap-6" : "gap-5";
  return (
    <div className={`flex flex-col ${gap}`}>
      <TextField
        label={t("lists.field.what.label")}
        value={text}
        autoComplete="off"
        onChange={(event) => {
          setText(event.target.value);
        }}
      />
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
      {/* The same Day picker as Add's (ADR 0030), not a row of weekday chips of its own. */}
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
      {changes.patchItem.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(changes.patchItem.error)}
        </p>
      ) : null}
      {changes.removeItem.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(changes.removeItem.error)}
        </p>
      ) : null}
      <Button
        variant="quiet-danger"
        pending={changes.removeItem.isPending}
        onClick={() => {
          changes.removeItem.mutate({ item }, { onSuccess: onClose });
        }}
      >
        {t("lists.remove.action", { name: item.text })}
      </Button>
      <PanelActions>
        <Button block pending={changes.patchItem.isPending} onClick={save}>
          {t("app.action.save_changes")}
        </Button>
      </PanelActions>
    </div>
  );
}
