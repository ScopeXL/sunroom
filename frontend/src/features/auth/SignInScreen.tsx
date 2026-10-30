import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { useId, useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { normalizeCode } from "../../lib/joinCode";
import { useT } from "../../lib/lang";
import { rememberSignedIn } from "../../lib/session";
import { Button } from "../../ui/Button";
import { Brand } from "../../ui/Brand";
import { useJoinWithCode } from "./useJoin";

function PasswordForm({ onUseCode }: { onUseCode: () => void }) {
  const t = useT();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputId = useId();
  const errorId = useId();

  const signIn = useMutation({
    mutationFn: async (value: string) =>
      unwrap(await api.POST("/api/auth/login", { body: { password: value } })),
    onSuccess: async (session) => {
      rememberSignedIn(true);
      queryClient.setQueryData(qk.session(), session);
      await navigate({ to: session.member ? "/" : "/who" });
    },
    onError: (failure) => {
      setError(errorMessage(failure));
    },
  });

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        signIn.mutate(password);
      }}
    >
      <label htmlFor={inputId} className="text-body font-semibold">
        {t("auth.sign_in.password.label")}
      </label>
      <div className="flex gap-2">
        <input
          id={inputId}
          type={visible ? "text" : "password"}
          autoComplete="current-password"
          autoCapitalize="none"
          spellCheck={false}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
          aria-describedby={errorId}
          aria-invalid={error ? true : undefined}
          className="min-h-12 min-w-0 flex-1 rounded-button border-2 border-line bg-surface px-4 text-body"
        />
        <Button
          variant="secondary"
          icon
          aria-label={
            visible ? t("auth.sign_in.password.hide.aria") : t("auth.sign_in.password.show.aria")
          }
          aria-pressed={visible}
          onClick={() => {
            setVisible((v) => !v);
          }}
        >
          {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </Button>
      </div>
      <p id={errorId} role="alert" className="min-h-7 text-secondary font-semibold text-alert">
        {error}
      </p>
      <Button type="submit" block pending={signIn.isPending} disabled={password.length === 0}>
        {signIn.isPending ? t("auth.sign_in.pending.action") : t("auth.sign_in.action")}
      </Button>
      <p className="mt-2 text-secondary text-ink-soft">{t("auth.sign_in.password.hint")}</p>
      <Button variant="quiet" className="-ml-5 self-start" onClick={onUseCode}>
        {t("auth.sign_in.code.action")}
      </Button>
    </form>
  );
}

function CodeForm({ onUsePassword }: { onUsePassword: () => void }) {
  const t = useT();
  const [code, setCode] = useState("");
  const join = useJoinWithCode();
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();
  const valid = normalizeCode(code);

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) join.mutate(valid);
      }}
    >
      <label htmlFor={inputId} className="text-body font-semibold">
        {t("auth.sign_in.code.label")}
      </label>
      <input
        id={inputId}
        value={code}
        maxLength={10}
        autoComplete="one-time-code"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        onChange={(event) => {
          setCode(event.target.value);
        }}
        aria-describedby={`${hintId} ${errorId}`}
        aria-invalid={join.isError ? true : undefined}
        className="min-h-12 rounded-button border-2 border-line bg-surface px-4 text-title font-bold tracking-widest uppercase"
      />
      <p id={hintId} className="text-secondary text-ink-soft">
        {t("auth.sign_in.code.hint")}
      </p>
      <p id={errorId} role="alert" className="min-h-7 text-secondary font-semibold text-alert">
        {join.isError ? errorMessage(join.error) : null}
      </p>
      <Button type="submit" block pending={join.isPending} disabled={!valid}>
        {join.isPending ? t("auth.sign_in.pending.action") : t("auth.sign_in.action")}
      </Button>
      <Button variant="quiet" className="-ml-5 self-start" onClick={onUsePassword}>
        {t("auth.sign_in.password.action")}
      </Button>
    </form>
  );
}

export function SignInScreen() {
  const [mode, setMode] = useState<"password" | "code">("password");
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="mb-10">
        <Brand size="stacked" heading />
      </div>
      {mode === "password" ? (
        <PasswordForm
          onUseCode={() => {
            setMode("code");
          }}
        />
      ) : (
        <CodeForm
          onUsePassword={() => {
            setMode("password");
          }}
        />
      )}
    </main>
  );
}
