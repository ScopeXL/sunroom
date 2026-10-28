import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import type { components } from "../../api/schema";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { Sheet } from "../../ui/Sheet";
import { ScreenNameFields } from "../display/ScreenName";

type Device = components["schemas"]["DeviceOut"];

/**
 * Rename Screen (Settings → Devices, ADR 0042): a paired screen's row opens it, this screen's own
 * too. The same places as Name This Screen and a field holding the current name; Save Changes
 * names it. A signed-in device isn't renamed here: its icon is read from its name.
 */
export function RenameScreenSheet({
  device,
  onClose,
}: {
  /** The screen being renamed; null when the sheet is closed. */
  device: Device | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState(device?.label ?? "");
  // A new screen opened in the sheet starts from its own name.
  const [shown, setShown] = useState(device?.id);
  if (device?.id !== shown) {
    setShown(device?.id);
    setLabel(device?.label ?? "");
  }
  const name = label.trim();
  const save = useMutation({
    mutationFn: (renamed: Device) =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/auth/devices/{device_id}", {
            params: { path: { device_id: renamed.id } },
            body: { label: name },
          }),
        ),
      ),
    onSuccess: async (renamed) => {
      await queryClient.invalidateQueries({ queryKey: qk.devices() });
      if (renamed.is_current) await queryClient.invalidateQueries({ queryKey: qk.session() });
      showToast(`Renamed to ${renamed.label}`);
      onClose();
    },
  });
  return (
    <Sheet open={device !== null} title="Rename Screen" onClose={onClose}>
      <form
        className="flex flex-col items-start gap-6 pb-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (device && name && name !== device.label) save.mutate(device);
        }}
      >
        <ScreenNameFields label={label} onChange={setLabel} field="always" />
        {save.isError ? (
          <p role="alert" className="text-d-secondary font-semibold text-alert">
            {errorMessage(save.error)}
          </p>
        ) : null}
        <Button type="submit" pending={save.isPending} disabled={!name || name === device?.label}>
          Save Changes
        </Button>
      </form>
    </Sheet>
  );
}
