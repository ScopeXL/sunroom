import { Link, useNavigate } from "@tanstack/react-router";
import { ListChecks, ListX, Plus } from "lucide-react";
import { useState } from "react";

import { errorMessage } from "../../api/client";
import { zonedParts } from "../../lib/dates";
import { useMembers, type Member } from "../../lib/household";
import { useT, type Key } from "../../lib/lang";
import { useLongPress } from "../../lib/longPress";
import { useMinute } from "../../lib/time";
import { HeaderBack } from "../../shell/HeaderLinks";
import { RoomHeader } from "../../shell/roomHeader";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { EmptyState, QuietLine } from "../../ui/EmptyState";
import { PanelActions } from "../../ui/PanelActions";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { TextField } from "../../ui/TextField";
import { Pop } from "../../ui/Pop";
import { useList, useListChanges, useLists, type ListInfo } from "./data";
import { AddBar, ItemRows } from "./ListItems";
import { countLine, lastChangeLine } from "./words";

/** The usual lists, as chips under a new list's name (and Add → Item's, before there's one). */
export const SUGGESTED: readonly Key[] = [
  "lists.suggested.groceries",
  "lists.suggested.todo",
  "lists.suggested.packing",
  "lists.suggested.costco",
  "lists.suggested.pharmacy",
];

/** The Lists room on the wall screen (UX §4): the lists as tiles, or one list. */
export function ListsRoom({ path }: { path: string[] }) {
  const [listId] = path;
  return listId ? <ListPage listId={listId} /> : <ListTiles />;
}

function ListTiles() {
  const t = useT();
  const { data: lists, isSuccess } = useLists();
  const { data: members = [] } = useMembers();
  const today = zonedParts(useMinute()).day;
  const [making, setMaking] = useState(false);
  // A long press on a tile opens its Change list here (UX §4), kept while it slides away.
  const [held, setHeld] = useState<{ id: string; open: boolean } | null>(null);
  const heldList = lists?.find((list) => list.id === held?.id);
  return (
    <section aria-label={t("lists.room.title")} className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title={t("lists.room.title")}
        controls={
          <Button
            variant="secondary"
            className="ml-auto"
            onClick={() => {
              setMaking(true);
            }}
          >
            <Plus aria-hidden="true" className="size-7" />
            {t("lists.new.action")}
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {isSuccess && lists.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            line={t("lists.none.empty")}
            note={t("lists.none.hint")}
            action={
              <Button
                onClick={() => {
                  setMaking(true);
                }}
              >
                {t("lists.new.action")}
              </Button>
            }
          />
        ) : (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(22rem,1fr))] gap-6">
            {(lists ?? []).map((list) => (
              <li key={list.id}>
                <ListTile
                  list={list}
                  members={members}
                  today={today}
                  onHold={() => {
                    setHeld({ id: list.id, open: true });
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
      <NewListPanel
        open={making}
        onClose={() => {
          setMaking(false);
        }}
      />
      {held && heldList ? (
        <ChangeListPanel
          key={heldList.id}
          list={heldList}
          open={held.open}
          onClose={() => {
            setHeld({ ...held, open: false });
          }}
        />
      ) : null}
    </section>
  );
}

/** A list's tile (UX §4): a tap opens the list; a long press is a shortcut to Change list. */
function ListTile({
  list,
  members,
  today,
  onHold,
}: {
  list: ListInfo;
  members: Member[];
  today: string;
  onHold: () => void;
}) {
  const hold = useLongPress(onHold);
  return (
    <Link
      to="/$room/$"
      params={{ room: "lists", _splat: list.id }}
      {...hold}
      className="press flex min-h-40 flex-col justify-between gap-2 rounded-panel border border-line bg-surface p-6 select-none [-webkit-touch-callout:none]"
    >
      <span className="text-d-title font-bold break-words">{list.name}</span>
      <Pop value={tileCount(list)} className="self-start text-d-body font-semibold" />
      {list.last_change ? (
        <span className="text-d-secondary text-ink-soft">
          {lastChangeLine(list.last_change, (id) => members.find((m) => m.id === id)?.name, today)}
        </span>
      ) : null}
    </Link>
  );
}

export function tileCount(list: ListInfo): string {
  return countLine(list.kind, list.open_count, list.done_count, list.due_count);
}

/** New list (UX §4, ADR 0030): one field for its name, with the usual names as chips under it
 * that fill the field; it opens once made. */
export function NewListPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const { createList } = useListChanges();
  const [name, setName] = useState("");
  const make = (chosen: string) => {
    if (!chosen.trim()) return;
    createList.mutate(
      { name: chosen.trim() },
      {
        onSuccess: (list) => {
          setName("");
          onClose();
          void navigate({ to: "/$room/$", params: { room: "lists", _splat: list.id } });
        },
      },
    );
  };
  return (
    <SidePanel open={open} title={t("lists.new.title")} onClose={onClose}>
      <form
        className={`flex flex-col ${display ? "gap-6" : "gap-5"}`}
        onSubmit={(event) => {
          event.preventDefault();
          make(name);
        }}
      >
        <div className="flex flex-col gap-3">
          <TextField
            label={t("lists.name.label")}
            autoComplete="off"
            data-autofocus=""
            value={name}
            error={createList.isError ? errorMessage(createList.error) : null}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          <ChipRow label={t("lists.usual_lists.aria")}>
            {SUGGESTED.map((key) => {
              const suggestion = t(key);
              return (
                <Chip
                  key={key}
                  on={name.trim() === suggestion}
                  onClick={() => {
                    setName(suggestion);
                  }}
                >
                  {suggestion}
                </Chip>
              );
            })}
          </ChipRow>
        </div>
        <PanelActions>
          <Button type="submit" block disabled={!name.trim()} pending={createList.isPending}>
            {t("lists.new.add.action")}
          </Button>
        </PanelActions>
      </form>
    </SidePanel>
  );
}

function ListPage({ listId }: { listId: string }) {
  const t = useT();
  const { data: detail, isError } = useList(listId);
  const navigate = useNavigate();
  const { clearDone } = useListChanges();
  const [changing, setChanging] = useState(false);
  if (isError) {
    return (
      <section className="p-6">
        <RoomHeader title={t("lists.room.title")} />
        <EmptyState
          icon={ListX}
          line={t("lists.list.gone.empty")}
          action={
            <Button
              onClick={() => {
                void navigate({ to: "/$room", params: { room: "lists" } });
              }}
            >
              {t("lists.back.action")}
            </Button>
          }
        />
      </section>
    );
  }
  if (!detail) return null;
  const { list } = detail;
  return (
    <section aria-label={list.name} className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title={list.name}
        visibleTitle
        back={
          <HeaderBack to="/$room" params={{ room: "lists" }}>
            {t("lists.room.title")}
          </HeaderBack>
        }
        controls={
          <div className="ml-auto flex gap-3">
            {list.done_count > 0 ? (
              <Button
                variant="secondary"
                pending={clearDone.isPending}
                onClick={() => {
                  clearDone.mutate({ listId: list.id });
                }}
              >
                {t("lists.list.clear_done.action")}
              </Button>
            ) : null}
            <Button
              variant="secondary"
              onClick={() => {
                setChanging(true);
              }}
            >
              {t("lists.list.change.action")}
            </Button>
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-2">
        {/* How much is left, over the items: the header has the list's name and nothing under it. */}
        <p className="pt-3 pb-1 text-d-secondary font-semibold text-ink-soft">
          <Pop value={tileCount(list)} className="inline-block" />
        </p>
        {detail.items.length === 0 && detail.done.length === 0 ? (
          <QuietLine>{t("lists.list.empty", { name: list.name })}</QuietLine>
        ) : (
          <ItemRows detail={detail} />
        )}
      </div>
      <footer className="border-t border-line bg-surface px-6 py-4">
        <AddBar detail={detail} />
      </footer>
      <ChangeListPanel
        list={list}
        open={changing}
        onClose={() => {
          setChanging(false);
        }}
      />
    </section>
  );
}

/**
 * Rename a list, or remove it (asked first while it still has things on it, UX §1). `asking`
 * opens it on that question: a phone's swipe on the list of lists (ADR 0036).
 */
export function ChangeListPanel({
  list,
  open,
  asking: askFirst = false,
  onClose,
}: {
  list: ListInfo;
  open: boolean;
  asking?: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const { renameList, removeList } = useListChanges();
  const [name, setName] = useState(list.name);
  const [asking, setAsking] = useState(open && askFirst);
  // Each opening starts where it was asked to: reset during render (docs/GOTCHAS.md).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setAsking(askFirst);
  }
  const holds = list.open_count + list.done_count;
  const remove = () => {
    removeList.mutate(
      { list },
      {
        onSuccess: () => {
          onClose();
          void navigate({ to: "/$room", params: { room: "lists" } });
        },
      },
    );
  };
  return (
    <SidePanel
      open={open}
      title={t("lists.list.change.title", { name: list.name })}
      onClose={() => {
        setAsking(false);
        onClose();
      }}
    >
      {/* One form: Remove in its flow, Save changes pinned under it like every other editor. */}
      <form
        className={`flex flex-col ${display ? "gap-6" : "gap-5"}`}
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim()) return;
          renameList.mutate({ list, name: name.trim() }, { onSuccess: onClose });
        }}
      >
        <TextField
          label={t("lists.name.label")}
          autoComplete="off"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        {removeList.isError ? (
          <p role="alert" className="font-semibold text-alert">
            {errorMessage(removeList.error)}
          </p>
        ) : null}
        {asking ? (
          <div className="flex flex-col gap-3 rounded-button border-2 border-line p-4">
            <p className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
              {t("lists.list.holds", { name: list.name, n: holds })}
            </p>
            <div className="flex flex-wrap gap-3">
              <Button variant="danger" pending={removeList.isPending} onClick={remove}>
                {t("lists.remove.action", { name: list.name })}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setAsking(false);
                }}
              >
                {t("lists.list.keep.action", { name: list.name })}
              </Button>
            </div>
          </div>
        ) : (
          <Button
            block
            variant="quiet-danger"
            onClick={() => {
              if (holds > 0) setAsking(true);
              else remove();
            }}
          >
            {t("lists.remove.action", { name: list.name })}
          </Button>
        )}
        <PanelActions>
          <Button type="submit" block disabled={!name.trim()} pending={renameList.isPending}>
            {t("app.action.save_changes")}
          </Button>
        </PanelActions>
      </form>
    </SidePanel>
  );
}
