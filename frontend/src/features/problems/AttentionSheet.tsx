import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { qk } from "../../api/keys";
import { tSaid, useT } from "../../lib/lang";
import { askForPin } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { useMinute } from "../../lib/time";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { sinceWords, usePageTitles, type Problem } from "./data";

/**
 * Needs Attention (ADR 0034): each problem as a sentence, when it started, a parent's quiet
 * detail, and a button to the Settings page that fixes it. On a paired screen that button asks
 * the PIN first, as the rail's gear does.
 */
export function AttentionSheet({
  open,
  problems,
  onClose,
}: {
  open: boolean;
  problems: readonly Problem[];
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const navigate = useNavigate();
  const now = useMinute();
  const titleOf = usePageTitles();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const go = async (page: string) => {
    if (session?.device_kind === "kiosk" && !session.is_parent && !(await askForPin())) return;
    onClose();
    await navigate({ to: "/settings/$page", params: { page } });
  };
  return (
    <Sheet
      open={open}
      title={t("problems.title")}
      onClose={onClose}
      footer={
        <Button block variant="secondary" onClick={onClose}>
          {t("app.action.done")}
        </Button>
      }
    >
      <ul className="flex flex-col divide-y divide-line">
        {problems.map((problem) => {
          const page = titleOf(problem.page);
          return (
            <li key={problem.id} className={`flex flex-col gap-1 ${display ? "py-5" : "py-4"}`}>
              <p className={`${display ? "text-d-body" : "text-body"} font-semibold`}>
                {tSaid(problem.title, problem.key, problem.params)}
              </p>
              {problem.since ? <p className={soft}>{sinceWords(problem.since, now)}</p> : null}
              {problem.detail ? <p className={soft}>{problem.detail}</p> : null}
              {problem.page && page ? (
                <div className="mt-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void go(problem.page ?? "");
                    }}
                  >
                    {t("problems.open.action", { page })}
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Sheet>
  );
}
