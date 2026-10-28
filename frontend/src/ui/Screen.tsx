import { useCanGoBack, useNavigate, useRouter } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";

import { ActionBar } from "./ActionBar";

/**
 * A phone screen (UX §5): the title, an optional Back, content on the wall color, and actions in
 * the bottom bar above the tabs, in the thumb zone. A `corner` control sits at the title's end
 * (Settings' Discord, ADR 0042).
 */
export function Screen({
  title,
  back,
  corner,
  children,
  actions,
}: {
  title: string;
  /** Where Back goes when there's no history to return to. */
  back?: string;
  corner?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <main
      className={`mx-auto w-full max-w-xl px-4 pt-[calc(env(safe-area-inset-top)+16px)] ${
        actions ? "pb-56" : "pb-32"
      }`}
    >
      {back ? <BackButton to={back} /> : null}
      {corner ? (
        <div className="mt-2 mb-5 flex items-center justify-between gap-4">
          <h1 className="min-w-0 text-title font-bold">{title}</h1>
          {corner}
        </div>
      ) : (
        <h1 className="mt-2 mb-5 text-title font-bold">{title}</h1>
      )}
      {children}
      {actions ? <ActionBar>{actions}</ActionBar> : null}
    </main>
  );
}

export function BackButton({ to }: { to: string }) {
  const router = useRouter();
  const navigate = useNavigate();
  const canGoBack = useCanGoBack();
  return (
    <button
      type="button"
      onClick={() => {
        if (canGoBack) router.history.back();
        else void navigate({ to });
      }}
      className="press -ml-2 inline-flex min-h-11 items-center gap-1 rounded-button pr-3 pl-1 text-body font-semibold"
    >
      <ChevronLeft aria-hidden="true" />
      Back
    </button>
  );
}

/** A titled group of rows on a surface card. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-7">
      <h2 className="mb-2 text-row font-bold">{title}</h2>
      <div className="rounded-chip border border-line bg-surface px-4">{children}</div>
    </section>
  );
}
