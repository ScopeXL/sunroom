import { TriangleAlert } from "lucide-react";
import { useState } from "react";

import { useT } from "../../lib/lang";
import { AttentionSheet } from "./AttentionSheet";
import { useProblems } from "./data";

/** A phone's Today, under its header (ADR 0034): a quiet pill while something needs a parent,
 * opening the same list as the wall's icon. Nothing at all while all is well. */
export function AttentionPill() {
  const t = useT();
  const { data: problems = [] } = useProblems();
  const [open, setOpen] = useState(false);
  if (!problems.length) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
        className="press inline-flex min-h-11 items-center gap-2 self-start rounded-full border-2 border-line bg-surface px-4 text-secondary font-semibold text-ink-soft"
      >
        <TriangleAlert aria-hidden="true" className="size-5" />
        {t("problems.pill.label", { n: problems.length })}
      </button>
      <AttentionSheet
        open={open}
        problems={problems}
        onClose={() => {
          setOpen(false);
        }}
      />
    </>
  );
}
