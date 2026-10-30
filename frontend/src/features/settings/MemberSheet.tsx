import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { useMembers, type Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { uploadPicture } from "../../lib/upload";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { ColorPicker, usedBy } from "../../ui/ColorPicker";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { ROLE_WORDS } from "./AddPersonRow";

type Color = Member["color"];

/**
 * Edit a person (UX §4 Settings → Family): name, parent or child, color (the ones nobody else
 * has first), birthday and photo.
 * Removing someone asks first, because a toast's Undo isn't enough for a whole person; their
 * history stays (they're archived, and Put back is in Family).
 */
export function MemberSheet({ member, onClose }: { member: Member | null; onClose: () => void }) {
  const t = useT();
  return (
    <Sheet
      open={member !== null}
      title={
        member
          ? t("settings.family.member.title", { name: member.name })
          : t("settings.family.member.blank.title")
      }
      onClose={onClose}
    >
      {member ? <MemberForm key={member.id} member={member} onClose={onClose} /> : null}
    </Sheet>
  );
}

function MemberForm({ member, onClose }: { member: Member; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  // A photo comes from a signed-in device; a paired screen has no files, so it shows the photo row
  // only to remove a photo (ADR 0028, 0034).
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const kiosk = session?.device_kind === "kiosk";
  const queryClient = useQueryClient();
  const { data: members = [] } = useMembers();
  // The color radios' group name, unique among the pickers on screen.
  const colorGroup = useId();
  const [name, setName] = useState(member.name);
  const [role, setRole] = useState<Member["role"]>(member.role);
  const [color, setColor] = useState<Color>(member.color);
  const [birthday, setBirthday] = useState(member.birthday ?? "");
  const [confirming, setConfirming] = useState(false);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["members"] });
    await queryClient.invalidateQueries({ queryKey: ["session"] });
  };

  const save = useMutation({
    mutationFn: () =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/members/{member_id}", {
            params: { path: { member_id: member.id } },
            body: { name: name.trim(), role, color, birthday: birthday || null },
          }),
        ),
      ),
    onSuccess: async () => {
      await refresh();
      showToast(t("settings.saved.toast"));
      onClose();
    },
  });

  const remove = useMutation({
    mutationFn: () =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/members/{member_id}/archive", {
            params: { path: { member_id: member.id } },
          }),
        ),
      ),
    onSuccess: async () => {
      await refresh();
      showToast(t("settings.family.member.removed.toast", { name: member.name }), {
        label: t("app.action.undo"),
        onAction: () => {
          void api
            .POST("/api/members/{member_id}/restore", {
              params: { path: { member_id: member.id } },
            })
            .then(refresh);
        },
      });
      onClose();
    },
  });

  const photo = useMutation({
    mutationFn: (file: File) =>
      asParent(() => uploadPicture<Member>(`/api/members/${member.id}/avatar`, "PUT", file, 1024)),
    onSuccess: refresh,
  });

  const removePhoto = useMutation({
    mutationFn: () =>
      asParent(async () =>
        unwrap(
          await api.DELETE("/api/members/{member_id}/avatar", {
            params: { path: { member_id: member.id } },
          }),
        ),
      ),
    onSuccess: refresh,
  });

  if (confirming) {
    return (
      <div className="flex flex-col gap-4">
        <p className={display ? "text-d-body" : "text-body"}>
          {t("settings.family.member.remove.question", { name: member.name })}
        </p>
        <Button
          variant="danger"
          block
          pending={remove.isPending}
          onClick={() => {
            remove.mutate();
          }}
        >
          {t("settings.family.member.remove.action", { name: member.name })}
        </Button>
        <Button
          variant="secondary"
          block
          onClick={() => {
            setConfirming(false);
          }}
        >
          {t("settings.family.member.keep.action", { name: member.name })}
        </Button>
      </div>
    );
  }

  const error = save.error ?? photo.error ?? removePhoto.error ?? remove.error;
  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) save.mutate();
      }}
    >
      <TextField
        label={t("settings.family.member.name.label")}
        value={name}
        maxLength={40}
        autoComplete="off"
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <Segmented
        label={t("settings.family.role.label")}
        value={role}
        onChange={setRole}
        options={[
          { value: "parent", label: t(ROLE_WORDS.parent) },
          { value: "kid", label: t(ROLE_WORDS.kid) },
        ]}
      />
      <ColorPicker
        name={colorGroup}
        value={color}
        onChange={setColor}
        used={usedBy(members, member.id)}
        initial={(name.trim() || member.name).charAt(0).toUpperCase()}
      />
      <TextField
        label={t("settings.family.member.birthday.label")}
        type="date"
        value={birthday}
        hint={t("settings.family.member.birthday.hint")}
        onChange={(event) => {
          setBirthday(event.target.value);
        }}
      />
      {kiosk && !member.avatar_url ? null : (
        <div className="flex items-center gap-4">
          <Avatar member={{ name: member.name, color, avatar_url: member.avatar_url }} size="lg" />
          {kiosk ? null : (
            <label
              className={`press inline-flex cursor-pointer items-center border-2 border-line bg-surface font-semibold has-focus-visible:outline-[3px] has-focus-visible:outline-offset-2 has-focus-visible:outline-ink ${
                display
                  ? "min-h-tap rounded-button-d px-7 text-d-body"
                  : "min-h-11 rounded-button px-4 text-body"
              }`}
            >
              {member.avatar_url
                ? t("settings.family.member.photo.change.action")
                : t("settings.family.member.photo.add.action")}
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) photo.mutate(file);
                }}
              />
            </label>
          )}
          {member.avatar_url ? (
            <Button
              variant="quiet"
              onClick={() => {
                removePhoto.mutate();
              }}
            >
              {t("settings.family.member.photo.remove.action")}
            </Button>
          ) : null}
        </div>
      )}
      {error ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(error)}
        </p>
      ) : null}
      <Button type="submit" block pending={save.isPending} disabled={!name.trim()}>
        {t("app.action.save_changes")}
      </Button>
      <Button
        variant="quiet-danger"
        block
        onClick={() => {
          setConfirming(true);
        }}
      >
        {t("settings.family.member.remove.action", { name: member.name })}
      </Button>
    </form>
  );
}
