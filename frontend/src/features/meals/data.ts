/**
 * Meals' data (PLAN §11.3): a week's meals, saved meals, what was removed, and every change
 * with the toast UX §2 names and Undo. "Add ingredients to Groceries" puts a saved meal's
 * ingredients on the Lists plugin's Groceries through its own API, and only shows while Lists
 * is on (ADR 0002: plugins never reach into each other's tables).
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, asMember, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { usePlugins } from "../../lib/household";
import { t, type Key } from "../../lib/lang";
import { showToast } from "../../lib/toast";

export type Week = components["schemas"]["MealWeekOut"];
export type Entry = components["schemas"]["EntryOut"];
export type EntryIn = components["schemas"]["EntryIn"];
export type Saved = components["schemas"]["SavedMealOut"];
export type SavedIn = components["schemas"]["SavedMealIn"];
export type SavedPatch = components["schemas"]["SavedMealPatch"];
export type Slot = Entry["slot"];

/** Each meal of the day's word, a key translated where it's shown (ADR 0043). A sentence that
 * names a meal ("Add dinner") says it in its own message, with a select on the slot. */
export const SLOT_WORDS: Record<Slot, Key> = {
  breakfast: "meals.slot.breakfast",
  lunch: "meals.slot.lunch",
  dinner: "meals.slot.dinner",
  snack: "meals.slot.snack",
};

export const mealKeys = {
  week: (start: string, days: number) => ["meals", "week", start, days] as const,
  saved: (q: string) => ["meals", "saved", q] as const,
  removed: () => ["meals", "removed"] as const,
};

export function useWeek(start: string, days = 7) {
  return useQuery({
    queryKey: mealKeys.week(start, days),
    queryFn: async () =>
      unwrap(await api.GET("/api/meals/week", { params: { query: { start, days } } })),
  });
}

export function useSaved(q = "") {
  const words = q.trim();
  return useQuery({
    queryKey: mealKeys.saved(words),
    queryFn: async () =>
      unwrap(await api.GET("/api/meals/saved", { params: { query: words ? { q: words } : {} } })),
  });
}

export function useRemovedMeals() {
  return useQuery({
    queryKey: mealKeys.removed(),
    queryFn: async () => unwrap(await api.GET("/api/meals/removed")),
  });
}

async function refresh(queryClient: QueryClient): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["meals"] }),
    queryClient.invalidateQueries({ queryKey: ["occurrences"] }),
  ]);
}

/** "Tacos", or "Tacos (Dinner)" when the household plans more than dinner. */
export function mealName(entry: { text: string; emoji?: string | null }): string {
  return entry.emoji ? `${entry.emoji} ${entry.text}` : entry.text;
}

function fieldsOf(entry: Entry): EntryIn {
  return {
    id: entry.id,
    day: entry.day,
    slot: entry.slot,
    position: entry.position,
    text: entry.text,
    emoji: entry.emoji,
    recipe_url: entry.recipe_url,
    note: entry.note,
    member_id: entry.member_id,
    saved_meal_id: entry.saved_meal_id,
  };
}

export function useMealChanges() {
  const queryClient = useQueryClient();

  const putBack = async (entry: Entry) => {
    unwrap(
      await api.POST("/api/meals/entries/{entry_id}/restore", {
        params: { path: { entry_id: entry.id } },
      }),
    );
  };
  const undoLater = (work: () => Promise<void>) => () => {
    void work()
      .then(() => refresh(queryClient))
      .catch(() => {
        showToast(t("app.undo.error"));
      });
  };

  /** Add or change one (PUT meals/entries); Undo puts back what was there before. */
  const save = useMutation({
    mutationFn: async ({
      body,
      member,
    }: {
      body: EntryIn;
      member?: string | null;
      before?: Entry | null;
    }) => unwrap(await api.PUT("/api/meals/entries", { body, ...asMember(member) })),
    onSuccess: async ({ entry, replaced }, { body, before }) => {
      await refresh(queryClient);
      const changed = Boolean(body.id);
      showToast(
        changed
          ? t("meals.entry.saved.toast", { name: entry.text })
          : t("meals.entry.added.toast", { name: entry.text }),
        {
          label: t("app.action.undo"),
          onAction: undoLater(async () => {
            if (changed && before) {
              unwrap(await api.PUT("/api/meals/entries", { body: fieldsOf(before) }));
              return;
            }
            unwrap(
              await api.DELETE("/api/meals/entries/{entry_id}", {
                params: { path: { entry_id: entry.id } },
              }),
            );
            if (replaced) await putBack(replaced);
          }),
        },
      );
    },
  });

  const remove = useMutation({
    mutationFn: async ({ entry }: { entry: Entry }) => {
      unwrap(
        await api.DELETE("/api/meals/entries/{entry_id}", {
          params: { path: { entry_id: entry.id } },
        }),
      );
    },
    onSuccess: async (_done, { entry }) => {
      await refresh(queryClient);
      showToast(t("meals.entry.removed.toast", { name: entry.text }), {
        label: t("app.action.undo"),
        onAction: undoLater(() => putBack(entry)),
      });
    },
  });

  const restore = useMutation({
    mutationFn: async ({ entry }: { entry: { id: string; text: string } }) => {
      unwrap(
        await api.POST("/api/meals/entries/{entry_id}/restore", {
          params: { path: { entry_id: entry.id } },
        }),
      );
    },
    onSuccess: async (_done, { entry }) => {
      await refresh(queryClient);
      showToast(t("meals.entry.put_back.toast", { name: entry.text }));
    },
  });

  /** Swap days: move it, and whatever was on that day takes its place. */
  const move = useMutation({
    mutationFn: async ({ entry, day }: { entry: Entry; day: string }) =>
      unwrap(
        await api.POST("/api/meals/entries/{entry_id}/move", {
          params: { path: { entry_id: entry.id } },
          body: { day, slot: entry.slot },
        }),
      ),
    onSuccess: async ({ moved, swapped }, { entry }) => {
      await refresh(queryClient);
      showToast(
        swapped
          ? t("meals.entry.swapped.toast", { name: moved.text, other: swapped.text })
          : t("meals.entry.moved.toast", { name: moved.text }),
        {
          label: t("app.action.undo"),
          onAction: undoLater(async () => {
            unwrap(
              await api.POST("/api/meals/entries/{entry_id}/move", {
                params: { path: { entry_id: entry.id } },
                body: { day: entry.day, slot: entry.slot },
              }),
            );
          }),
        },
      );
    },
  });

  const copyWeek = useMutation({
    mutationFn: async ({ from, to }: { from: string; to: string }) =>
      unwrap(await api.POST("/api/meals/copy-week", { body: { from_start: from, to_start: to } })),
    onSuccess: async ({ ids, skipped }) => {
      await refresh(queryClient);
      if (!ids.length) {
        showToast(skipped ? t("meals.week.copy_full.toast") : t("meals.week.copy_none.toast"));
        return;
      }
      showToast(t("meals.week.copied.toast", { n: ids.length }), {
        label: t("app.action.undo"),
        onAction: undoLater(async () => {
          for (const id of ids) {
            unwrap(
              await api.DELETE("/api/meals/entries/{entry_id}", {
                params: { path: { entry_id: id } },
              }),
            );
          }
        }),
      });
    },
  });

  const addSaved = useMutation({
    mutationFn: async ({ body, member }: { body: SavedIn; member?: string | null }) =>
      unwrap(await api.POST("/api/meals/saved", { body, ...asMember(member) })),
    onSuccess: async (saved) => {
      await refresh(queryClient);
      showToast(t("meals.saved.save.toast", { name: saved.text }));
    },
  });

  const changeSaved = useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: SavedPatch }) =>
      unwrap(
        await api.PATCH("/api/meals/saved/{saved_id}", {
          params: { path: { saved_id: id } },
          body: patch,
        }),
      ),
    onSuccess: async (saved) => {
      await refresh(queryClient);
      showToast(t("meals.saved.save.toast", { name: saved.text }));
    },
  });

  const restoreSaved = async (id: string) => {
    unwrap(
      await api.POST("/api/meals/saved/{saved_id}/restore", {
        params: { path: { saved_id: id } },
      }),
    );
  };

  const archiveSaved = useMutation({
    mutationFn: async ({ saved }: { saved: { id: string; text: string } }) => {
      unwrap(
        await api.DELETE("/api/meals/saved/{saved_id}", {
          params: { path: { saved_id: saved.id } },
        }),
      );
    },
    onSuccess: async (_done, { saved }) => {
      await refresh(queryClient);
      showToast(t("meals.saved.archived.toast", { name: saved.text }), {
        label: t("app.action.undo"),
        onAction: undoLater(() => restoreSaved(saved.id)),
      });
    },
  });

  const unarchiveSaved = useMutation({
    mutationFn: async ({ saved }: { saved: { id: string; text: string } }) => {
      await restoreSaved(saved.id);
    },
    onSuccess: async (_done, { saved }) => {
      await refresh(queryClient);
      showToast(t("meals.saved.put_back.toast", { name: saved.text }));
    },
  });

  return {
    save,
    remove,
    restore,
    move,
    copyWeek,
    addSaved,
    changeSaved,
    archiveSaved,
    unarchiveSaved,
  };
}

/** Whether Lists is on, so "Add ingredients to Groceries" can show. */
export function useListsOn(): boolean {
  const { data: plugins = [] } = usePlugins();
  return plugins.some((plugin) => plugin.id === "lists" && plugin.enabled);
}

/**
 * Put a meal's ingredients on Groceries (the Lists plugin's API): the first grocery list, made
 * if there's none. What's already on it to get isn't added twice (the Lists API says which).
 */
export function useAddToGroceries() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ items, member }: { items: string[]; member?: string | null }) => {
      const lists = unwrap(await api.GET("/api/lists"));
      const groceries =
        lists.find((list) => list.kind === "grocery") ??
        unwrap(
          await api.POST("/api/lists", {
            // A new list's name: the family's own once it's made, so it's made in their language.
            body: { name: t("meals.groceries.name"), kind: "grocery" },
          }),
        );
      const added = unwrap(
        await api.POST("/api/lists/{list_id}/items", {
          params: { path: { list_id: groceries.id } },
          body: { items: items.map((text) => ({ text })) },
          ...asMember(member),
        }),
      );
      return { list: groceries, added };
    },
    onSuccess: async ({ list, added }) => {
      await queryClient.invalidateQueries({ queryKey: ["lists"] });
      const count = added.items.length;
      showToast(
        count === 0
          ? t("meals.groceries.already.toast", { list: list.name })
          : t("meals.groceries.added.toast", { n: count, list: list.name }),
        count
          ? {
              label: t("app.action.undo"),
              onAction: () => {
                void (async () => {
                  for (const item of added.items) {
                    unwrap(
                      await api.DELETE("/api/lists/{list_id}/items/{item_id}", {
                        params: { path: { list_id: list.id, item_id: item.id } },
                      }),
                    );
                  }
                  await queryClient.invalidateQueries({ queryKey: ["lists"] });
                })().catch(() => {
                  showToast(t("app.undo.error"));
                });
              },
            }
          : undefined,
      );
    },
  });
}
