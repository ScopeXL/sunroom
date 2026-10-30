import {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useT } from "../lib/lang";
import { Button } from "./Button";
import { useShell } from "./shell";
import { SheetToastsContext, type SheetToasts } from "./sheetToasts";
import { ToastAnchor } from "./ToastAnchor";

/**
 * Keeps showing what it last showed while `frozen`. Callers clear their state when a sheet
 * closes, so without this a closing sheet would slide away empty.
 */
const Frozen = memo(
  function Frozen({ children }: { children: ReactNode; frozen: boolean }) {
    return children;
  },
  (_previous, next) => next.frozen,
);

/** Back to a plain open dialog: no longer sliding away. */
function stopClosing(dialog: HTMLDialogElement): void {
  delete dialog.dataset.closing;
  dialog.inert = false;
  dialog.removeAttribute("aria-hidden");
}

/**
 * A sheet on the native <dialog> (UX §3): a bottom sheet on phones, a centred panel on large
 * screens. The browser handles focus, Escape and the inert background, and nothing injects
 * styles (Dinner Bell's ADR 0023). It closes with its visible Close button; Escape and a tap on
 * the backdrop are only shortcuts.
 *
 * It slides up when it opens and back down when it closes (styles/motion.css). While
 * it slides away it stays modal, marked `data-closing`, inert and hidden from screen readers,
 * still showing what it showed; the script closes it once its animation ends. Opening it again
 * meanwhile just keeps it open.
 */
export function Sheet({
  open,
  title,
  onClose,
  children,
  footer,
  step,
  oneLineTitle = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** For a sheet with steps: when it changes, the new step starts at the top, with focus. */
  step?: string;
  /** The title never takes a second line: one too long for it is cut with an ellipsis (the
   * forecast's place). Off, a long title wraps, as an event's should. */
  oneLineTitle?: boolean;
}) {
  const t = useT();
  const display = useShell() === "display";
  const ref = useRef<HTMLDialogElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // Where the last press started: a tap on the backdrop closes the sheet only if it started
  // there. A press on a field raises the wall's keyboard, the sheet moves up above it, and the
  // release can land on the backdrop: that click belongs to the field, not the backdrop.
  const pressedBackdrop = useRef(false);
  const shownStep = useRef(step);
  const titleId = useId();
  // Sliding away: `open` went false, but the dialog is still on screen until its animation ends.
  const [closing, setClosing] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    setClosing(!open);
  }
  // A pinned button bar in the body takes the toasts above itself (ui/sheetToasts).
  const [pinned, setPinned] = useState(0);
  const pin = useCallback(() => {
    setPinned((count) => count + 1);
    return () => {
      setPinned((count) => count - 1);
    };
  }, []);
  const toasts = useMemo<SheetToasts>(() => ({ open, pin }), [open, pin]);

  useEffect(() => {
    if (step === shownStep.current) return;
    shownStep.current = step;
    const body = bodyRef.current;
    if (!body) return;
    // What had focus (the choice just tapped) is gone with the old step.
    body.scrollTop = 0;
    body.focus({ preventScroll: true });
  }, [step]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      stopClosing(dialog);
      if (!dialog.open) {
        dialog.showModal();
        // The sheet itself takes focus, not its first button, so Close doesn't look pressed.
        dialog.focus();
      }
      return;
    }
    if (!dialog.open) return;
    dialog.dataset.closing = "";
    dialog.inert = true;
    dialog.setAttribute("aria-hidden", "true");
    let reopened = false;
    void Promise.allSettled(dialog.getAnimations().map((animation) => animation.finished)).then(
      () => {
        if (reopened) return;
        stopClosing(dialog);
        dialog.close();
        setClosing(false);
      },
    );
    return () => {
      reopened = true;
    };
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="sheet"
      tabIndex={-1}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === ref.current;
      }}
      onClick={(event) => {
        if (event.target === ref.current && pressedBackdrop.current) onClose();
      }}
    >
      {open || closing ? (
        <div className="flex max-h-[min(88dvh,calc(100dvh_-_var(--osk-h,0px)_-_48px))] flex-col">
          <Frozen frozen={!open}>
            <header
              className={`flex items-center justify-between gap-3 border-b border-line ${
                display ? "py-2 pr-3 pl-6" : "py-1.5 pr-2 pl-4"
              }`}
            >
              {/* The heading is the flex item that gives way: Close's least width is its word. */}
              <h2
                id={titleId}
                className={`${display ? "text-d-title font-bold" : "text-row font-bold"} ${
                  oneLineTitle ? "min-w-0 truncate" : ""
                }`}
              >
                {title}
              </h2>
              <Button variant="quiet" onClick={onClose}>
                {t("app.action.close")}
              </Button>
            </header>
          </Frozen>
          <div className="relative flex min-h-0 flex-1 flex-col">
            <SheetToastsContext.Provider value={toasts}>
              <Frozen frozen={!open}>
                {/* Focusable, so a keyboard can scroll it even when nothing inside takes focus. */}
                <div
                  ref={bodyRef}
                  role="region"
                  aria-labelledby={titleId}
                  tabIndex={0}
                  className={`flex-1 overflow-y-auto ${display ? "px-6 py-6" : "px-4 py-4"}`}
                >
                  {children}
                </div>
              </Frozen>
            </SheetToastsContext.Provider>
            {/* Toasts raised while the sheet is open (and their Undo) show here, since the page
                behind it can't be tapped. They float over the bottom of the body, above the
                footer's buttons and taking no room, so the sheet never moves as one comes or goes;
                a pinned button bar in the body takes them above itself instead (ADR 0032). Gone as
                soon as the sheet starts closing: its toasts go back to the page. */}
            {open && pinned === 0 ? (
              <ToastAnchor className="absolute inset-x-0 bottom-0 pb-3" />
            ) : null}
          </div>
          <Frozen frozen={!open}>
            {footer ? (
              <footer className={`border-t border-line ${display ? "px-6 py-4" : "px-4 py-3"}`}>
                {footer}
              </footer>
            ) : null}
          </Frozen>
        </div>
      ) : null}
    </dialog>
  );
}
