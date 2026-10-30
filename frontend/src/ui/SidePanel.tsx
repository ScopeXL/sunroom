import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { useSettings } from "../lib/household";
import { useT } from "../lib/lang";
import { Button } from "./Button";
import { useShell } from "./shell";
import { Sheet } from "./Sheet";

interface PanelProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** The wall's panel goes back to its top when this changes (Add: the kind of thing), as it
   * does when it opens: a new form shouldn't start scrolled to where the last one was left. */
  scrollKey?: string | undefined;
}

/** The event sheet, Add and the editor: a side panel on the wall screen, a sheet on a phone. */
export function SidePanel({ scrollKey, ...props }: PanelProps) {
  return useShell() === "display" ? (
    <WallPanel {...props} scrollKey={scrollKey} />
  ) : (
    <Sheet {...props} />
  );
}

/**
 * The wall screen's side panel (UX §4): 640 px over the Today panel in landscape, two-thirds of
 * the height from the bottom in portrait. It isn't modal: the board stays live behind it, so Add
 * can take a tap on a day. Close is always visible; Escape closes it too. It slides in and out
 * (styles/motion.css, `[data-panel]`) and keeps showing what it showed while it slides away.
 */
function WallPanel({ open, title, onClose, children, footer, scrollKey }: PanelProps) {
  const t = useT();
  const { data: settings } = useSettings();
  const titleId = useId();
  const ref = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState({ title, children, footer });
  const [closing, setClosing] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    setClosing(!open);
  }
  if (open && (shown.title !== title || shown.children !== children || shown.footer !== footer)) {
    setShown({ title, children, footer });
  }

  // It opens at its top, whatever was scrolled to the last time it was open, or in the panel
  // it replaces (an event's sheet, then Change): the node is the same one. A new form inside it
  // (Add: another kind) starts at its top too.
  useEffect(() => {
    if (open && body.current) body.current.scrollTop = 0;
  }, [open, title, scrollKey]);

  // Focus moves in when it opens and back to where it was when it closes.
  useEffect(() => {
    if (!open) return;
    returnTo.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) {
      const target = node.querySelector<HTMLElement>("[autofocus], [data-autofocus]") ?? node;
      target.focus({ preventScroll: true });
    }
    return () => {
      returnTo.current?.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open && !closing) return null;
  const left = settings?.display_rail_side === "right";
  return (
    <section
      ref={ref}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-panel=""
      data-state={open ? "open" : "closing"}
      inert={!open}
      onAnimationEnd={() => {
        if (!open) setClosing(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
      className={`fixed z-40 flex flex-col border-line bg-surface shadow-[0_8px_32px_rgb(0_0_0/0.18)] outline-none portrait:inset-x-0 portrait:bottom-0 portrait:h-[66dvh] portrait:rounded-t-panel portrait:border-t landscape:inset-y-0 landscape:w-[40rem] ${
        left ? "landscape:left-0 landscape:border-r" : "landscape:right-0 landscape:border-l"
      }`}
    >
      <header className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
        <h2 id={titleId} className="min-w-0 text-d-title font-bold">
          {shown.title}
        </h2>
        <Button variant="quiet" onClick={onClose}>
          {t("app.action.close")}
        </Button>
      </header>
      {/* Focusable, so a keyboard can scroll it even when nothing inside takes focus. */}
      <div
        ref={body}
        tabIndex={0}
        className={`min-h-0 flex-1 overflow-y-auto px-6 py-5 ${
          shown.footer
            ? ""
            : "scroll-pb-[calc(var(--osk-h,0px)+8rem)] pb-[calc(var(--osk-h,0px)+20px)]"
        }`}
      >
        {shown.children}
      </div>
      {shown.footer ? (
        <footer className="border-t border-line px-6 py-4 pb-[calc(var(--osk-h,0px)+16px)]">
          {shown.footer}
        </footer>
      ) : null}
    </section>
  );
}
