import { Check } from "lucide-react";

import { useT } from "../lib/lang";
import { useShell } from "./shell";

/**
 * The quiet "Saved" under a field that saves itself (lib/savedFlash). The line is always there
 * for screen readers (aria-live, polite) and keeps its height, so nothing under it jumps when
 * the word comes and goes.
 */
export function SavedMark({ show }: { show: boolean }) {
  const t = useT();
  const display = useShell() === "display";
  return (
    <p
      aria-live="polite"
      className={`flex items-center gap-1 text-ink-soft ${
        display ? "min-h-6 text-d-caption" : "min-h-[1.125rem] text-caption"
      }`}
    >
      {show ? (
        <>
          <Check aria-hidden="true" className={display ? "size-5" : "size-4"} />
          {t("ui.saved")}
        </>
      ) : null}
    </p>
  );
}
