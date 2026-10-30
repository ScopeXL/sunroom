import { useEffect } from "react";

import { useT } from "../../lib/lang";
import { RemovedRow } from "../settings/RecentlyRemoved";
import { useChoreChanges, useRemovedChores } from "./data";

/** Chores removed in the last 7 days, in Recently removed (UX §4). */
export function RemovedChoreRows({ onCount }: { onCount: (count: number) => void }) {
  const t = useT();
  const { data: removed = [] } = useRemovedChores();
  const { restoreChore } = useChoreChanges();
  useEffect(() => {
    onCount(removed.length);
  }, [removed.length, onCount]);
  return (
    <>
      {removed.map((chore) => (
        <RemovedRow
          key={chore.id}
          title={chore.title}
          detail={t("tasks.removed.detail")}
          removedAt={chore.deleted_at}
          pending={restoreChore.isPending && restoreChore.variables.choreId === chore.id}
          onPutBack={() => {
            restoreChore.mutate({ choreId: chore.id });
          }}
        />
      ))}
    </>
  );
}
