/**
 * Lists' data (PLAN §11.3): the lists, one list's items with its Usuals, items due (To do), and
 * every change, each with the toast UX §2 names and Undo where it applies. On the wall screen a
 * change says who did it only when someone tapped their avatar first (`member`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, asMember, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { qk } from "../../api/keys";
import { t } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";

export type ListInfo = components["schemas"]["ListOut"];
export type ListDetail = components["schemas"]["ListDetailOut"];
export type Item = components["schemas"]["ItemOut"];
export type TodoItem = components["schemas"]["TodoItemOut"];
/** A change to an item: only what's sent changes (the clear_ flags default to false). */
export type ItemPatch = Omit<
  components["schemas"]["ItemPatch"],
  "clear_assignee" | "clear_due_date"
> & { clear_assignee?: boolean; clear_due_date?: boolean };

export function useLists() {
  return useQuery({
    queryKey: qk.lists(),
    queryFn: async () => unwrap(await api.GET("/api/lists")),
  });
}

export function useList(listId: string | null) {
  return useQuery({
    queryKey: qk.list(listId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/lists/{list_id}/items", {
          params: { path: { list_id: listId ?? "" } },
        }),
      ),
    enabled: listId !== null,
  });
}

export function useTodo(day: string) {
  return useQuery({
    queryKey: qk.listsTodo(day),
    queryFn: async () =>
      unwrap(await api.GET("/api/lists/todo", { params: { query: { date: day } } })),
  });
}

export function useRemovedLists() {
  return useQuery({
    queryKey: qk.listsRemoved(),
    queryFn: async () => unwrap(await api.GET("/api/lists/removed")),
  });
}

export function useListChanges() {
  const queryClient = useQueryClient();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["lists"] });
  };

  const restoreItems = useMutation({
    mutationFn: async ({ listId, ids }: { listId: string; ids: string[] }) =>
      unwrap(
        await api.POST("/api/lists/{list_id}/restore-items", {
          params: { path: { list_id: listId } },
          body: { ids },
        }),
      ),
    onSettled: refresh,
  });

  const removeItem = useMutation({
    mutationFn: async ({ item }: { item: Item; member?: string | null | undefined }) => {
      unwrap(
        await api.DELETE("/api/lists/{list_id}/items/{item_id}", {
          params: { path: { list_id: item.list_id, item_id: item.id } },
        }),
      );
    },
    onSuccess: (_data, { item }) => {
      showToast(t("lists.removed.toast", { name: item.text }), {
        label: t("app.action.undo"),
        onAction: () => {
          restoreItems.mutate({ listId: item.list_id, ids: [item.id] });
        },
      });
    },
    onSettled: refresh,
  });

  const addItems = useMutation({
    mutationFn: async ({
      listId,
      texts,
      member,
      dueDate,
      assignee,
    }: {
      listId: string;
      texts: string[];
      member?: string | null;
      dueDate?: string | null;
      assignee?: string | null;
    }) =>
      unwrap(
        await api.POST("/api/lists/{list_id}/items", {
          params: { path: { list_id: listId } },
          body: {
            items: texts.map((text) => ({
              text,
              due_date: dueDate ?? null,
              assigned_member_id: assignee ?? null,
            })),
          },
          ...asMember(member),
        }),
      ),
    onSuccess: (added, { member }) => {
      const [first] = added.items;
      if (added.items.length === 0) {
        showToast(
          added.already.length === 1
            ? t("lists.added.already.toast", { name: added.already[0] ?? "" })
            : t("lists.added.already_several.toast"),
        );
        return;
      }
      showToast(
        added.items.length === 1 && first
          ? t("lists.added.toast", { name: first.text })
          : t("lists.added.several.toast", { n: added.items.length }),
        {
          label: t("app.action.undo"),
          onAction: () => {
            for (const item of added.items) removeItem.mutate({ item, member });
          },
        },
      );
    },
    onSettled: refresh,
  });

  const patchItem = useMutation({
    mutationFn: async ({
      item,
      change,
      member,
    }: {
      item: Item;
      change: ItemPatch;
      member?: string | null | undefined;
    }) =>
      unwrap(
        await api.PATCH("/api/lists/{list_id}/items/{item_id}", {
          params: { path: { list_id: item.list_id, item_id: item.id } },
          body: { clear_assignee: false, clear_due_date: false, ...change },
          ...asMember(member),
        }),
      ),
    onSettled: refresh,
  });

  /** Check off or put back, with "Checked off Milk · Undo" (UX §4). */
  const check = (item: Item, checked: boolean, member?: string | null) => {
    patchItem.mutate(
      { item, change: { checked }, member },
      {
        onSuccess: () => {
          if (!checked) return;
          showToast(t("lists.checked.toast", { name: item.text }), {
            label: t("app.action.undo"),
            onAction: () => {
              patchItem.mutate({ item, change: { checked: false }, member });
            },
          });
        },
      },
    );
  };

  const clearDone = useMutation({
    mutationFn: async ({ listId }: { listId: string }) =>
      unwrap(
        await api.POST("/api/lists/{list_id}/clear-checked", {
          params: { path: { list_id: listId } },
        }),
      ),
    onSuccess: ({ ids }, { listId }) => {
      showToast(t("lists.cleared.toast", { n: ids.length }), {
        label: t("app.action.undo"),
        onAction: () => {
          restoreItems.mutate({ listId, ids });
        },
      });
    },
    onSettled: refresh,
  });

  const createList = useMutation({
    mutationFn: async ({ name }: { name: string }) =>
      unwrap(await api.POST("/api/lists", { body: { name } })),
    onSuccess: (list) => {
      showToast(t("lists.made.toast", { name: list.name }));
    },
    onSettled: refresh,
  });

  const renameList = useMutation({
    mutationFn: async ({ list, name }: { list: ListInfo; name: string }) =>
      unwrap(
        await api.PATCH("/api/lists/{list_id}", {
          params: { path: { list_id: list.id } },
          body: { name },
        }),
      ),
    onSuccess: () => {
      showToast(t("lists.saved.toast"));
    },
    onSettled: refresh,
  });

  const restoreList = useMutation({
    mutationFn: async ({ listId }: { listId: string }) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/lists/{list_id}/restore", {
            params: { path: { list_id: listId } },
          }),
        ),
      ),
    onSuccess: (list) => {
      showToast(t("lists.put_back.toast", { name: list.name }));
    },
    onSettled: refresh,
  });

  const removeList = useMutation({
    mutationFn: async ({ list }: { list: ListInfo }) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/lists/{list_id}", { params: { path: { list_id: list.id } } }),
        );
      }, t("lists.remove.pin"));
    },
    onSuccess: (_data, { list }) => {
      showToast(t("lists.removed.toast", { name: list.name }), {
        label: t("app.action.undo"),
        onAction: () => {
          restoreList.mutate({ listId: list.id });
        },
      });
    },
    onSettled: refresh,
  });

  return {
    addItems,
    patchItem,
    check,
    removeItem,
    restoreItems,
    clearDone,
    createList,
    renameList,
    removeList,
    restoreList,
  };
}
