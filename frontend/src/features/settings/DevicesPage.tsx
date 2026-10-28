import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Laptop, Monitor, Smartphone, Tablet, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import type { components } from "../../api/schema";
import { signedOutHere } from "../../lib/live";
import { asParent } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { ListRow } from "../../ui/ListRow";
import { useShell } from "../../ui/shell";
import { AddDeviceSheet } from "./AddDeviceSheet";
import { PairDisplaySheet } from "./PairDisplaySheet";
import { RenameScreenSheet } from "./RenameScreenSheet";
import { Group, Text } from "./parts";

type Device = components["schemas"]["DeviceOut"];

function lastUsed(device: Device): string {
  const days = Math.floor((Date.now() - new Date(device.last_seen_at).getTime()) / 86_400_000);
  if (days <= 0) return "last used today";
  if (days === 1) return "last used yesterday";
  return `last used ${String(days)} days ago`;
}

/** What each device is (the server's `form`, from the label it signed in with: ADR 0032). */
const ICONS: Record<Device["form"], LucideIcon> = {
  screen: Monitor,
  phone: Smartphone,
  tablet: Tablet,
  computer: Laptop,
};
const WORDS: Record<Exclude<Device["form"], "screen">, string> = {
  phone: "Phone",
  tablet: "Tablet",
  computer: "Computer",
};

function signOutLabel(device: Device): string {
  if (device.form === "screen") return device.is_current ? "Unpair This Screen" : "Unpair";
  return device.is_current ? `Sign Out of This ${WORDS[device.form]}` : "Sign Out";
}

/**
 * Settings → Devices (UX §4, ADR 0032): the paired screens on top, then every signed-in phone,
 * tablet and computer, each with an icon for what it is. A phone or a computer pairs a screen
 * from here; the screen itself doesn't offer to.
 */
export function DevicesPage() {
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const { data: devices = [], error } = useQuery({
    queryKey: qk.devices(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/auth/devices"))),
  });
  const [adding, setAdding] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [renaming, setRenaming] = useState<Device | null>(null);
  const onTheScreen = session?.device_kind === "kiosk";
  const refresh = () => queryClient.invalidateQueries({ queryKey: qk.devices() });

  const signOut = useMutation({
    mutationFn: (device: Device) =>
      asParent(async () => {
        const result = await api.DELETE("/api/auth/devices/{device_id}", {
          params: { path: { device_id: device.id } },
        });
        if (!result.response.ok) unwrap(result);
        return device;
      }),
    onSuccess: async (device) => {
      // The server cleared this device's cookie with it: straight to sign in (or the pair code).
      if (device.is_current) {
        signedOutHere();
        return;
      }
      await refresh();
      showToast(
        device.kind === "kiosk" ? `Unpaired ${device.label}` : `Signed out ${device.label}`,
      );
    },
  });
  const kidPhone = useMutation({
    mutationFn: ({ device, kid }: { device: Device; kid: boolean }) =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/auth/devices/{device_id}", {
            params: { path: { device_id: device.id } },
            body: { is_kid_device: kid },
          }),
        ),
      ),
    onSuccess: refresh,
  });

  const screens = devices.filter((device) => device.kind === "kiosk");
  const phones = devices.filter((device) => device.kind === "phone");
  const problem = error ?? signOut.error ?? kidPhone.error;

  const row = (device: Device) => {
    const Icon = ICONS[device.form];
    const icon = (
      <Icon
        aria-hidden="true"
        data-form={device.form}
        className={`shrink-0 ${display ? "size-9" : "size-6"}`}
      />
    );
    const title = `${device.label}${device.is_current ? " (this one)" : ""}`;
    const about = [
      device.member_name ? `Used by ${device.member_name}` : null,
      device.is_kid_device ? "a child’s device" : null,
      lastUsed(device),
    ]
      .filter(Boolean)
      .join(", ");
    return (
      <div
        key={device.id}
        className={`flex flex-wrap items-center gap-4 ${display ? "min-h-20 py-3" : "min-h-16 py-2"}`}
      >
        {device.kind === "kiosk" ? (
          // A paired screen's name opens Rename Screen (ADR 0042), a row with its chevron; its
          // Unpair stays beside it.
          <div className="min-w-0 flex-1 basis-56">
            <ListRow
              label={`Rename ${device.label}`}
              leading={icon}
              title={title}
              subtitle={about}
              onClick={() => {
                setRenaming(device);
              }}
            />
          </div>
        ) : (
          <>
            {icon}
            <div className="flex min-w-0 flex-1 basis-56 flex-col">
              <span className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
                {title}
              </span>
              <span
                className={
                  display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"
                }
              >
                {about}
              </span>
            </div>
          </>
        )}
        {device.kind === "phone" && session?.has_pin ? (
          <Button
            variant="secondary"
            aria-pressed={device.is_kid_device}
            onClick={() => {
              kidPhone.mutate({ device, kid: !device.is_kid_device });
            }}
          >
            {device.is_kid_device ? "Not a Child’s Device" : "Child’s Device"}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => {
            signOut.mutate(device);
          }}
        >
          {signOutLabel(device)}
        </Button>
      </div>
    );
  };

  return (
    <>
      <Group title="Paired Screens">
        {screens.length === 0 ? (
          <div className="py-4">
            <Text soft>
              No screen paired yet. Open Sunroom on the screen you want to pair and type its code
              here.
            </Text>
          </div>
        ) : (
          screens.map(row)
        )}
        {!onTheScreen ? (
          <div className={display ? "py-5" : "py-4"}>
            <Button
              variant="secondary"
              onClick={() => {
                setPairing(true);
              }}
            >
              Pair a Display
            </Button>
          </div>
        ) : null}
      </Group>
      <Group
        title="Signed-in Devices"
        note={session?.has_pin ? undefined : "Set a parent PIN in Family to mark a child’s device."}
      >
        {phones.map(row)}
        <div className={display ? "py-5" : "py-4"}>
          <Button
            variant="secondary"
            onClick={() => {
              setAdding(true);
            }}
          >
            Add a Device
          </Button>
        </div>
      </Group>
      {problem ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(problem)}
        </p>
      ) : null}
      <RenameScreenSheet
        device={renaming}
        onClose={() => {
          setRenaming(null);
        }}
      />
      <AddDeviceSheet
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
      <PairDisplaySheet
        open={pairing}
        onClose={() => {
          setPairing(false);
        }}
      />
    </>
  );
}
