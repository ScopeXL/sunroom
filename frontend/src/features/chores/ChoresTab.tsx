import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, ListTodo, Plus } from "lucide-react";
import { useState, type ReactNode } from "react";

import { weekOf, zonedParts } from "../../lib/dates";
import type { BoardPanel } from "../../lib/displayState";
import { useMembers, useSettings } from "../../lib/household";
import { useT } from "../../lib/lang";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Screen } from "../../ui/Screen";
import { Segmented } from "../../ui/Segmented";
import { AddPanel } from "../calendar/AddPanel";
import { taskColumns, TaskRuleRow, tasksCount } from "./AllTasks";
import { ChoreColumn, personOf, useViewer, WaitingStrip } from "./ChoreBoard";
import { useChores, useChoresDay, useChoresWeek, useRewards, type Column, type Day } from "./data";
import { AskedStrip, RewardsPage } from "./RewardsPage";
import { RoutineRunner } from "./RoutineRunner";
import { WeekRows } from "./ChoresRoom";
import { countText } from "./words";

/** Chores on a phone (UX §5): Today, This Week or All Tasks (ADR 0036), Stars & rewards, and
 * the routine runner. */
export function ChoresTab({ path }: { path: string[] }) {
  const [page, ...rest] = path;
  if (page === "rewards") return <RewardsPage />;
  if (page === "run") {
    const [routineId, memberId, day] = rest;
    if (routineId && memberId && day) {
      return <RoutineRunner routineId={routineId} memberId={memberId} day={day} />;
    }
  }
  return <PhoneChores />;
}

function PhoneChores() {
  const t = useT();
  const today = zonedParts(useMinute()).day;
  const { data: day, isSuccess } = useChoresDay(today);
  const viewer = useViewer();
  const { data: rewards } = useRewards({ enabled: viewer.answers });
  const [mode, setMode] = useState<"today" | "week" | "all">("today");
  const [panel, setPanel] = useState<BoardPanel>(null);
  const mine = day?.stars.find((s) => s.member_id === viewer.memberId);
  const { data: members = [] } = useMembers();
  const me = personOf(members, viewer.memberId);
  return (
    <Screen
      title={t("tasks.room.title")}
      actions={
        <Button
          block
          onClick={() => {
            setPanel({ kind: "add", day: null, hour: null, type: "chore" });
          }}
        >
          <Plus aria-hidden="true" className="size-5" />
          {t("app.action.add")}
        </Button>
      }
    >
      <div className="-mt-3 mb-4 flex flex-col gap-3">
        {me && mine && day?.stars_on ? (
          <p className="text-body font-bold">{`★ ${String(mine.balance)} ${me.name}`}</p>
        ) : null}
        <Segmented
          label={t("tasks.show.label")}
          value={mode}
          options={[
            { value: "today", label: t("tasks.show.today") },
            { value: "week", label: t("tasks.show.week") },
            { value: "all", label: t("tasks.show.all") },
          ]}
          onChange={setMode}
        />
      </div>
      <div className="flex flex-col gap-4">
        {rewards?.asked.length && viewer.answers ? <AskedStrip asked={rewards.asked} /> : null}
        {day?.waiting.length ? <WaitingStrip waiting={day.waiting} /> : null}
        {isSuccess && day.columns.length === 0 ? (
          <EmptyState icon={ListTodo} line={t("tasks.none.empty")} note={t("tasks.none.hint")} />
        ) : day && mode === "today" ? (
          <Sections day={day} first={viewer.memberId} />
        ) : day && mode === "all" ? (
          <PhoneAllTasks first={viewer.memberId} starsOn={day.stars_on} />
        ) : day ? (
          <PhoneWeek day={day} today={today} />
        ) : null}
        {day && (day.stars_on || day.rewards_on) ? (
          <Link
            to="/$room/$"
            params={{ room: "chores", _splat: "rewards" }}
            className="press-row flex min-h-14 items-center justify-between rounded-chip border border-line bg-surface px-4 text-row font-semibold"
          >
            {day.rewards_on ? t("tasks.rewards.title") : t("tasks.stars.title")}
            <ChevronRight aria-hidden="true" className="text-ink-soft" />
          </Link>
        ) : null}
      </div>
      <AddPanel
        panel={panel?.kind === "add" ? panel : null}
        today={today}
        room="chores"
        onClose={() => {
          setPanel(null);
        }}
        onType={(type) => {
          setPanel((open) => (open?.kind === "add" ? { ...open, type } : open));
        }}
      />
    </Screen>
  );
}

/** The phone's person first and open; everyone else folded, with how they're doing. */
function Sections({ day, first }: { day: Day; first: string | null }) {
  const ordered = [
    ...day.columns.filter((c) => c.member_id === first && first !== null),
    ...day.columns.filter((c) => c.member_id !== first || first === null),
  ];
  return (
    <div className="flex flex-col gap-3">
      {ordered.map((column, index) => (
        <Section
          key={column.member_id ?? "anyone"}
          column={column}
          day={day}
          open={index === 0 || column.member_id === null}
        />
      ))}
    </div>
  );
}

function Section({
  column,
  day,
  open: initiallyOpen,
}: {
  column: Column;
  day: Day;
  open: boolean;
}) {
  const t = useT();
  const { data: members = [] } = useMembers();
  const person = personOf(members, column.member_id);
  const name = person ? person.name : t("tasks.anyone");
  const allDone = column.total > 0 && column.done === column.total;
  const status = allDone
    ? t("tasks.status.all_done")
    : column.total > 0
      ? countText(column.done, column.total)
      : t("tasks.status.nothing");
  return (
    <Folding title={`${name} · ${status}`} open={initiallyOpen}>
      <ChoreColumn
        column={column}
        day={day}
        starsOn={day.stars_on}
        stars={day.stars.find((s) => s.member_id === column.member_id)?.balance}
        header={false}
      />
    </Folding>
  );
}

/** All Tasks on a phone (ADR 0036): a section per person, the phone's person first and open (and
 * Anyone's), the rest folded with how many tasks; rows a swipe can remove, on a parent's phone. */
function PhoneAllTasks({ first, starsOn }: { first: string | null; starsOn: boolean }) {
  const t = useT();
  const { data: chores } = useChores();
  const { data: members = [] } = useMembers();
  if (!chores) return null;
  const columns = taskColumns(chores, members);
  const ordered = [
    ...columns.filter((c) => c.memberId === first && first !== null),
    ...columns.filter((c) => c.memberId !== first || first === null),
  ];
  return (
    <div className="flex flex-col gap-3">
      {ordered.map(({ memberId, tasks }, index) => (
        <Folding
          key={memberId ?? "anyone"}
          title={`${personOf(members, memberId)?.name ?? t("tasks.anyone")} · ${tasksCount(tasks.length)}`}
          open={index === 0 || memberId === null}
        >
          <ul className="flex flex-col">
            {tasks.map((chore) => (
              <TaskRuleRow key={chore.id} chore={chore} starsOn={starsOn} />
            ))}
          </ul>
        </Folding>
      ))}
    </div>
  );
}

/** A person's part of the phone's list: a button with their name and how they're doing,
 * folding what's under it. */
function Folding({
  title,
  open: initiallyOpen,
  children,
}: {
  title: string;
  open: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <section className="rounded-chip border border-line bg-surface px-3 py-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
        className="press-row flex min-h-12 w-full items-center gap-2 rounded-button text-left text-row font-bold"
      >
        {open ? (
          <ChevronDown aria-hidden="true" className="size-5" />
        ) : (
          <ChevronRight aria-hidden="true" className="size-5" />
        )}
        {title}
      </button>
      {open ? children : null}
    </section>
  );
}

function PhoneWeek({ day, today }: { day: Day; today: string }) {
  const t = useT();
  const { data: settings } = useSettings();
  const { data: members = [] } = useMembers();
  const start = weekOf(today, settings?.week_starts_on ?? 6)[0] ?? today;
  const { data: week } = useChoresWeek(start);
  if (!week) return null;
  return (
    <div className="flex flex-col gap-3">
      {week.columns.map((column) => {
        const person = personOf(members, column.member_id);
        return (
          <section
            key={column.member_id ?? "anyone"}
            data-person={person?.color ?? "everyone"}
            className="rounded-chip border border-line bg-surface px-3 py-2"
          >
            <h2 className="py-2 text-row font-bold">{person ? person.name : t("tasks.anyone")}</h2>
            <WeekRows column={column} today={today} />
          </section>
        );
      })}
      <span hidden>{day.date}</span>
    </div>
  );
}
