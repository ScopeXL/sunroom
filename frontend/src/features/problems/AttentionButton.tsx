import { TriangleAlert } from "lucide-react";
import { useState } from "react";

import { useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { AttentionSheet } from "./AttentionSheet";
import { useProblems } from "./data";

/**
 * The wall's header, at its right end beside the live-updates icon (ADR 0034): drawn only while
 * something needs a parent, as that icon is only while the stream is in trouble. A tap lists
 * what's wrong.
 */
export function AttentionButton() {
  const t = useT();
  const { data: problems = [] } = useProblems();
  const [open, setOpen] = useState(false);
  if (!problems.length) return null;
  return (
    <>
      <Button
        variant="quiet"
        icon
        aria-label={t("problems.button.aria", { n: problems.length })}
        onClick={() => {
          setOpen(true);
        }}
      >
        <TriangleAlert aria-hidden="true" className="size-8 text-ink-soft" />
      </Button>
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
