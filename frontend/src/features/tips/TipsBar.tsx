import { ChevronRight, Lightbulb } from "lucide-react";
import { useEffect } from "react";

import { usePlugins, useSettings } from "../../lib/household";
import { tRich, useT } from "../../lib/lang";
import { createStore, useStore } from "../../lib/store";
import { Button } from "../../ui/Button";
import { useShell } from "../../ui/shell";
import { pickTip, tipFits, TIPS, type Tip } from "./tips";

const EVERY_MS = 30 * 60_000;

/** The tip on show, kept outside React so a new one can come from a timer or a tap. */
const shownTip = createStore<Tip | null>(null);

function nextTip(enabled: ReadonlySet<string>): void {
  shownTip.set((last) => pickTip(TIPS, enabled, last?.id ?? null));
}

/**
 * Tips under the board (UX §3, ADR 0028): with Settings → Display → Show tips on, a 56 px strip
 * along the bottom of the wall's shell (a laptop's too, never a phone's) shows one thing Sunroom
 * can do, a new one every half hour and on Next tip. It's never an error or a nag. While it
 * shows, toasts sit above it (styles/tokens.css, `--tips-h`).
 */
export function TipsBar() {
  const t = useT();
  const display = useShell() === "display";
  const { data: settings } = useSettings();
  const { data: plugins = [] } = usePlugins();
  const on = plugins
    .filter((plugin) => plugin.enabled)
    .map((plugin) => plugin.id)
    .sort()
    .join(" ");
  const tip = useStore(shownTip);
  const shown = display && settings?.show_tips === true;

  useEffect(() => {
    if (!shown) return;
    const enabled = new Set(on.split(" "));
    const current = shownTip.get();
    if (!current || !tipFits(current, enabled)) nextTip(enabled);
    const timer = setInterval(() => {
      nextTip(enabled);
    }, EVERY_MS);
    return () => {
      clearInterval(timer);
    };
  }, [shown, on]);

  if (!shown || !tip) return null;
  return (
    <div
      data-tips=""
      className="flex h-tap shrink-0 items-center gap-3 border-t border-line bg-surface pl-6"
    >
      <Lightbulb aria-hidden="true" className="size-6 shrink-0 text-ink-soft" />
      <p className="min-w-0 flex-1 truncate text-d-secondary">
        {/* "Tip:" for a screen reader only, before the tip's words. */}
        {tRich("tips.bar.text", {
          hidden: (words) => <span className="sr-only">{words}</span>,
          tip: t(tip.text),
        })}
      </p>
      <Button
        variant="quiet"
        icon
        aria-label={t("tips.bar.next.aria")}
        onClick={() => {
          nextTip(new Set(on.split(" ")));
        }}
      >
        <ChevronRight aria-hidden="true" className="size-8 text-ink-soft" />
      </Button>
    </div>
  );
}
