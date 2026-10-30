import { useT } from "../lib/lang";

/**
 * Grey shapes where a screen's content is about to appear (UX §8), so nothing jumps when
 * it arrives. They wait 300 ms before showing (`.skeleton-wait`), so a quick load never flashes
 * them. A screen reader hears the label instead.
 */
const WIDTHS = ["w-2/3", "w-1/2", "w-3/4", "w-2/5"] as const;

function Lines({ index }: { index: number }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <div className={`skeleton-shape h-4 rounded ${WIDTHS[index % WIDTHS.length] ?? "w-1/2"}`} />
      <div className="skeleton-shape h-3 w-1/3 rounded" />
    </div>
  );
}

export function Skeleton({
  rows = 3,
  shape = "rows",
  label,
}: {
  rows?: number;
  /** rows: a photo and two lines each (lists); lines: text only; cards: the meal library. */
  shape?: "rows" | "lines" | "cards";
  label?: string;
}) {
  const t = useT();
  const indexes = Array.from({ length: rows }, (_, index) => index);
  return (
    <div role="status" className="skeleton-wait">
      <span className="sr-only">{label ?? t("ui.loading")}</span>
      {shape === "cards" ? (
        <div aria-hidden="true" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {indexes.map((index) => (
            <div key={index} className="overflow-hidden rounded-chip border border-line bg-surface">
              <div className="skeleton-shape aspect-[4/3] w-full" />
              <div className="flex p-3">
                <Lines index={index} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div
          aria-hidden="true"
          className="overflow-hidden rounded-chip border border-line bg-surface"
        >
          {indexes.map((index) => (
            <div
              key={index}
              className="flex min-h-14 items-center gap-3 border-b border-line px-3 py-3 last:border-b-0"
            >
              {shape === "rows" ? (
                <div className="skeleton-shape size-12 shrink-0 rounded-chip" />
              ) : null}
              <Lines index={index} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
