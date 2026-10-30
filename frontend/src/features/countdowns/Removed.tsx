import { useEffect } from "react";

import { shortDate } from "../../lib/dates";
import { useT } from "../../lib/lang";
import { RemovedRow } from "../settings/RecentlyRemoved";
import { useCountdownChanges, useRemovedCountdowns } from "./data";

/** Countdowns removed in the last 7 days (and past ones, the day after), in Recently removed. */
export function RemovedCountdownRows({ onCount }: { onCount: (count: number) => void }) {
  const t = useT();
  const { data = [] } = useRemovedCountdowns();
  const { restore } = useCountdownChanges();
  useEffect(() => {
    onCount(data.length);
  }, [data.length, onCount]);
  return (
    <>
      {data.map((countdown) => (
        <RemovedRow
          key={countdown.id}
          title={countdown.title}
          detail={t("countdowns.removed.detail", { day: shortDate(countdown.date) })}
          removedAt={countdown.deleted_at}
          pending={restore.isPending && restore.variables.id === countdown.id}
          onPutBack={() => {
            restore.mutate({ id: countdown.id, title: countdown.title });
          }}
        />
      ))}
    </>
  );
}
