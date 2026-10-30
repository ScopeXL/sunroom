import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion, useIsPresent } from "motion/react";
import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";

import { holdIdle } from "../../lib/displayState";
import { playDone } from "../../lib/done";
import { useMembers, useSettings } from "../../lib/household";
import { whenIdle } from "../../lib/idle";
import { useT } from "../../lib/lang";
import { EXIT, useMotionReduced } from "../../lib/motion";
import { Button } from "../../ui/Button";
import { celebrate } from "../../ui/Celebration";
import { useShell } from "../../ui/shell";
import { personOf } from "./ChoreBoard";
import { useChoreChanges, useRoutines } from "./data";
import { stepIcon } from "./icons";
import { routineTitle } from "./words";

const GIVE_UP_MS = 30 * 60_000;
const FINISH_MS = 6000;

/**
 * The routine runner (UX §4, §6 "A kid runs a bedtime routine"): the whole screen, one step at a
 * time: its picture, its name at 64 px, dots for progress (hollow for a skipped one), a 120 px
 * Done in the kid's color that stamps and bursts, and a quiet Skip this one. The last Done
 * shows "All done, Leo! Night night." with the full burst and the stars it gave, then Chores.
 * Stop asks nothing: checked steps are kept, so it continues later. The screen's idle return
 * waits while it runs, for up to 30 minutes.
 */
export function RoutineRunner({
  routineId,
  memberId,
  day,
}: {
  routineId: string;
  memberId: string;
  day: string;
}) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const { data } = useRoutines(day);
  const { data: members = [] } = useMembers();
  const { data: settings } = useSettings();
  const { checkStep, finish } = useChoreChanges();
  const run = data?.runs.find((r) => r.routine_id === routineId && r.member_id === memberId);
  const kid = personOf(members, memberId);
  const [done, setDone] = useState<string[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [finished, setFinished] = useState<{ stars: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const screen = useRef<HTMLDivElement>(null);

  const back = () => {
    void navigate({ to: "/$room", params: { room: "chores" } });
  };
  const leave = useRef(back);
  useEffect(() => {
    leave.current = back;
  });
  useEffect(() => holdIdle(), []);
  useEffect(
    () =>
      whenIdle(GIVE_UP_MS, () => {
        leave.current();
      }),
    [],
  );
  const over = finished !== null;
  useEffect(() => {
    if (!over) return;
    const timer = setTimeout(() => {
      leave.current();
    }, FINISH_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [over]);

  if (!run || !kid) {
    return data ? (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-6 bg-wall">
        <p className={display ? "text-d-title font-bold" : "text-title font-bold"}>
          {t("tasks.runner.missing")}
        </p>
        <Button onClick={back}>{t("tasks.back.action")}</Button>
      </div>
    ) : null;
  }

  const title = routineTitle(run.title, kid.name);
  const steps = [...run.steps].sort((a, b) => a.position - b.position);
  const checked = new Set([...run.checked, ...done]);
  const current = steps.find((step) => !checked.has(step.id) && !skipped.includes(step.id));
  const position = current ? steps.indexOf(current) + 1 : steps.length;
  const evening = run.window_start >= "16:00";
  // A dot's state, a code its words (`tasks.runner.dot.aria`) and its look are picked by.
  const stateOf = (id: string): "done" | "skipped" | "now" | "todo" =>
    checked.has(id)
      ? "done"
      : skipped.includes(id)
        ? "skipped"
        : id === current?.id
          ? "now"
          : "todo";

  const complete = (anyDone: boolean) => {
    setFinished({ stars: 0 });
    celebrate(screen.current, kid.color, "full");
    // Skipping every step finishes it, but stars are for doing.
    if (!anyDone) return;
    finish.mutate(
      { run, day },
      {
        onSuccess: (result) => {
          setFinished({ stars: result.points_awarded });
        },
      },
    );
  };
  const next = (afterDone: boolean) => {
    if (!current) return;
    const remaining = steps.filter(
      (step) => step.id !== current.id && !checked.has(step.id) && !skipped.includes(step.id),
    );
    if (afterDone) {
      setDone((list) => [...list, current.id]);
      checkStep.mutate({ run, stepId: current.id, day, checked: true });
      playDone({
        row: button.current,
        box: button.current,
        person: kid.color,
        sound: display && (settings?.display_sounds ?? false),
      });
    } else {
      setSkipped((list) => [...list, current.id]);
    }
    if (remaining.length === 0) complete(afterDone || checked.size > 0);
  };

  const icon = (key: string | null | undefined) => {
    const Icon = stepIcon(key);
    return (
      <Icon aria-hidden="true" className={display ? "size-60" : "size-32"} strokeWidth={1.75} />
    );
  };

  return (
    <div
      ref={screen}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-person={kid.color}
      className="fixed inset-0 z-50 flex flex-col bg-wall text-ink"
    >
      <header
        className={`flex items-center justify-between gap-4 border-b border-line ${display ? "px-8 py-5" : "px-4 py-3"}`}
      >
        <h1 className={display ? "text-d-title font-bold" : "text-row font-bold"}>{title}</h1>
        {!finished ? (
          <span className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
            {t("tasks.runner.step", { n: position, total: steps.length })}
          </span>
        ) : null}
        <Button variant="secondary" onClick={back}>
          {finished ? t("tasks.back.action") : t("tasks.runner.stop.action")}
        </Button>
      </header>
      {finished || !current ? (
        <button
          type="button"
          onClick={back}
          className="appear flex flex-1 flex-col items-center justify-center gap-6 px-6 text-center"
        >
          <span className={display ? "text-d-step font-extrabold" : "text-big font-extrabold"}>
            {evening
              ? t("tasks.runner.all_done.night", { name: kid.name })
              : t("tasks.all_done.person", { name: kid.name })}
          </span>
          {finished && finished.stars > 0 ? (
            <span
              className={
                display
                  ? "text-d-title font-bold text-sun-ink"
                  : "text-title font-bold text-sun-ink"
              }
            >
              {t("tasks.runner.stars", { n: finished.stars })}
            </span>
          ) : null}
        </button>
      ) : (
        // The step just done slides off to the left while the next comes in from the right
        // (UX §9 "Routine step"): it's taken out of the layout as it goes, so the new one has
        // the screen.
        <AnimatePresence mode="popLayout" initial={false}>
          <Step
            key={current.id}
            className={`step-in flex flex-1 flex-col items-center justify-center ${display ? "gap-8 px-8" : "gap-5 px-4"}`}
          >
            <span className="text-p-text">{icon(current.icon)}</span>
            <h2
              className={`text-center ${display ? "text-d-step font-extrabold" : "text-big font-extrabold"}`}
            >
              {current.title}
            </h2>
            <ol aria-label={t("tasks.runner.steps.aria")} className="flex gap-3">
              {steps.map((step) => {
                const state = stateOf(step.id);
                return (
                  <li
                    key={step.id}
                    aria-label={t("tasks.runner.dot.aria", { step: step.title, state })}
                    className={`rounded-full border-[3px] ${display ? "size-6" : "size-4"} ${
                      state === "done"
                        ? "border-p bg-p"
                        : state === "now"
                          ? "border-p bg-p-tint"
                          : "border-ink-soft"
                    }`}
                  />
                );
              })}
            </ol>
            <button
              // Only ever set: the step that's leaving still holds its own button for a moment,
              // and must not clear the new one's on its way out.
              ref={(node) => {
                if (node) button.current = node;
              }}
              type="button"
              onClick={() => {
                next(true);
              }}
              className={`press rounded-button-d bg-p font-extrabold text-on-ink ${
                display ? "h-[120px] w-3/5 text-d-glance" : "min-h-16 w-full text-title"
              }`}
            >
              {t("tasks.runner.step_done.action")}
            </button>
            <Button
              variant="quiet"
              onClick={() => {
                next(false);
              }}
            >
              {t("tasks.runner.skip.action")}
            </Button>
          </Step>
        </AnimatePresence>
      )}
    </div>
  );
}

/** One step on the screen. When the next one takes its place it slides off to the left and
 * fades, already out of reach: its Done can't be tapped twice, and a screen reader hears only
 * the new step. */
function Step({
  ref,
  className,
  children,
}: {
  ref?: Ref<HTMLElement>;
  className: string;
  children: ReactNode;
}) {
  const present = useIsPresent();
  const reduced = useMotionReduced();
  return (
    <motion.main
      ref={ref}
      inert={!present}
      aria-hidden={present ? undefined : true}
      className={className}
      {...(reduced ? {} : { exit: { opacity: 0, x: "-12%", transition: EXIT } })}
    >
      {children}
    </motion.main>
  );
}
