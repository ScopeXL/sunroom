import { useState } from "react";

import { ApiError, errorMessage } from "../../api/client";
import { usePlugins } from "../../lib/household";
import { useT } from "../../lib/lang";
import { showToast } from "../../lib/toast";
import { Button } from "../../ui/Button";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { usePluginSettings } from "../settings/PluginSettingsForm";

/** The settings group this module draws itself, so the generic Features form leaves its fields
 * out. */
export const GOOGLE_GROUP = "Sign in with Google";
const MASK = "***";
/** A saved secret in its field: dots, the same in every language. */
const DOTS = "••••••••";

/** Whether Google's app keys are saved: the ID as it is, the secret only ever as a mask. */
export function useGoogleKeys(): { savedId: string; hasSecret: boolean; ready: boolean } {
  const { data: plugins = [] } = usePlugins();
  const settings = plugins.find((plugin) => plugin.id === "calendar_sync")?.settings ?? {};
  const savedId = typeof settings.google_client_id === "string" ? settings.google_client_id : "";
  const hasSecret = settings.google_client_secret === MASK;
  return { savedId, hasSecret, ready: savedId !== "" && hasSecret };
}

/**
 * Google's app keys, where they're used (ADR 0030): in the Sign in with Google step of Add an
 * account, and in the sheet of an account that signed in that way, so they can be changed
 * without starting over. Nothing else needs them (the secret address and the helper's key file
 * don't), which is why they left the Features page.
 *
 * With no keys: the two fields and one button. With keys: "Keys saved", Change keys (the ID to
 * edit, the secret never shown again) and, in the step, Remove keys: not in an account's sheet,
 * where taking the keys away would stop that account. The fields keep their own Save: half a
 * key shouldn't save itself.
 */
export function GoogleKeys({
  firstSave: given,
  removable = true,
}: {
  /** What the button says while there are no keys yet: Save Keys, unless it's said otherwise. */
  firstSave?: string;
  /** Offer Remove keys. Not beside an account that signs in with them. */
  removable?: boolean;
}) {
  const t = useT();
  const firstSave = given ?? t("sync.keys.save.action");
  const display = useShell() === "display";
  const { savedId, hasSecret, ready } = useGoogleKeys();
  const save = usePluginSettings("calendar_sync");
  const [changing, setChanging] = useState(false);
  const body = display ? "text-d-body" : "text-body";
  if (!ready || changing) {
    return (
      <KeysForm
        savedId={savedId}
        hasSecret={hasSecret}
        submit={ready ? t("sync.keys.save.action") : firstSave}
        primary={!ready}
        onDone={() => {
          setChanging(false);
        }}
        onCancel={
          ready
            ? () => {
                setChanging(false);
              }
            : undefined
        }
      />
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <p className={`${body} font-semibold`}>{t("sync.keys.saved.label")}</p>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          onClick={() => {
            setChanging(true);
          }}
        >
          {t("sync.keys.change.action")}
        </Button>
        {removable ? (
          <Button
            variant="quiet-danger"
            pending={save.isPending}
            onClick={() => {
              // An empty secret clears it; the mask would keep it.
              save.mutate(
                { google_client_id: "", google_client_secret: "" },
                {
                  onSuccess: () => {
                    showToast(t("sync.keys.removed.toast"));
                  },
                },
              );
            }}
          >
            {t("sync.keys.remove.action")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function KeysForm({
  savedId,
  hasSecret,
  submit,
  primary,
  onDone,
  onCancel,
}: {
  savedId: string;
  hasSecret: boolean;
  submit: string;
  /** The step's main button (no keys yet); changing saved keys is a side errand. */
  primary: boolean;
  onDone: () => void;
  onCancel: (() => void) | undefined;
}) {
  const t = useT();
  const display = useShell() === "display";
  const save = usePluginSettings("calendar_sync");
  const [id, setId] = useState(savedId);
  const [secret, setSecret] = useState("");
  // A new secret, or the one already saved (sent back masked, which keeps it).
  const complete = id.trim() !== "" && (secret !== "" || hasSecret);
  const problems = save.error instanceof ApiError ? save.error.problems : [];
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        // Inside another sheet's form this must not submit that one too.
        event.stopPropagation();
        if (!complete) return;
        save.mutate(
          { google_client_id: id.trim(), google_client_secret: secret || MASK },
          {
            onSuccess: () => {
              showToast(t("sync.keys.saved.toast"));
              onDone();
            },
          },
        );
      }}
    >
      <TextField
        label={t("sync.keys.id.label")}
        value={id}
        maxLength={200}
        autoComplete="off"
        autoCapitalize="none"
        onChange={(event) => {
          setId(event.target.value);
        }}
      />
      <TextField
        label={t("sync.keys.secret.label")}
        type="password"
        layout="password"
        value={secret}
        maxLength={200}
        autoComplete="off"
        hint={hasSecret ? t("sync.keys.secret.saved.hint") : t("sync.keys.secret.hint")}
        placeholder={hasSecret ? DOTS : undefined}
        onChange={(event) => {
          setSecret(event.target.value);
        }}
      />
      {save.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {problems.length ? problems.join(" ") : errorMessage(save.error)}
        </p>
      ) : null}
      <div className={`flex flex-col ${display ? "gap-3" : "gap-2"}`}>
        <Button
          type="submit"
          variant={primary ? "primary" : "secondary"}
          block
          pending={save.isPending}
          disabled={!complete}
        >
          {submit}
        </Button>
        {onCancel ? (
          <Button variant="quiet" block onClick={onCancel}>
            {t("app.action.cancel")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
