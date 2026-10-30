import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, notSaved, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import type { components } from "../../api/schema";
import { COLORS } from "../../lib/colors";
import { useMembers } from "../../lib/household";
import { tPlugin, useT } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { useSavedFlash } from "../../lib/savedFlash";
import { showToast } from "../../lib/toast";
import { Chip, ChipRow } from "../../ui/Chip";
import { SavedMark } from "../../ui/SavedMark";
import { Segmented } from "../../ui/Segmented";
import { useShell } from "../../ui/shell";
import { Switch } from "../../ui/Switch";
import { TextField } from "../../ui/TextField";

type Field = components["schemas"]["FieldOut"];
type PluginInfo = components["schemas"]["PluginOut"];
type Values = Record<string, unknown>;
/** A saved secret as the server sends it: never the secret itself. */
const MASK = "***";
/** A saved secret as its field shows it. */
const MASK_DOTS = "••••••••";

/** Save a plugin's settings as they change (UX §1 "Undo, drafts, confirmations", ADR 0029):
 * the whole values object goes to the server, what's on screen changes at once, and a refusal
 * puts it back. A 422's problems come back for the form to list; anything else is a toast. */
export function usePluginSettings(pluginId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: Values) =>
      asParent(async () =>
        unwrap(
          await api.PUT("/api/plugins/{plugin_id}/settings", {
            params: { path: { plugin_id: pluginId } },
            body: { values },
          }),
        ),
      ),
    onMutate: async (values) => {
      await queryClient.cancelQueries({ queryKey: qk.plugins() });
      const before = queryClient.getQueryData<PluginInfo[]>(qk.plugins());
      queryClient.setQueryData<PluginInfo[]>(qk.plugins(), (plugins) =>
        plugins?.map((plugin) =>
          plugin.id === pluginId
            ? { ...plugin, settings: { ...plugin.settings, ...values } }
            : plugin,
        ),
      );
      return { before };
    },
    onError: (error, _values, context) => {
      if (context?.before) queryClient.setQueryData(qk.plugins(), context.before);
      const listed = error instanceof ApiError && error.problems.length > 0;
      if (!listed) showToast(notSaved(error));
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.plugins() });
    },
  });
}

/**
 * A plugin's settings, drawn from its spec (PLAN §6.2): the generic form every plugin gets unless
 * it brings its own section. There is no Save button and no draft: switches, choices and chips
 * save the moment they change, and a typed field saves when it's left or on ↵, with a quiet
 * "Saved" under it. The values shown are the server's, so two phones never fight over a form.
 * Secrets are write-only: a set one shows as dots and stays as it is unless typed over.
 * `skipGroups` leaves out the fields a plugin draws itself (Google's keys).
 */
export function PluginSettingsForm({
  pluginId,
  spec,
  values,
  skipGroups = [],
}: {
  pluginId: string;
  spec: Field[];
  values: Values;
  skipGroups?: readonly string[];
}) {
  const display = useShell() === "display";
  const save = usePluginSettings(pluginId);
  const problems = save.error instanceof ApiError ? save.error.problems : [];
  const fields = spec.filter((field) => !skipGroups.includes(field.group));
  /** Save one field; resolves to whether the server took it. */
  const change = async (key: string, value: unknown): Promise<boolean> => {
    try {
      await save.mutateAsync({ ...values, [key]: value });
      return true;
    } catch {
      return false;
    }
  };
  if (fields.length === 0) return null;
  return (
    <div className={`flex flex-col ${display ? "gap-6 py-6" : "gap-4 py-4"}`}>
      {fields.map((field) => (
        <FieldInput
          key={field.key}
          pluginId={pluginId}
          field={field}
          value={values[field.key]}
          onChange={(value) => change(field.key, value)}
        />
      ))}
      {save.isError && problems.length ? (
        <div role="alert" className="font-semibold text-alert">
          <ul className="list-disc pl-6">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** A typed field: its own draft while it has focus, saved when it's left or on ↵ if it changed. */
function TypedField({
  field,
  shown,
  parse,
  onChange,
  ...input
}: {
  field: Field;
  /** The saved value as text. */
  shown: string;
  /** What's typed, as the value to save. */
  parse: (text: string) => unknown;
  onChange: (value: unknown) => Promise<boolean>;
} & Pick<
  React.ComponentProps<typeof TextField>,
  "type" | "layout" | "inputMode" | "maxLength" | "placeholder" | "autoComplete" | "hint" | "label"
>) {
  const [draft, setDraft] = useState<string | null>(null);
  const { saved, flash } = useSavedFlash();
  const commit = () => {
    if (draft === null) return;
    const typed = draft;
    if (typed === shown) {
      setDraft(null);
      return;
    }
    void onChange(parse(typed)).then((ok) => {
      // Kept as typed when the server refused it, so it can be put right.
      if (!ok) return;
      setDraft(null);
      flash();
    });
  };
  return (
    <div className="flex flex-col gap-1">
      <TextField
        strong
        {...input}
        value={draft ?? shown}
        data-setting={field.key}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
      />
      <SavedMark show={saved} />
    </div>
  );
}

function FieldInput({
  pluginId,
  field: spec,
  value,
  onChange,
}: {
  pluginId: string;
  field: Field;
  value: unknown;
  onChange: (value: unknown) => Promise<boolean>;
}) {
  const t = useT();
  const { data: members = [] } = useMembers();
  const display = useShell() === "display";
  // A field's label, help and choices are the plugin's own words: its keys in the page's
  // language, else the server's English (lib/lang's tPlugin). The unit is the server's.
  const said = (path: string, english: string) =>
    tPlugin(pluginId, `settings.${spec.key}.${path}`, english);
  const field: Field = {
    ...spec,
    label: said("label", spec.label),
    help: spec.help ? said("help", spec.help) : spec.help,
    choice_labels: spec.choices
      ? spec.choices.map((choice, index) =>
          said(`choices.${choice}`, spec.choice_labels?.[index] ?? choice),
        )
      : null,
  };
  // A group's name reads like a field's label (ui/TextField): the shell's body size.
  const groupLabel = `${display ? "text-d-body" : "text-body"} font-semibold`;
  const hint = field.help || null;
  const now = (next: unknown) => {
    void onChange(next);
  };
  const text =
    typeof value === "string"
      ? value
      : typeof value === "number" || typeof value === "boolean"
        ? String(value)
        : "";
  switch (field.type) {
    case "bool":
      return (
        <Switch label={field.label} hint={field.help} checked={value === true} onChange={now} />
      );
    case "int":
    case "float":
    case "percent":
      return (
        <TypedField
          field={field}
          label={
            field.unit
              ? t("settings.features.field.unit", { label: field.label, unit: field.unit })
              : field.label
          }
          hint={hint}
          inputMode="decimal"
          layout="numeric"
          shown={text}
          parse={(typed) => (typed === "" ? null : typed)}
          onChange={onChange}
        />
      );
    case "secret":
      return (
        <TypedField
          field={field}
          label={field.label}
          hint={value === MASK ? t("settings.features.field.secret.hint") : hint}
          type="password"
          layout="password"
          autoComplete="off"
          placeholder={value === MASK ? MASK_DOTS : undefined}
          shown=""
          parse={(typed) => typed}
          onChange={onChange}
        />
      );
    case "choice": {
      const choices = field.choices ?? [];
      const labels = field.choice_labels ?? choices;
      // Side by side while the words are short ("Never, 5 min, 15 min, 30 min, 1 hour"): the
      // group wraps onto a second row on a phone. Longer or more of them are chips.
      const words = choices.reduce(
        (sum, choice, index) => sum + (labels[index] ?? choice).length,
        0,
      );
      if (choices.length <= 6 && words <= 40) {
        return (
          <div className="flex flex-col gap-2">
            <span className={groupLabel}>{field.label}</span>
            <Segmented
              label={field.label}
              value={text}
              onChange={now}
              options={choices.map((choice, index) => ({
                value: choice,
                label: labels[index] ?? choice,
              }))}
            />
            {hint ? <FieldHint>{hint}</FieldHint> : null}
          </div>
        );
      }
      return (
        <div className="flex flex-col gap-2">
          <span className={groupLabel}>{field.label}</span>
          <ChipRow label={field.label}>
            {choices.map((choice, index) => (
              <Chip
                key={choice}
                on={text === choice}
                onClick={() => {
                  now(choice);
                }}
              >
                {labels[index] ?? choice}
              </Chip>
            ))}
          </ChipRow>
          {hint ? <FieldHint>{hint}</FieldHint> : null}
        </div>
      );
    }
    case "multichoice": {
      const chosen = Array.isArray(value) ? (value as string[]) : [];
      const choices = field.choices ?? [];
      const labels = field.choice_labels ?? choices;
      return (
        <div className="flex flex-col gap-2">
          <span className={groupLabel}>{field.label}</span>
          <ChipRow label={field.label}>
            {choices.map((choice, index) => (
              <Chip
                key={choice}
                on={chosen.includes(choice)}
                onClick={() => {
                  now(
                    chosen.includes(choice)
                      ? chosen.filter((c) => c !== choice)
                      : [...chosen, choice],
                  );
                }}
              >
                {labels[index] ?? choice}
              </Chip>
            ))}
          </ChipRow>
          {hint ? <FieldHint>{hint}</FieldHint> : null}
        </div>
      );
    }
    case "color":
      return (
        <div className="flex flex-col gap-2">
          <span className={groupLabel}>{field.label}</span>
          <ChipRow label={field.label}>
            {COLORS.map((color) => (
              <Chip
                key={color.value}
                on={text === color.value}
                onClick={() => {
                  now(color.value);
                }}
              >
                {t(color.word)}
              </Chip>
            ))}
          </ChipRow>
        </div>
      );
    case "member":
      return (
        <div className="flex flex-col gap-2">
          <span className={groupLabel}>{field.label}</span>
          <ChipRow label={field.label}>
            {members.map((member) => (
              <Chip
                key={member.id}
                on={text === member.id}
                onClick={() => {
                  now(member.id);
                }}
              >
                {member.name}
              </Chip>
            ))}
          </ChipRow>
        </div>
      );
    case "time":
    case "date":
      return (
        <TypedField
          field={field}
          label={field.label}
          hint={hint}
          type={field.type}
          shown={text}
          parse={(typed) => typed || null}
          onChange={onChange}
        />
      );
    case "text":
    case "json":
      return (
        <TypedField
          field={field}
          label={field.label}
          hint={hint}
          shown={field.type === "json" && typeof value === "object" ? JSON.stringify(value) : text}
          parse={(typed) => typed}
          onChange={onChange}
        />
      );
    default:
      return (
        <TypedField
          field={field}
          label={field.label}
          hint={hint}
          maxLength={field.max_length ?? undefined}
          shown={text}
          parse={(typed) => typed}
          onChange={onChange}
        />
      );
  }
}

function FieldHint({ children }: { children: string }) {
  const display = useShell() === "display";
  return (
    <p className={display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"}>
      {children}
    </p>
  );
}
