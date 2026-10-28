import { Check, type LucideIcon } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { swallowFollowingClick } from "../lib/idle";

/** What a menu's button needs, handed to whoever draws it. */
export interface MenuTrigger {
  ref: RefObject<HTMLButtonElement | null>;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
  onClick: () => void;
}

/** Close the menu a row is in and give focus back to its button. */
const MenuClose = createContext<() => void>(() => undefined);

const ROWS = "[role=menuitemradio], [role=menuitemcheckbox]";
const ROW =
  "press-row flex min-h-tap w-full items-center gap-3 rounded-button-d px-4 text-left text-d-body font-semibold";

/**
 * A button that opens a short menu under itself (the header's View and Filter, UX §3, ADR 0029,
 * 0030). No library and no `<dialog>`: a `role="menu"` box, with the keyboard a menu owes.
 * Opening puts focus on the checked row; the arrows, Home and End walk the rows; Escape and Tab
 * close it and give focus back to the button.
 *
 * A press anywhere else closes it and does nothing more: the tap is the menu's, so a tap on the
 * board never also opens Add. (No backdrop element: the header is a size container, which
 * contains fixed boxes, and one in the page's own layer would cover the menu.)
 *
 * A radio row ends the choosing and closes the menu; a checkbox row leaves it open for the next.
 */
export function Menu({
  label,
  trigger,
  className = "min-w-72",
  children,
}: {
  /** The menu's own name: "View", "Filter". */
  label: string;
  trigger: (props: MenuTrigger, open: boolean) => ReactNode;
  /** The box's width, when its rows want more than a word's (the View menu's drawings). */
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const rows = box.current?.querySelectorAll<HTMLElement>(ROWS);
    (box.current?.querySelector<HTMLElement>("[aria-checked=true]") ?? rows?.[0])?.focus();
    const outside = (event: PointerEvent) => {
      if (!(event.target instanceof Node) || box.current?.contains(event.target)) return;
      swallowFollowingClick();
      setOpen(false);
    };
    document.addEventListener("pointerdown", outside, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
    };
  }, [open]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    if (event.key === "Escape") {
      event.stopPropagation();
      close(true);
      return;
    }
    if (event.key === "Tab") {
      close(true);
      return;
    }
    const rows = Array.from(box.current?.querySelectorAll<HTMLElement>(ROWS) ?? []);
    const at = rows.findIndex((row) => row === document.activeElement);
    const to =
      event.key === "ArrowDown"
        ? (at + 1) % rows.length
        : event.key === "ArrowUp"
          ? (at - 1 + rows.length) % rows.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? rows.length - 1
              : -1;
    if (to < 0) return;
    event.preventDefault();
    rows[to]?.focus();
  };

  return (
    <div ref={box} className="relative" onKeyDown={onKeyDown}>
      {trigger(
        {
          ref: button,
          "aria-haspopup": "menu",
          "aria-expanded": open,
          "aria-controls": open ? menuId : undefined,
          onClick: () => {
            setOpen(!open);
          },
        },
        open,
      )}
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          data-segmented=""
          className={`rise-in absolute top-full right-0 z-50 mt-2 flex max-h-[70dvh] flex-col gap-1 overflow-y-auto rounded-panel border-2 border-line bg-surface p-2 shadow-[0_8px_32px_rgb(0_0_0/0.18)] ${className}`}
        >
          <MenuClose.Provider
            value={() => {
              close(true);
            }}
          >
            {children}
          </MenuClose.Provider>
        </div>
      ) : null}
    </div>
  );
}

/** Rows under a quiet word ("People"): a named group, so a screen reader says what the rows
 * are. The word isn't a row: the arrows pass it by. */
export function MenuGroup({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="flex flex-col gap-1">
      <p id={id} className="px-4 pt-2 text-d-caption font-semibold text-ink-soft">
        {label}
      </p>
      {children}
    </div>
  );
}

/**
 * One of several, only one chosen. The chosen row fills with ink (the views); with `check` it
 * shows a check at its end instead, to sit among checkbox rows (Filter's Everyone). A row can
 * show a `drawing` in place of its icon and a `detail` line under its name (the View menu, ADR
 * 0042): it is 88 px tall then, named by its name alone, the line read after it. A drawing draws
 * in the row's own color, so it reads on a chosen row's ink too.
 */
export function MenuRadio({
  checked,
  onChoose,
  icon: Icon,
  check = false,
  drawing,
  detail,
  children,
}: {
  checked: boolean;
  onChoose: () => void;
  icon?: LucideIcon;
  check?: boolean;
  drawing?: ReactNode;
  detail?: string;
  children: ReactNode;
}) {
  const close = useContext(MenuClose);
  const nameId = useId();
  const detailId = useId();
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={checked}
      aria-labelledby={detail ? nameId : undefined}
      aria-describedby={detail ? detailId : undefined}
      onClick={() => {
        onChoose();
        close();
      }}
      className={`${ROW} ${detail ? "min-h-22 gap-4 py-2" : ""} ${check ? "aria-checked:bg-wall" : "aria-checked:bg-ink aria-checked:text-on-ink"}`}
    >
      {drawing ? (
        <span aria-hidden="true" className="shrink-0">
          {drawing}
        </span>
      ) : Icon ? (
        <Icon aria-hidden="true" className="size-8 shrink-0" />
      ) : null}
      {detail ? (
        <span className="flex min-w-0 flex-col">
          <span id={nameId}>{children}</span>
          <span id={detailId} className="text-d-secondary font-normal">
            {detail}
          </span>
        </span>
      ) : (
        children
      )}
      {check ? <Mark shown={checked} /> : null}
    </button>
  );
}

/** One of several, any number chosen: a chosen row shows a check at its end, and the menu
 * stays open for the next one. */
export function MenuCheck({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={checked}
      onClick={() => {
        onChange(!checked);
      }}
      className={`${ROW} aria-checked:bg-wall`}
    >
      {children}
      <Mark shown={checked} />
    </button>
  );
}

// Always there, so a row is one width checked or not.
function Mark({ shown }: { shown: boolean }) {
  return (
    <Check
      aria-hidden="true"
      className={`ml-auto size-8 shrink-0 ${shown ? "" : "invisible"}`}
      strokeWidth={2.5}
    />
  );
}
