import { useT, type Key } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import type { Scope } from "./types";

type Verb = "Change" | "Move" | "Remove";

/** The sheet's title for each verb: "Remove Which?". */
const TITLES: Record<Verb, Key> = {
  Change: "calendar.scope.change.title",
  Move: "calendar.scope.move.title",
  Remove: "calendar.scope.remove.title",
};

/**
 * "Change which?" for a repeating event (UX §6): just this one, this and the ones after, or all
 * of them. Remove and Move (and a drop) ask the same three; Undo reverses the whole choice.
 */
export function ScopeChooser({
  open,
  verb,
  title,
  repeatText,
  onChoose,
  onCancel,
}: {
  open: boolean;
  verb: Verb;
  title: string;
  repeatText?: string | null | undefined;
  onChoose: (scope: Scope) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const choice = (scope: Scope, label: string) => (
    <Button
      block
      variant="secondary"
      onClick={() => {
        onChoose(scope);
      }}
    >
      {label}
    </Button>
  );
  return (
    <Sheet open={open} title={t(TITLES[verb])} onClose={onCancel}>
      <div className="flex flex-col gap-4 pb-2">
        <p className={display ? "text-d-body" : "text-body"}>
          {/* Mid-sentence, only the first word drops its capital: "every week on Tue and Thu". */}
          {repeatText
            ? t("calendar.scope.repeats_as", {
                title,
                repeat: `${repeatText.charAt(0).toLowerCase()}${repeatText.slice(1)}`,
              })
            : t("calendar.scope.repeats", { title })}
        </p>
        {choice("this", t("calendar.scope.action.this"))}
        {choice("following", t("calendar.scope.action.following"))}
        {choice("all", t("calendar.scope.action.all"))}
      </div>
    </Sheet>
  );
}
