import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Check, ChevronRight, Star } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { errorMessage } from "../../api/client";
import { qk } from "../../api/keys";
import { playDone } from "../../lib/done";
import { zonedParts } from "../../lib/dates";
import { flyPoints } from "../../lib/fly";
import { useMembers, useSettings, type Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { GLIDE, useChangeCount } from "../../lib/motion";
import { askForPin } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { useMinute } from "../../lib/time";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { celebrate } from "../../ui/Celebration";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { SwipeRow } from "../../ui/SwipeRow";
import { TickBox } from "../../ui/TickBox";
import { WhoPicker } from "../../ui/WhoPicker";
import { ChoreEditor } from "./ChoreEditor";
import {
  PARENT_CHANGE,
  useChoreChanges,
  useChores,
  type Box,
  type Column,
  type Day,
  type RoutineRun,
  type Waiting,
} from "./data";
import {
  allDoneText,
  boxLabel,
  boxLine,
  clockText,
  countText,
  doneLine,
  routineTitle,
  ruleLine,
} from "./words";

const TURN_WAIT_MS = 2000;
const FOLD_MS = 900;

const boxKey = (box: Box) => `${box.chore_id}|${box.owner_id ?? ""}|${box.due_date}`;
const FLOAT_MS = 1000;

/** Who's looking: a phone's person and whether it may say yes to things (a kid's never does). */
export function useViewer() {
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const kiosk = session?.device_kind === "kiosk";
  return {
    memberId: kiosk ? null : (session?.member?.id ?? null),
    /** Approve and Not now show: a parent's phone, or the wall screen (behind the PIN). */
    answers: kiosk || (session?.is_parent ?? false),
    kiosk,
  };
}

export function personOf(members: Member[], id: string | null | undefined): Member | undefined {
  return id ? members.find((member) => member.id === id) : undefined;
}

/**
 * One column of the day (UX §4 "Chores room"): its person (or Anyone) with "2 of 3" and their
 * stars, the chores to do, then Done with its stamps (seeing them is the reward), then the kid's
 * routines in their window. Its last box brings "All done, Mia!" with the bigger burst.
 */
export function ChoreColumn({
  column,
  day,
  starsOn,
  stars,
  header = true,
  readOnly = false,
}: {
  column: Column;
  day: Day;
  starsOn: boolean;
  /** The person's balance, when stars are on. */
  stars?: number | undefined;
  header?: boolean;
  /** Another day than today (the People view paged): rows without boxes (`ChoreRow`). */
  readOnly?: boolean;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const person = personOf(members, column.member_id);
  const head = useRef<HTMLElement>(null);
  const pops = useChangeCount(column.done);
  const starPops = useChangeCount(stars);
  const allDone = column.total > 0 && column.done === column.total;
  // A row just ticked here stays where it was while it's stamped, then folds into Done (UX §7).
  const [lingering, setLingering] = useState<string[]>([]);
  const linger = (key: string) => {
    setLingering((keys) => [...keys, key]);
    setTimeout(() => {
      setLingering((keys) => keys.filter((k) => k !== key));
    }, FOLD_MS);
  };
  const todo = column.boxes.filter((box) => !box.completion || lingering.includes(boxKey(box)));
  const done = column.boxes.filter((box) => box.completion && !lingering.includes(boxKey(box)));
  const color = person?.color ?? "everyone";
  const name = person ? person.name : t("tasks.anyone");
  return (
    <section
      // On its own (the Chores room) the column is a region named for its person; inside a
      // person's column elsewhere (Who's doing what, a phone's section) it's just a group.
      role={header ? undefined : "group"}
      aria-label={header ? name : t("tasks.column.aria", { name })}
      data-person={color}
      className={`flex min-h-0 flex-col ${display ? "gap-2" : "gap-1"}`}
    >
      {header ? (
        <header
          ref={head}
          className={`flex flex-wrap items-center gap-x-3 gap-y-1 ${display ? "pb-3" : "pb-1"}`}
        >
          <span data-points-to={person?.id} className="inline-flex shrink-0">
            <Avatar member={person ?? null} size={display ? "lg" : "sm"} />
          </span>
          <h2 className={display ? "text-d-title font-bold" : "text-row font-bold"}>{name}</h2>
          {column.total > 0 ? (
            <span
              key={pops}
              className={`font-bold ${pops ? "pop" : ""} ${display ? "text-d-title" : "text-row"}`}
            >
              {countText(column.done, column.total)}
            </span>
          ) : null}
          {starsOn && stars !== undefined && person?.role === "kid" ? (
            <span
              className={`inline-flex items-center gap-1 font-bold text-ink-soft ${
                display ? "text-d-body" : "text-body"
              }`}
            >
              <Star
                aria-hidden="true"
                className={
                  display ? "size-6 fill-sun stroke-sun-ink" : "size-4 fill-sun stroke-sun-ink"
                }
              />
              <span key={starPops} className={starPops ? "pop" : ""}>
                {stars}
              </span>
              <span className="sr-only"> {t("tasks.stars.unit.aria")}</span>
            </span>
          ) : null}
        </header>
      ) : null}
      {allDone ? (
        <p className={`appear font-bold ${display ? "text-d-glance" : "text-title"}`}>
          {allDoneText(person ? person.name : null)}
        </p>
      ) : null}
      {column.total === 0 && !column.routines.some((run) => run.open_now) ? (
        <p className={display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"}>
          {t("tasks.column.nothing")}
        </p>
      ) : null}
      <ul className="flex flex-col">
        {todo.map((box) => (
          <ChoreRow
            key={boxKey(box)}
            box={box}
            owner={person}
            starsOn={starsOn}
            readOnly={readOnly}
            onTicked={() => {
              linger(boxKey(box));
            }}
            onAllDone={() => {
              celebrate(head.current, color, "big");
            }}
          />
        ))}
      </ul>
      {done.length ? (
        <>
          <h3
            className={`font-bold text-ink-soft ${display ? "mt-2 text-d-secondary" : "mt-1 text-secondary"}`}
          >
            {t("tasks.column.done.title")}
          </h3>
          <ul className="flex flex-col">
            {done.map((box) => (
              <ChoreRow
                key={boxKey(box)}
                box={box}
                owner={person}
                starsOn={starsOn}
                readOnly={readOnly}
              />
            ))}
          </ul>
        </>
      ) : null}
      {/* A routine shows during its window (UX §4). */}
      {column.routines
        .filter((run) => run.open_now)
        .map((run) => (
          <RoutineStart key={run.routine_id} run={run} day={day.date} />
        ))}
    </section>
  );
}

/**
 * A chore's row: its box, its title and line. Ticking a fixed chore credits the column's person
 * with one tap; an Anyone chore asks "Who did it?" beside it, with the person whose turn it is
 * picked for 2 seconds so someone else can claim it. Ticking a done box takes it back.
 * `readOnly` (another day than today) draws no box: a check mark before a done row's line,
 * the due line otherwise; the title still opens the task. The title ends in a chevron, since
 * it opens the task (ADR 0036); on a phone that may remove tasks, a swipe left shows Remove.
 */
export function ChoreRow({
  box,
  owner,
  starsOn,
  readOnly = false,
  onTicked,
  onAllDone,
}: {
  box: Box;
  owner: Member | undefined;
  starsOn: boolean;
  readOnly?: boolean;
  /** Ticked here: the column keeps the row in place while it's stamped. */
  onTicked?: () => void;
  onAllDone?: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const viewer = useViewer();
  const changes = useChoreChanges();
  const row = useRef<HTMLLIElement>(null);
  const tick = useRef<HTMLDivElement>(null);
  const [asking, setAsking] = useState(false);
  const [optimistic, setOptimistic] = useState<{ member: string } | null>(null);
  const [floating, setFloating] = useState(0);
  const [editing, setEditing] = useState(false);
  const done = Boolean(box.completion) || optimistic !== null;
  const waiting = box.completion?.status === "pending";
  const doer = personOf(members, box.completion?.member_id ?? optimistic?.member);

  // A server answer replaces the optimistic tick.
  const completionId = box.completion?.id ?? null;
  const [seen, setSeen] = useState(completionId);
  if (seen !== completionId) {
    setSeen(completionId);
    setOptimistic(null);
  }

  const credit = (memberId: string) => {
    const who = personOf(members, memberId);
    if (!who) return;
    setAsking(false);
    setOptimistic({ member: memberId });
    onTicked?.();
    playDone({
      row: row.current,
      box: tick.current,
      person: who.color,
      sound: display && (settings?.display_sounds ?? false),
    });
    // "+2" flies to the person's avatar; with nowhere on screen to land, it rises from the row.
    if (
      starsOn &&
      box.points > 0 &&
      !flyPoints({ from: tick.current, memberId, points: box.points, display })
    ) {
      setFloating((n) => n + 1);
    }
    changes.complete.mutate(
      { box, member: memberId, name: who.name },
      {
        onSuccess: (result) => {
          if (result.all_done) onAllDone?.();
        },
        onError: (error) => {
          setOptimistic(null);
          showToast(errorMessage(error));
        },
      },
    );
  };

  const toggle = () => {
    if (box.completion) {
      changes.undo.mutate(
        { box, member: box.completion.member_id },
        {
          onSuccess: () => {
            showToast(t("tasks.undone.toast"));
          },
          onError: (error) => {
            showToast(errorMessage(error));
          },
        },
      );
      return;
    }
    if (optimistic) return;
    if (box.owner_id) {
      credit(box.owner_id);
      return;
    }
    // On a phone, the person using it did it (a parent's phone can still choose).
    if (!viewer.kiosk && viewer.memberId && !viewer.answers) {
      credit(viewer.memberId);
      return;
    }
    setAsking(true);
  };

  const line = done
    ? box.completion
      ? doneLine(box.completion, members)
      : doer
        ? t("tasks.done.by_name", { name: doer.name })
        : ""
    : boxLine(box, members, starsOn);
  const label = boxLabel(
    optimistic && doer
      ? {
          ...box,
          completion: {
            member_id: doer.id,
            completed_at: new Date().toISOString(),
            status: "done",
          },
        }
      : box,
    members,
    starsOn,
  );
  return (
    // The row glides to where it belongs next (UX §9 "The done row folds"): under Done once it's
    // stamped, back up on Undo, and its neighbours close the gap. Position only, by transform.
    <motion.li
      ref={row}
      layout="position"
      layoutId={`task ${owner?.id ?? "anyone"} ${boxKey(box)}`}
      transition={GLIDE}
      data-person={(doer ?? owner)?.color ?? "everyone"}
      className="relative flex flex-col border-b border-line"
    >
      <SwipeRow
        action={t("app.action.remove")}
        label={t("tasks.remove.action", { name: box.title })}
        // Removing is a parent's: a child's phone has no PIN pad to unlock it (lib/parent).
        disabled={!viewer.answers}
        onAction={() => {
          changes.removeChore.mutate(
            { chore: { id: box.chore_id, title: box.title } },
            {
              onError: (error) => {
                showToast(errorMessage(error));
              },
            },
          );
        }}
      >
        <div className="@container flex items-stretch gap-2">
          {readOnly ? null : (
            <div ref={tick} className="flex">
              <TickBox
                checked={done}
                waiting={waiting}
                person={(doer ?? owner)?.color}
                label={label}
                onToggle={toggle}
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => {
              setEditing(true);
            }}
            className={`press-row flex min-w-0 flex-1 items-center gap-3 rounded-button py-2 pr-2 text-left ${
              display ? "min-h-[72px]" : "min-h-20"
            } ${readOnly ? "pl-2" : ""}`}
          >
            <span className="flex min-w-0 flex-1 flex-col justify-center">
              <span
                className={`font-semibold break-words hyphens-auto ${display ? "text-d-body" : "text-body"} ${
                  done ? "text-ink-soft" : ""
                }`}
              >
                {box.title}
              </span>
              <span className="sr-only">, </span>
              {line ? (
                <span
                  className={`${display ? "text-d-secondary" : "text-secondary"} text-ink-soft ${
                    readOnly && done ? "inline-flex items-center gap-1" : ""
                  }`}
                >
                  {readOnly && done ? (
                    <Check
                      aria-hidden="true"
                      className={`shrink-0 text-p-text ${display ? "size-6" : "size-5"}`}
                    />
                  ) : null}
                  {line}
                </span>
              ) : null}
            </span>
            {/* A row too narrow for its words (People's columns in portrait) keeps the room for
                them: the title still opens the task. */}
            <ChevronRight
              aria-hidden="true"
              className={`shrink-0 text-ink-soft @max-[13rem]:hidden ${display ? "size-6" : "size-5"}`}
            />
          </button>
          {floating ? <FloatingStars key={floating} points={box.points} /> : null}
        </div>
      </SwipeRow>
      {asking ? (
        <WhoDidIt
          turn={box.turn_id}
          onPick={credit}
          onCancel={() => {
            setAsking(false);
          }}
        />
      ) : null}
      {/* Outside the row: its stamp leaves a transform that would hold a fixed panel inside. */}
      {createPortal(
        <ChoreSheet
          open={editing}
          task={{ chore_id: box.chore_id, title: box.title }}
          starsOn={starsOn}
          onClose={() => {
            setEditing(false);
          }}
        />,
        document.body,
      )}
    </motion.li>
  );
}

/** "+2" rising from a ticked row toward its person (UX §7), then gone: when their avatar isn't
 * on screen for it to fly to (lib/fly). */
function FloatingStars({ points }: { points: number }) {
  const display = useShell() === "display";
  const [shown, setShown] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => {
      setShown(false);
    }, FLOAT_MS);
    return () => {
      clearTimeout(timer);
    };
  }, []);
  if (!shown) return null;
  return (
    <span
      aria-hidden="true"
      className={`float-up pointer-events-none absolute top-2 right-3 font-bold text-sun-ink ${
        display ? "text-d-title" : "text-row"
      }`}
    >
      +{points}
    </span>
  );
}

/** "Who did it?" beside an Anyone box (UX §6): whose turn it is is picked for 2 seconds. */
function WhoDidIt({
  turn,
  onPick,
  onCancel,
}: {
  turn: string | null;
  onPick: (memberId: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const [chosen, setChosen] = useState<string | null>(turn);
  const picked = useRef(onPick);
  useEffect(() => {
    picked.current = onPick;
  });
  useEffect(() => {
    if (!turn) return;
    const timer = setTimeout(() => {
      picked.current(turn);
    }, TURN_WAIT_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [turn]);
  return (
    <div className={`flex flex-col gap-3 ${display ? "pb-4 pl-24" : "pb-3 pl-2"}`}>
      <p className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
        {t("tasks.who_did.label")}
      </p>
      <WhoPicker
        label={t("tasks.who_did.label")}
        members={members}
        value={chosen ? [chosen] : []}
        everyone={false}
        wrap
        onChange={(ids) => {
          const [id] = ids;
          if (!id) return;
          setChosen(id);
          onPick(id);
        }}
      />
      <div>
        <Button variant="quiet" onClick={onCancel}>
          {t("app.action.cancel")}
        </Button>
      </div>
    </div>
  );
}

/** A kid's routine in their column during its window (UX §4): Start, Continue, or done. */
export function RoutineStart({ run, day }: { run: RoutineRun; day: string }) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const { data: members = [] } = useMembers();
  const kid = personOf(members, run.member_id);
  const checked = run.checked.length;
  const total = run.steps.length;
  const title = routineTitle(run.title, kid?.name);
  const when = clockText(run.window_start);
  const start = () => {
    void navigate({
      to: "/$room/$",
      params: { room: "chores", _splat: `run/${run.routine_id}/${run.member_id}/${day}` },
    });
  };
  return (
    <div
      data-person={kid?.color ?? "everyone"}
      className={`mt-2 flex flex-wrap items-center justify-between gap-3 rounded-button border-2 border-p bg-p-tint ${
        display ? "p-4" : "p-3"
      }`}
    >
      <span className="flex min-w-0 flex-col">
        <span className={display ? "text-d-body font-bold" : "text-body font-bold"}>{title}</span>
        <span className={display ? "text-d-secondary" : "text-secondary"}>
          {run.finished
            ? t("tasks.routine.all_done")
            : checked > 0
              ? t("tasks.runner.step", { n: Math.min(checked + 1, total), total })
              : when}
        </span>
      </span>
      {run.finished ? (
        <Check aria-hidden="true" className={display ? "size-9" : "size-6"} />
      ) : run.open_now ? (
        <Button onClick={start}>
          {checked > 0 ? t("tasks.routine.continue.action") : t("tasks.routine.start.action")}
        </Button>
      ) : null}
    </div>
  );
}

/** Chores waiting for a parent's OK, for a parent (or the PIN on the wall screen). */
export function WaitingStrip({ waiting }: { waiting: Waiting[] }) {
  const t = useT();
  const display = useShell() === "display";
  const viewer = useViewer();
  const { data: members = [] } = useMembers();
  const { answer } = useChoreChanges();
  if (!waiting.length || !viewer.answers) return null;
  return (
    <Strip title={t("tasks.waiting.title")}>
      {waiting.map((item) => {
        const who = personOf(members, item.completion.member_id);
        return (
          <div
            key={item.completion.id}
            className="flex flex-wrap items-center justify-between gap-3 py-2"
          >
            <span className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
              {item.title}
              {who ? ` · ${who.name}` : ""}
            </span>
            <span className="flex gap-2">
              <Button
                pending={
                  answer.isPending && answer.variables.waiting === item && answer.variables.yes
                }
                onClick={() => {
                  answer.mutate({ waiting: item, yes: true });
                }}
              >
                {t("tasks.waiting.yes.action")}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  answer.mutate({ waiting: item, yes: false });
                }}
              >
                {t("tasks.waiting.no.action")}
              </Button>
            </span>
          </div>
        );
      })}
    </Strip>
  );
}

export function Strip({ title, children }: { title: string; children: ReactNode }) {
  const display = useShell() === "display";
  return (
    <section
      aria-label={title}
      className={`rounded-button border-2 border-sun bg-surface ${display ? "px-5 py-3" : "px-4 py-2"}`}
    >
      <h2 className={display ? "text-d-body font-bold" : "text-body font-bold"}>{title}</h2>
      {children}
    </section>
  );
}

/**
 * A task, opened from its row (UX §4, ADR 0036): what it is in words ("Every week on Sat · Sat,
 * Nov 14 · by 5:00 PM · ★2"), then **Change** (on the wall the PIN is asked before the form
 * opens, as an event's Change does), **Skip Today** while it repeats and is due today (with
 * Undo), and **Remove** (with Undo). From All Tasks as from a box.
 */
export function ChoreSheet({
  open,
  task,
  starsOn,
  onClose,
}: {
  open: boolean;
  task: { chore_id: string; title: string };
  starsOn: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: chores = [] } = useChores();
  const { data: members = [] } = useMembers();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const today = zonedParts(useMinute()).day;
  const changes = useChoreChanges();
  const [changing, setChanging] = useState(false);
  const chore = chores.find((c) => c.id === task.chore_id);
  // Changing a task is a parent's: on the wall, the PIN before the form, not after it.
  const guarded =
    display && session?.device_kind === "kiosk" && !session.is_parent && session.has_pin;
  const close = () => {
    setChanging(false);
    onClose();
  };
  return (
    <SidePanel
      open={open}
      title={changing ? t("tasks.sheet.change.title", { name: task.title }) : task.title}
      onClose={close}
    >
      {changing && chore ? (
        <ChoreEditor chore={chore} onDone={close} />
      ) : (
        <div className={`flex flex-col ${display ? "gap-4" : "gap-3"}`}>
          {chore ? (
            <p className={display ? "text-d-body text-ink-soft" : "text-body text-ink-soft"}>
              {ruleLine(chore, members, starsOn, today)}
            </p>
          ) : null}
          <Button
            block
            variant="secondary"
            disabled={!chore}
            onClick={() => {
              void (async () => {
                if (guarded && !(await askForPin(t(PARENT_CHANGE)))) return;
                setChanging(true);
              })();
            }}
          >
            {t("app.action.change")}
          </Button>
          {chore?.rrule && chore.next_due === today ? (
            <Button
              block
              variant="secondary"
              pending={changes.skip.isPending}
              onClick={() => {
                changes.skip.mutate(
                  { choreId: task.chore_id, day: today, title: task.title },
                  { onSuccess: close },
                );
              }}
            >
              {t("tasks.sheet.skip.action")}
            </Button>
          ) : null}
          <Button
            block
            variant="quiet-danger"
            pending={changes.removeChore.isPending}
            onClick={() => {
              changes.removeChore.mutate(
                { chore: { id: task.chore_id, title: task.title } },
                { onSuccess: close },
              );
            }}
          >
            {t("tasks.remove.action", { name: task.title })}
          </Button>
          {changes.skip.isError || changes.removeChore.isError ? (
            <p role="alert" className="font-semibold text-alert">
              {errorMessage(changes.skip.error ?? changes.removeChore.error)}
            </p>
          ) : null}
        </div>
      )}
    </SidePanel>
  );
}
