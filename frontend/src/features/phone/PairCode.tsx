/**
 * Pairing a wall screen by the code it shows (UX §5 "Pair a Display"): the call and the field,
 * shared by More → Pair a Display on a phone and Settings → Devices on a phone or a
 * computer. The screen moves on by itself once it's paired, and asks for its own name.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { t, useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";

export function usePairDisplay() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/auth/kiosk/pair", {
            // The name it's paired with, until the screen's Name This Screen gives it another.
            body: { code, label: t("display.name.default") },
          }),
        ),
      ),
    onSuccess: async (paired) => {
      await queryClient.invalidateQueries({ queryKey: qk.devices() });
      showToast(t("phone.pair.paired.toast", { name: paired.label ?? t("display.name.default") }));
    },
  });
}

export function PairCodeField({
  value,
  error,
  onChange,
}: {
  value: string;
  error: string | null;
  onChange: (value: string) => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  return (
    <TextField
      label={t("phone.pair.code.label")}
      hint={t("phone.pair.code.hint")}
      value={value}
      maxLength={10}
      autoComplete="one-time-code"
      autoCapitalize="characters"
      className={`${display ? "text-d-title" : "text-title"} font-bold tracking-widest uppercase`}
      error={error}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

/** Under the field: what to do when the screen shows no code. */
export function NoCodeYet() {
  const t = useT();
  const display = useShell() === "display";
  return (
    <p className={`${display ? "text-d-secondary" : "text-secondary"} text-ink-soft`}>
      {t("phone.pair.no_code.hint")}
    </p>
  );
}
