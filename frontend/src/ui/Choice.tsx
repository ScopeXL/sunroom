import { CircleCheck } from "lucide-react";
import { createContext, useContext, useId, useRef, type ReactNode } from "react";

/** The chooseable cards' group: which one is chosen, and how to choose another. */
const ChoiceContext = createContext<{ value: string; choose: (value: string) => void } | null>(
  null,
);

/** Arrow keys in a radio group: the next card, or the one before. */
const STEPS: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/**
 * One of two ways on, as a card beside the other (the screen's Welcome, ADR 0038; the wall's
 * Set Up Sunroom, ADR 0039): its name, a line on what it is, what to know. The wall's sizes only.
 *
 * Two forms. Inside a `ChoiceGroup` with a `value`, the whole card is one radio button of a
 * choice made once, then Continue (Welcome, ADR 0042): chosen, it has an ink border and a check
 * in the sun's color in its corner. Otherwise it's a section with its own button at the foot
 * (`action`), so two cards side by side keep their buttons on one line (Set Up Sunroom, whose
 * second card is a QR code, not a choice).
 */
export function Choice({
  heading,
  lead,
  children,
  action,
  value,
}: {
  heading: string;
  lead: string;
  /** Inside a chooseable card, phrasing only: spans, drawn as blocks. */
  children: ReactNode;
  /** None for a way that has nothing to tap here (a QR code for a phone). */
  action?: ReactNode;
  /** The card's value in its `ChoiceGroup`: the whole card is then the button. */
  value?: string;
}) {
  const id = useId();
  const group = useContext(ChoiceContext);
  if (group && value !== undefined) {
    const chosen = group.value === value;
    return (
      <button
        type="button"
        role="radio"
        aria-checked={chosen}
        aria-labelledby={`${id}-name`}
        aria-describedby={`${id}-more`}
        tabIndex={chosen ? 0 : -1}
        data-choice={value}
        onClick={() => {
          group.choose(value);
        }}
        className={`press relative flex min-w-0 flex-col gap-4 rounded-panel bg-surface text-left ${
          // The chosen border is a pixel wider; its padding a pixel less, so nothing inside moves.
          chosen ? "border-[3px] border-ink p-[calc(1.5rem-1px)]" : "border-2 border-line p-6"
        }`}
      >
        {chosen ? (
          <CircleCheck
            aria-hidden="true"
            className="absolute top-5 right-5 size-10 fill-sun text-on-sun"
          />
        ) : null}
        <span id={`${id}-name`} className="pr-14 text-d-title font-bold">
          {heading}
        </span>
        <span id={`${id}-more`} className="flex flex-col gap-4">
          <span className="text-d-body font-semibold">{lead}</span>
          {children}
        </span>
      </button>
    );
  }
  return (
    <section
      aria-labelledby={id}
      className="flex min-w-0 flex-col gap-4 rounded-panel border border-line bg-surface p-6 text-left"
    >
      <h2 id={id} className="text-d-title font-bold">
        {heading}
      </h2>
      <p className="text-d-body font-semibold">{lead}</p>
      {children}
      {action ? <div className="mt-auto pt-2">{action}</div> : null}
    </section>
  );
}

/**
 * Chooseable `Choice` cards as one radio group, named by the question it answers
 * (`labelledBy`): a tap chooses a card, and the arrow keys move the choice as in any radio group
 * (Home and End to the first and last); only the chosen card is in the tab order.
 */
export function ChoiceGroup({
  labelledBy,
  value,
  onChange,
  className,
  children,
}: {
  labelledBy: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <ChoiceContext.Provider value={{ value, choose: onChange }}>
      <div
        ref={box}
        role="radiogroup"
        aria-labelledby={labelledBy}
        className={className}
        onKeyDown={(event) => {
          const step = STEPS[event.key];
          if (step === undefined && event.key !== "Home" && event.key !== "End") return;
          const cards = [...(box.current?.querySelectorAll<HTMLElement>("[data-choice]") ?? [])];
          if (cards.length === 0) return;
          event.preventDefault();
          const at = cards.findIndex((card) => card.dataset.choice === value);
          const next =
            event.key === "Home"
              ? cards[0]
              : event.key === "End"
                ? cards.at(-1)
                : cards[(at + (step ?? 0) + cards.length) % cards.length];
          const chosen = next?.dataset.choice;
          if (next === undefined || chosen === undefined) return;
          onChange(chosen);
          next.focus();
        }}
      >
        {children}
      </div>
    </ChoiceContext.Provider>
  );
}
