import { useState } from "react";

import { useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { useShell } from "../../ui/shell";
import { AddAccountSheet } from "./AddAccount";
import { useAccounts } from "./data";

/** First run, step 6 (UX §6): Apple, Google, holidays or a calendar address; each flow comes
 * back here, listing what was added. */
export function SetupCalendars({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { data: accounts = [] } = useAccounts();
  // On the wall screen when it sets Sunroom up itself (ADR 0039), at its sizes.
  const text = useShell() === "display" ? "text-d-body" : "text-body";
  return (
    <>
      <p className={`${text} text-ink-soft`}>{t("sync.setup.intro")}</p>
      {accounts.length ? (
        <ul aria-label={t("sync.setup.added.aria")} className="flex flex-col gap-1">
          {accounts.map((account) => (
            <li key={account.id} className={`${text} font-semibold`}>
              {account.label}
            </li>
          ))}
        </ul>
      ) : null}
      <Button
        variant={accounts.length ? "secondary" : "primary"}
        block
        onClick={() => {
          setOpen(true);
        }}
      >
        {accounts.length ? t("sync.setup.add_another.action") : t("sync.setup.add.action")}
      </Button>
      <Button variant={accounts.length ? "primary" : "quiet"} block onClick={onDone}>
        {accounts.length ? t("app.action.next") : t("sync.setup.skip.action")}
      </Button>
      <AddAccountSheet
        open={open}
        onClose={() => {
          setOpen(false);
        }}
      />
    </>
  );
}
