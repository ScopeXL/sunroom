/**
 * Pairing a wall screen by the code it shows (UX §5 "Pair a Display"): the call and the field,
 * shared by More → Pair a Display on a phone and Settings → Devices on a phone or a
 * computer. The screen moves on by itself once it's paired, and asks for its own name.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
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
            body: { code, label: "Wall screen" },
          }),
        ),
      ),
    onSuccess: async (paired) => {
      await queryClient.invalidateQueries({ queryKey: qk.devices() });
      showToast(`${paired.label ?? "Wall screen"} paired`);
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
  const display = useShell() === "display";
  return (
    <TextField
      label="The code on the screen"
      hint="The screen shows a code. Type it here."
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
  const display = useShell() === "display";
  return (
    <p className={`${display ? "text-d-secondary" : "text-secondary"} text-ink-soft`}>
      No code? On the screen, open Sunroom. A screen that’s already paired shows the calendar.
    </p>
  );
}
