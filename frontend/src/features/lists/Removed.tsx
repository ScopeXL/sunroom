import { useEffect } from "react";

import { useT } from "../../lib/lang";
import { RemovedRow } from "../settings/RecentlyRemoved";
import { useListChanges, useRemovedLists } from "./data";

/** Lists and items removed in the last 7 days, in Recently removed (UX §4). */
export function RemovedListRows({ onCount }: { onCount: (count: number) => void }) {
  const t = useT();
  const { data } = useRemovedLists();
  const { restoreList, restoreItems } = useListChanges();
  const lists = data?.lists ?? [];
  const items = data?.items ?? [];
  const count = lists.length + items.length;
  useEffect(() => {
    onCount(count);
  }, [count, onCount]);
  return (
    <>
      {lists.map((list) => (
        <RemovedRow
          key={list.id}
          title={list.name}
          detail={t("lists.removed.list", { n: list.item_count })}
          removedAt={list.deleted_at}
          pending={restoreList.isPending && restoreList.variables.listId === list.id}
          onPutBack={() => {
            restoreList.mutate({ listId: list.id });
          }}
        />
      ))}
      {items.map((item) => (
        <RemovedRow
          key={item.id}
          title={item.text}
          detail={item.list_name}
          removedAt={item.deleted_at}
          pending={restoreItems.isPending && restoreItems.variables.ids.includes(item.id)}
          onPutBack={() => {
            restoreItems.mutate({ listId: item.list_id, ids: [item.id] });
          }}
        />
      ))}
    </>
  );
}
