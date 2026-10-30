import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

import { errorMessage } from "../../api/client";
import { zonedParts } from "../../lib/dates";
import { useMembers, type Member } from "../../lib/household";
import { t, useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { useShell } from "../../ui/shell";
import { SwipeRow } from "../../ui/SwipeRow";
import { ChoreSheet, personOf, useViewer } from "./ChoreBoard";
import { useChoreChanges, useChores, type Chore } from "./data";
import { ruleLine } from "./words";

const MOST_COLUMNS = 5;

export interface TaskColumn {
  /** null: Anyone's. */
  memberId: string | null;
  tasks: Chore[];
}

/**
 * Which column each task is in (All Tasks, ADR 0036): a fixed task under each of its people, a
 * turn-taking one under each person in its turns, an anyone task under Anyone; the columns in
 * household order, then Anyone, and the tasks as the list has them (soonest first). Someone who
 * has left the household has no column.
 */
export function taskColumns(chores: readonly Chore[], members: readonly Member[]): TaskColumn[] {
  const named = new Map<string | null, Chore[]>();
  for (const chore of chores) {
    const ids = chore.assignee_mode === "any" ? [null] : chore.assignee_member_ids;
    for (const id of ids) named.set(id, [...(named.get(id) ?? []), chore]);
  }
  const columns: TaskColumn[] = members.flatMap((member) => {
    const tasks = named.get(member.id);
    return tasks ? [{ memberId: member.id, tasks }] : [];
  });
  const anyone = named.get(null);
  return anyone ? [...columns, { memberId: null, tasks: anyone }] : columns;
}

/** "1 task", "5 tasks". */
export function tasksCount(count: number): string {
  return t("tasks.how_many", { n: count });
}

/**
 * All Tasks on the wall (UX §4, ADR 0036): a column per person any task names, then Anyone,
 * each headed by the person and how many tasks, then every task soonest first, a row each.
 * No boxes: a box completes, and that belongs to Today.
 */
export function AllTasksColumns({ starsOn }: { starsOn: boolean }) {
  const t = useT();
  const { data: chores } = useChores();
  const { data: members = [] } = useMembers();
  if (!chores) return null;
  const columns = taskColumns(chores, members);
  const width = `${String(100 / Math.min(Math.max(columns.length, 1), MOST_COLUMNS))}%`;
  return (
    <div tabIndex={0} className="flex min-h-0 flex-1 snap-x overflow-x-auto">
      {columns.map(({ memberId, tasks }) => {
        const person = personOf(members, memberId);
        return (
          <section
            key={memberId ?? "anyone"}
            aria-label={person ? person.name : t("tasks.anyone")}
            data-person={person?.color ?? "everyone"}
            className="min-h-0 min-w-[16rem] shrink-0 snap-start overflow-y-auto border-r border-line px-4 py-4"
            style={{ width }}
          >
            <header className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-3">
              <Avatar member={person ?? null} size="lg" />
              <h2 className="text-d-title font-bold">{person ? person.name : t("tasks.anyone")}</h2>
              <span className="text-d-body font-semibold text-ink-soft">
                {tasksCount(tasks.length)}
              </span>
            </header>
            <ul className="flex flex-col">
              {tasks.map((chore) => (
                <TaskRuleRow key={chore.id} chore={chore} starsOn={starsOn} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/**
 * One task in All Tasks: its title over its rule line ("Every week on Sat · Sat, Nov 14 · by
 * 5:00 PM · ★2"), and a chevron, since a tap opens it (`ChoreSheet`). On a phone that may remove
 * tasks, a swipe to the left shows Remove.
 */
export function TaskRuleRow({ chore, starsOn }: { chore: Chore; starsOn: boolean }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const today = zonedParts(useMinute()).day;
  const viewer = useViewer();
  const changes = useChoreChanges();
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-line">
      <SwipeRow
        action={t("app.action.remove")}
        label={t("tasks.remove.action", { name: chore.title })}
        disabled={!viewer.answers}
        onAction={() => {
          changes.removeChore.mutate(
            { chore },
            {
              onError: (error) => {
                showToast(errorMessage(error));
              },
            },
          );
        }}
      >
        <button
          type="button"
          onClick={() => {
            setOpen(true);
          }}
          className={`press-row flex w-full items-center gap-3 rounded-button px-2 py-2 text-left ${
            display ? "min-h-[72px]" : "min-h-16"
          }`}
        >
          <span className="flex min-w-0 flex-1 flex-col justify-center">
            <span
              className={`font-semibold break-words hyphens-auto ${display ? "text-d-body" : "text-body"}`}
            >
              {chore.title}
            </span>
            <span className="sr-only">, </span>
            <span className={`text-ink-soft ${display ? "text-d-secondary" : "text-secondary"}`}>
              {ruleLine(chore, members, starsOn, today)}
            </span>
          </span>
          <ChevronRight
            aria-hidden="true"
            className={`shrink-0 text-ink-soft ${display ? "size-6" : "size-5"}`}
          />
        </button>
      </SwipeRow>
      {/* Outside the row, as a box's sheet is (ChoreRow). */}
      {createPortal(
        <ChoreSheet
          open={open}
          task={{ chore_id: chore.id, title: chore.title }}
          starsOn={starsOn}
          onClose={() => {
            setOpen(false);
          }}
        />,
        document.body,
      )}
    </li>
  );
}
