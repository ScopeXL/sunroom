/**
 * Chores' data (PLAN §11.3, ADR 0025): a day's columns, the week, the chores, stars and rewards,
 * routines, and every change with the toast UX §2 names. On the wall screen a tick or a request
 * says who with X-Sunroom-Member (the column's person, or the "Who did it?" answer); parent
 * things ask for the PIN there (lib/parent).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, asMember, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { qk } from "../../api/keys";
import { usePlugins } from "../../lib/household";
import { t, type Key } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { starsToast } from "./words";

export type Day = components["schemas"]["DayOut"];
export type Column = components["schemas"]["ColumnOut"];
export type Box = components["schemas"]["BoxOut"];
export type Completion = components["schemas"]["CompletionOut"];
export type Stars = components["schemas"]["StarsOut"];
export type RoutineRun = components["schemas"]["RoutineRunOut"];
export type Redemption = components["schemas"]["RedemptionOut"];
export type Waiting = components["schemas"]["WaitingOut"];
export type Week = components["schemas"]["WeekOut"];
export type Chore = components["schemas"]["ChoreOut"];
export type ChoreIn = components["schemas"]["ChoreIn"];
/** A change to a chore: only what's sent changes (the clear_ flags default to false). */
export type ChorePatch = Omit<
  components["schemas"]["ChorePatch"],
  "clear_due_time" | "clear_requires_approval" | "clear_rrule"
> & { clear_due_time?: boolean; clear_requires_approval?: boolean; clear_rrule?: boolean };
export type Reward = components["schemas"]["RewardOut"];
export type Routine = components["schemas"]["RoutineOut"];
export type RoutineIn = components["schemas"]["RoutineIn"];
export type StepIn = components["schemas"]["StepIn"];

/** Why the PIN pad opens, as keys: said in the page's language when it asks. */
export const PARENT_CHANGE: Key = "tasks.pin.change";
const PARENT_ANSWER: Key = "tasks.pin.answer";

export function useChoresDay(day: string) {
  return useQuery({
    queryKey: qk.choresDay(day),
    queryFn: async () =>
      unwrap(await api.GET("/api/chores/today", { params: { query: { date: day } } })),
  });
}

export function useChoresWeek(start: string, { enabled = true } = {}) {
  return useQuery({
    queryKey: qk.choresWeek(start),
    queryFn: async () =>
      unwrap(await api.GET("/api/chores/week", { params: { query: { start } } })),
    enabled,
  });
}

export function useChores() {
  return useQuery({
    queryKey: qk.chores(),
    queryFn: async () => unwrap(await api.GET("/api/chores")),
  });
}

export function useRewards({ enabled = true } = {}) {
  return useQuery({
    queryKey: qk.rewards(),
    queryFn: async () => unwrap(await api.GET("/api/chores/rewards")),
    enabled,
  });
}

export function useRoutines(day: string) {
  return useQuery({
    queryKey: qk.routines(day),
    queryFn: async () =>
      unwrap(await api.GET("/api/chores/routines", { params: { query: { date: day } } })),
  });
}

export function useRemovedChores() {
  return useQuery({
    queryKey: qk.choresRemoved(),
    queryFn: async () => unwrap(await api.GET("/api/chores/removed")),
  });
}

export function useChoreChanges() {
  const queryClient = useQueryClient();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["chores"] });
  };

  const undo = useMutation({
    mutationFn: async ({ box, member }: { box: Box; member: string | null }) => {
      unwrap(
        await api.POST("/api/chores/{chore_id}/undo", {
          params: { path: { chore_id: box.chore_id } },
          body: { due_date: box.due_date, member_id: member },
          ...asMember(member),
        }),
      );
    },
    onSettled: refresh,
  });

  /** Tick a box for `member` (the column's person, or who did it). */
  const complete = useMutation({
    mutationFn: async ({ box, member }: { box: Box; member: string | null; name: string }) =>
      unwrap(
        await api.POST("/api/chores/{chore_id}/complete", {
          params: { path: { chore_id: box.chore_id } },
          body: { due_date: box.due_date, member_id: member },
          ...asMember(member),
        }),
      ),
    onSuccess: (done, { box, member, name }) => {
      showToast(
        done.completion.status === "pending"
          ? t("tasks.complete.pending.toast", { name })
          : t("tasks.complete.toast", { name }),
        {
          label: t("app.action.undo"),
          onAction: () => {
            undo.mutate({ box, member });
          },
        },
      );
    },
    onSettled: refresh,
  });

  const answer = useMutation({
    mutationFn: async ({ waiting, yes }: { waiting: Waiting; yes: boolean }) =>
      asParent(
        async () =>
          unwrap(
            yes
              ? await api.POST("/api/chores/completions/{completion_id}/approve", {
                  params: { path: { completion_id: waiting.completion.id } },
                })
              : await api.POST("/api/chores/completions/{completion_id}/reject", {
                  params: { path: { completion_id: waiting.completion.id } },
                }),
          ),
        t(PARENT_ANSWER),
      ),
    onSuccess: (_data, { waiting, yes }) => {
      showToast(
        yes
          ? t("tasks.answer.yes.toast", { name: waiting.title })
          : t("tasks.answer.no.toast", { name: waiting.title }),
      );
    },
    onSettled: refresh,
  });

  const addChore = useMutation({
    mutationFn: async ({ chore, member }: { chore: ChoreIn; member?: string | null }) =>
      unwrap(await api.POST("/api/chores", { body: chore, ...asMember(member) })),
    onSuccess: (chore) => {
      showToast(t("tasks.added.toast", { name: chore.title }), {
        label: t("app.action.undo"),
        onAction: () => {
          removeChore.mutate({ chore, quiet: true });
        },
      });
    },
    onSettled: refresh,
  });

  const changeChore = useMutation({
    mutationFn: async ({ chore, change }: { chore: Chore; change: ChorePatch }) =>
      asParent(
        async () =>
          unwrap(
            await api.PATCH("/api/chores/{chore_id}", {
              params: { path: { chore_id: chore.id } },
              body: {
                clear_due_time: false,
                clear_requires_approval: false,
                clear_rrule: false,
                ...change,
              },
            }),
          ),
        t(PARENT_CHANGE),
      ),
    onSuccess: () => {
      showToast(t("tasks.saved.toast"));
    },
    onSettled: refresh,
  });

  const restoreChore = useMutation({
    mutationFn: async ({ choreId }: { choreId: string }) =>
      asParent(
        async () =>
          unwrap(
            await api.POST("/api/chores/{chore_id}/restore", {
              params: { path: { chore_id: choreId } },
            }),
          ),
        t(PARENT_CHANGE),
      ),
    onSuccess: (chore) => {
      showToast(t("tasks.put_back.toast", { name: chore.title }));
    },
    onSettled: refresh,
  });

  const removeChore = useMutation({
    mutationFn: async ({ chore }: { chore: { id: string; title: string }; quiet?: boolean }) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/chores/{chore_id}", { params: { path: { chore_id: chore.id } } }),
        );
      }, t(PARENT_CHANGE));
    },
    onSuccess: (_data, { chore, quiet }) => {
      if (quiet) return;
      showToast(t("tasks.removed.toast", { name: chore.title }), {
        label: t("app.action.undo"),
        onAction: () => {
          restoreChore.mutate({ choreId: chore.id });
        },
      });
    },
    onSettled: refresh,
  });

  const unskip = useMutation({
    mutationFn: async ({ choreId, day }: { choreId: string; day: string }) =>
      asParent(
        async () =>
          unwrap(
            await api.POST("/api/chores/{chore_id}/unskip", {
              params: { path: { chore_id: choreId } },
              body: { date: day },
            }),
          ),
        t(PARENT_CHANGE),
      ),
    onSettled: refresh,
  });

  const skip = useMutation({
    mutationFn: async ({ choreId, day }: { choreId: string; day: string; title: string }) =>
      asParent(
        async () =>
          unwrap(
            await api.POST("/api/chores/{chore_id}/skip", {
              params: { path: { chore_id: choreId } },
              body: { date: day },
            }),
          ),
        t(PARENT_CHANGE),
      ),
    onSuccess: (_data, { choreId, day, title }) => {
      showToast(t("tasks.skipped.toast", { name: title }), {
        label: t("app.action.undo"),
        onAction: () => {
          unskip.mutate({ choreId, day });
        },
      });
    },
    onSettled: refresh,
  });

  const cancelAsk = useMutation({
    mutationFn: async ({ redemption }: { redemption: Redemption }) =>
      unwrap(
        await api.POST("/api/chores/redemptions/{redemption_id}/cancel", {
          params: { path: { redemption_id: redemption.id } },
          ...asMember(redemption.member_id),
        }),
      ),
    onSettled: refresh,
  });

  const redeem = useMutation({
    mutationFn: async ({ reward, member }: { reward: Reward; member: string; name: string }) =>
      unwrap(
        await api.POST("/api/chores/rewards/{reward_id}/redeem", {
          params: { path: { reward_id: reward.id } },
          body: { member_id: member },
          ...asMember(member),
        }),
      ),
    onSuccess: (redemption, { reward }) => {
      showToast(t("tasks.reward.asked.toast", { name: reward.title }), {
        label: t("tasks.reward.take_back.action"),
        onAction: () => {
          cancelAsk.mutate({ redemption });
        },
      });
    },
    onSettled: refresh,
  });

  const decide = useMutation({
    mutationFn: async ({
      redemption,
      yes,
    }: {
      redemption: Redemption;
      yes: boolean;
      name: string;
    }) =>
      asParent(
        async () =>
          unwrap(
            yes
              ? await api.POST("/api/chores/redemptions/{redemption_id}/approve", {
                  params: { path: { redemption_id: redemption.id } },
                })
              : await api.POST("/api/chores/redemptions/{redemption_id}/deny", {
                  params: { path: { redemption_id: redemption.id } },
                }),
          ),
        t(PARENT_ANSWER),
      ),
    onSuccess: (_data, { redemption, yes, name }) => {
      showToast(
        yes
          ? t("tasks.decide.yes.toast", { name, reward: redemption.reward_title })
          : t("tasks.decide.no.toast", { name }),
      );
    },
    onSettled: refresh,
  });

  const saveReward = useMutation({
    mutationFn: async ({
      reward,
      title,
      cost,
    }: {
      reward: Reward | null;
      title: string;
      cost: number;
    }) =>
      asParent(
        async () =>
          unwrap(
            reward
              ? await api.PATCH("/api/chores/rewards/{reward_id}", {
                  params: { path: { reward_id: reward.id } },
                  body: { title, cost_points: cost },
                })
              : await api.POST("/api/chores/rewards", { body: { title, cost_points: cost } }),
          ),
        t(PARENT_CHANGE),
      ),
    onSuccess: (saved, { reward }) => {
      showToast(reward ? t("tasks.saved.toast") : t("tasks.added.toast", { name: saved.title }));
    },
    onSettled: refresh,
  });

  const removeReward = useMutation({
    mutationFn: async ({ reward }: { reward: Reward }) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/chores/rewards/{reward_id}", {
            params: { path: { reward_id: reward.id } },
          }),
        );
      }, t(PARENT_CHANGE));
    },
    onSuccess: (_data, { reward }) => {
      showToast(t("tasks.removed.toast", { name: reward.title }));
    },
    onSettled: refresh,
  });

  const checkStep = useMutation({
    mutationFn: async ({
      run,
      stepId,
      day,
      checked,
    }: {
      run: RoutineRun;
      stepId: string;
      day: string;
      checked: boolean;
    }) =>
      unwrap(
        await api.POST("/api/chores/routines/{routine_id}/steps/{step_id}/check", {
          params: { path: { routine_id: run.routine_id, step_id: stepId } },
          body: { date: day, member_id: run.member_id, checked },
          ...asMember(run.member_id),
        }),
      ),
    onSettled: refresh,
  });

  const finish = useMutation({
    mutationFn: async ({ run, day }: { run: RoutineRun; day: string }) =>
      unwrap(
        await api.POST("/api/chores/routines/{routine_id}/finish", {
          params: { path: { routine_id: run.routine_id } },
          body: { date: day, member_id: run.member_id },
          ...asMember(run.member_id),
        }),
      ),
    onSuccess: (_data, { run }) => {
      showToast(t("tasks.routine.done.toast", { name: run.title }));
    },
    onSettled: refresh,
  });

  const saveRoutine = useMutation({
    mutationFn: async ({
      routine,
      fields,
      steps,
    }: {
      routine: Routine | null;
      fields: Omit<RoutineIn, "steps">;
      steps: StepIn[];
    }) =>
      asParent(async () => {
        if (!routine) {
          return unwrap(await api.POST("/api/chores/routines", { body: { ...fields, steps } }));
        }
        unwrap(
          await api.PATCH("/api/chores/routines/{routine_id}", {
            params: { path: { routine_id: routine.id } },
            body: { ...fields, every_kid: fields.member_id === null },
          }),
        );
        return unwrap(
          await api.PUT("/api/chores/routines/{routine_id}/steps", {
            params: { path: { routine_id: routine.id } },
            body: { steps },
          }),
        );
      }, t(PARENT_CHANGE)),
    onSuccess: (saved, { routine }) => {
      showToast(routine ? t("tasks.saved.toast") : t("tasks.added.toast", { name: saved.title }));
    },
    onSettled: refresh,
  });

  const removeRoutine = useMutation({
    mutationFn: async ({ routine }: { routine: Routine }) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/chores/routines/{routine_id}", {
            params: { path: { routine_id: routine.id } },
          }),
        );
      }, t(PARENT_CHANGE));
    },
    onSuccess: (_data, { routine }) => {
      showToast(t("tasks.removed.toast", { name: routine.title }));
    },
    onSettled: refresh,
  });

  // To one child or several at once (ADR 0034); the toast names them all.
  const adjust = useMutation({
    mutationFn: async ({
      members,
      points,
      reason,
    }: {
      members: string[];
      points: number;
      reason: string;
      names: string[];
    }) =>
      asParent(
        async () =>
          unwrap(
            await api.POST("/api/chores/points/adjust", {
              body: { member_ids: members, points, reason },
            }),
          ),
        t(PARENT_CHANGE),
      ),
    onSuccess: (_data, { points, names }) => {
      showToast(starsToast(points, names));
    },
    onSettled: refresh,
  });

  return {
    complete,
    undo,
    answer,
    addChore,
    changeChore,
    removeChore,
    restoreChore,
    skip,
    unskip,
    redeem,
    cancelAsk,
    decide,
    saveReward,
    removeReward,
    checkStep,
    finish,
    saveRoutine,
    removeRoutine,
    adjust,
  };
}

/** The chores plugin's switches (Settings → Features or Settings → Chores). */
export function useChoreSettings(): {
  stars: boolean;
  rewards: boolean;
  routines: boolean;
  approval: boolean;
} {
  const { data: plugins = [] } = usePlugins();
  const settings = plugins.find((plugin) => plugin.id === "chores")?.settings ?? {};
  return {
    stars: settings.stars !== false,
    rewards: settings.rewards !== false,
    routines: settings.routines !== false,
    approval: settings.approval === true,
  };
}
