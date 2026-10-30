import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { colorWord } from "../../lib/colors";
import { useMembers, useSettings, useUpdateSettings, type Member } from "../../lib/household";
import { useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { ListRow } from "../../ui/ListRow";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";
import { AddPersonRow, ROLE_WORDS, type RoleChoice } from "./AddPersonRow";
import { MemberSheet } from "./MemberSheet";
import { Group, Row, Text } from "./parts";

/** Settings → Family (UX §4): the people, the parent PIN and Child-safe editing. */
export function FamilyPage() {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { data: archived = [] } = useMembers(true);
  const [changing, setChanging] = useState<Member | null>(null);
  const queryClient = useQueryClient();
  const removed = archived.filter((member) => member.archived);

  const restore = useMutation({
    mutationFn: (member: Member) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/members/{member_id}/restore", {
            params: { path: { member_id: member.id } },
          }),
        ),
      ),
    onSuccess: async (member) => {
      await queryClient.invalidateQueries({ queryKey: ["members"] });
      showToast(t("settings.family.put_back.toast", { name: member.name }));
    },
  });

  return (
    <>
      <Group title={t("settings.family.people.title")}>
        {members.length === 0 ? (
          <div className="py-4">
            <Text soft>{t("settings.family.people.empty")}</Text>
          </div>
        ) : null}
        {members.map((member) => (
          <ListRow
            key={member.id}
            label={t("settings.family.edit.aria", { name: member.name })}
            leading={<Avatar member={member} size={display ? "lg" : "md"} />}
            title={member.name}
            subtitle={t("settings.family.person.subtitle", {
              role: t(ROLE_WORDS[member.role]),
              color: colorWord(member.color),
            })}
            onClick={() => {
              setChanging(member);
            }}
          />
        ))}
        <AddPerson />
      </Group>
      {removed.length > 0 ? (
        <Group title={t("settings.family.removed.title")}>
          {removed.map((member) => (
            <Row key={member.id} label={member.name}>
              <Button
                variant="secondary"
                pending={restore.isPending}
                onClick={() => {
                  restore.mutate(member);
                }}
              >
                {t("app.action.put_back")}
              </Button>
            </Row>
          ))}
        </Group>
      ) : null}
      <ParentPin />
      <MemberSheet
        member={changing}
        onClose={() => {
          setChanging(null);
        }}
      />
    </>
  );
}

function AddPerson() {
  const t = useT();
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: ({ name, role }: { name: string; role: RoleChoice }) =>
      asParent(async () => unwrap(await api.POST("/api/members", { body: { name, role } }))),
    onSuccess: async (member) => {
      await queryClient.invalidateQueries({ queryKey: ["members"] });
      await queryClient.invalidateQueries({ queryKey: qk.session() });
      showToast(t("settings.family.added.toast", { name: member.name }));
    },
  });
  return (
    <div className={display ? "py-6" : "py-4"}>
      <AddPersonRow
        label={t("settings.family.add.label")}
        placeholder={t("settings.family.add.placeholder")}
        action={t("app.action.add")}
        pending={add.isPending}
        error={add.isError ? errorMessage(add.error) : null}
        onAdd={(name, role) => add.mutateAsync({ name, role })}
      />
    </div>
  );
}

function ParentPin() {
  const t = useT();
  const display = useShell() === "display";
  const queryClient = useQueryClient();
  const { data: settings } = useSettings();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const updateSettings = useUpdateSettings();
  const [editing, setEditing] = useState(false);
  const [pin, setPin] = useState("");
  const [current, setCurrent] = useState("");
  const hasPin = settings?.has_pin ?? false;
  // Where the PIN is what made this device a parent (the wall screen, a kid's phone), changing
  // it asks for the current one (PLAN §12.3).
  const needsCurrent =
    hasPin && (session?.device_kind === "kiosk" || session?.is_kid_device === true);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.settings() });
    await queryClient.invalidateQueries({ queryKey: qk.session() });
  };
  const save = useMutation({
    mutationFn: () =>
      asParent(async () => {
        const result = await api.PUT("/api/auth/pin", {
          body: needsCurrent ? { pin, current_pin: current } : { pin },
        });
        if (!result.response.ok) unwrap(result);
      }),
    onSuccess: async () => {
      setEditing(false);
      setPin("");
      setCurrent("");
      await refresh();
      showToast(t("settings.family.pin.saved.toast"));
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      asParent(async () => {
        const result = await api.DELETE("/api/auth/pin");
        if (!result.response.ok) unwrap(result);
      }),
    onSuccess: async () => {
      await refresh();
      showToast(t("settings.family.pin.removed.toast"));
    },
  });
  const valid = /^\d{4,6}$/.test(pin) && (!needsCurrent || /^\d{4,6}$/.test(current));

  return (
    <Group
      title={t("settings.family.pin.title")}
      note={hasPin ? t("settings.family.pin.on.note") : t("settings.family.pin.off.note")}
    >
      {editing ? (
        <form
          className={`flex flex-col gap-4 ${display ? "py-6" : "py-4"}`}
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) save.mutate();
          }}
        >
          {needsCurrent ? (
            <TextField
              label={t("settings.family.pin.current.label")}
              type="password"
              inputMode="numeric"
              layout="numeric"
              autoComplete="off"
              maxLength={6}
              value={current}
              onChange={(event) => {
                setCurrent(event.target.value.replace(/\D/g, ""));
              }}
            />
          ) : null}
          <TextField
            label={t("settings.family.pin.new.label")}
            type="password"
            inputMode="numeric"
            layout="numeric"
            autoComplete="off"
            maxLength={6}
            value={pin}
            error={save.isError ? errorMessage(save.error) : null}
            onChange={(event) => {
              setPin(event.target.value.replace(/\D/g, ""));
            }}
          />
          <div className="flex gap-3">
            <Button type="submit" pending={save.isPending} disabled={!valid}>
              {t("settings.family.pin.set.action")}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setEditing(false);
              }}
            >
              {t("app.action.cancel")}
            </Button>
          </div>
        </form>
      ) : (
        <Row
          label={hasPin ? t("settings.family.pin.on.label") : t("settings.family.pin.off.label")}
        >
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(true);
            }}
          >
            {hasPin
              ? t("settings.family.pin.change.action")
              : t("settings.family.pin.first.action")}
          </Button>
          {hasPin ? (
            <Button
              variant="quiet-danger"
              pending={remove.isPending}
              onClick={() => {
                remove.mutate();
              }}
            >
              {t("settings.family.pin.remove.action")}
            </Button>
          ) : null}
        </Row>
      )}
      <Switch
        label={t("settings.family.kid_safe.label")}
        hint={t("settings.family.kid_safe.hint")}
        checked={settings?.kid_safe_editing ?? true}
        onChange={(value) => {
          updateSettings.mutate({ kid_safe_editing: value });
        }}
      />
    </Group>
  );
}
