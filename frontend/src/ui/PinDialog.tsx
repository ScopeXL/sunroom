import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Delete } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, unwrap } from "../api/client";
import { qk } from "../api/keys";
import { finishPinRequest, pinRequest } from "../lib/parent";
import { fetchSession } from "../lib/session";
import { useStore } from "../lib/store";
import { useT } from "../lib/lang";
import { Button } from "./Button";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"] as const;

/**
 * The parent PIN pad (UX §4): dots for each digit, a 3 × 4 pad of 112 × 88 keys, Cancel, and
 * how to recover a forgotten PIN. It tries as soon as the PIN's length is typed; a wrong PIN
 * shakes the dots once; too many tries counts down until the next one.
 */
export function PinDialog() {
  const request = useStore(pinRequest);
  const ref = useRef<HTMLDialogElement>(null);
  const open = request !== null;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      dialog.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="pin-title"
      tabIndex={-1}
      onCancel={(event) => {
        event.preventDefault();
        finishPinRequest(false);
      }}
      className="rise-in m-auto rounded-panel border-0 bg-surface p-8 text-ink backdrop:bg-scrim focus-visible:outline-none"
    >
      {open ? <PinPad key={String(request.reason)} reason={request.reason} /> : null}
    </dialog>
  );
}

function PinPad({ reason }: { reason: string | null }) {
  const queryClient = useQueryClient();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const length = session?.pin_length ?? 4;
  const [digits, setDigits] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [shaking, setShaking] = useState(0);
  const [waitUntil, setWaitUntil] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (waitUntil === null) return;
    const timer = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= waitUntil) {
        setWaitUntil(null);
        setMessage(null);
      }
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [waitUntil]);

  const t = useT();
  const verify = useMutation({
    mutationFn: async (pin: string) =>
      unwrap(await api.POST("/api/auth/pin/verify", { body: { pin } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.session() });
      finishPinRequest(true);
    },
    onError: (error) => {
      setDigits("");
      if (error instanceof ApiError && error.status === 429) {
        setWaitUntil(Date.now() + (error.retryAfter ?? 60) * 1000);
        setMessage(t("ui.pin.too_many.error"));
      } else {
        setShaking((n) => n + 1);
        setMessage(error instanceof ApiError ? error.message : t("ui.pin.wrong.error"));
      }
    },
  });

  const waiting = waitUntil !== null;
  const press = (key: (typeof KEYS)[number]) => {
    if (waiting || verify.isPending) return;
    if (key === "back") {
      setDigits((value) => value.slice(0, -1));
      return;
    }
    const next = (digits + key).slice(0, length);
    setDigits(next);
    setMessage(null);
    if (next.length === length) verify.mutate(next);
  };

  const secondsLeft = waitUntil ? Math.max(0, Math.ceil((waitUntil - now) / 1000)) : 0;
  const countdown = `${String(Math.floor(secondsLeft / 60))}:${String(secondsLeft % 60).padStart(2, "0")}`;
  return (
    <div className="flex w-[400px] max-w-full flex-col items-center gap-6">
      {reason ? <p className="text-center text-d-secondary text-ink-soft">{reason}</p> : null}
      <h2 id="pin-title" className="text-d-title font-bold">
        {t("ui.pin.title")}
      </h2>
      <div
        key={shaking}
        className={shaking ? "shake flex gap-4" : "flex gap-4"}
        role="img"
        aria-label={t("ui.pin.dots.aria", { entered: digits.length, length })}
      >
        {Array.from({ length }, (_, index) => (
          <span
            key={index}
            className={`size-5 rounded-full border-2 border-ink ${index < digits.length ? "bg-ink" : ""}`}
          />
        ))}
      </div>
      <p role="alert" className="min-h-8 text-center text-d-secondary font-semibold text-alert">
        {waiting ? t("ui.pin.wait.error", { time: countdown }) : message}
      </p>
      <div className="grid grid-cols-3 gap-3">
        {KEYS.map((key, index) =>
          key === "" ? (
            <span key={index} />
          ) : (
            <button
              key={index}
              type="button"
              disabled={waiting || verify.isPending}
              aria-label={key === "back" ? t("ui.pin.delete.aria") : key}
              onClick={() => {
                press(key);
              }}
              className="press flex h-22 w-28 items-center justify-center rounded-button-d bg-wall text-d-pin font-semibold disabled:opacity-50"
            >
              {key === "back" ? <Delete aria-hidden="true" className="size-9" /> : key}
            </button>
          ),
        )}
      </div>
      <Button
        variant="secondary"
        block
        onClick={() => {
          finishPinRequest(false);
        }}
      >
        {t("app.action.cancel")}
      </Button>
      <p className="max-w-sm text-center text-d-caption text-ink-soft">{t("ui.pin.forgot")}</p>
    </div>
  );
}
