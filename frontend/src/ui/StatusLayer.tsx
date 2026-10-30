import { WifiOff } from "lucide-react";
import { useEffect } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";

import { connection } from "../lib/connection";
import { formatTime } from "../lib/dates";
import { useT } from "../lib/lang";
import { useStore } from "../lib/store";

const UPDATE_CHECK_MS = 60 * 60 * 1000;

/**
 * The quiet connection pill (UX §8): never an error wall. A phone says "Offline · showing what
 * we had"; the wall screen says when it last heard from the server.
 */
export function OfflinePill({ display = false }: { display?: boolean }) {
  const t = useT();
  const { showOffline, lastReachableAt } = useStore(connection);
  if (!showOffline) return <div role="status" aria-live="polite" className="sr-only" />;
  const text =
    display && lastReachableAt
      ? t("ui.offline.unreachable", { time: formatTime(new Date(lastReachableAt)) })
      : t("ui.offline.phone");
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-[calc(env(safe-area-inset-top)+8px)] z-30 flex justify-center print:hidden"
    >
      <span
        className={`inline-flex items-center gap-2 rounded-full bg-ink font-semibold text-on-ink ${
          display ? "px-5 py-3 text-d-secondary" : "px-4 py-2 text-secondary"
        }`}
      >
        <WifiOff aria-hidden="true" size={display ? 24 : 18} />
        {text}
      </span>
    </div>
  );
}

/** Whether a new version is waiting (the service worker installed it), and how to take it. */
export function useAppUpdate(): { ready: boolean; apply: () => void } {
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW();

  // Hourly, and whenever the page comes back into view, while it's visible. One timer per mount,
  // cleared with it: the wall remounts its shell on every room change (ADR 0034).
  useEffect(() => {
    const check = () => {
      if (document.visibilityState === "visible" && "serviceWorker" in navigator) {
        navigator.serviceWorker
          .getRegistration()
          .then((registration) => registration?.update())
          .catch(() => undefined); // offline, or the server restarting: the next check tries again
      }
    };
    const timer = setInterval(check, UPDATE_CHECK_MS);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);

  return {
    ready: needRefresh,
    apply: () => {
      void updateServiceWorker(true);
    },
  };
}

/** "New version · Refresh" on phones. The wall screen restarts itself at night (shell/). */
export function UpdatePrompt() {
  const t = useT();
  const { ready, apply } = useAppUpdate();
  if (!ready) return null;
  return (
    <div className="fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+var(--tabbar-h)+12px)] z-30 flex justify-center px-4 print:hidden lg:bottom-6">
      <div className="rise-in flex items-center gap-3 rounded-button bg-ink py-2 pr-2 pl-4 text-on-ink [--focus-ring:var(--wall)]">
        <span className="text-secondary font-semibold">{t("ui.update.ready")}</span>
        <button
          type="button"
          className="press min-h-11 rounded-button bg-wall px-4 text-secondary font-bold text-ink"
          onClick={apply}
        >
          {t("ui.update.refresh.action")}
        </button>
      </div>
    </div>
  );
}

// The toasts live in their own module, which the screen's own pages load without the PWA.
export { ToastRegion } from "./ToastRegion";
