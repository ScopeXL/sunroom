import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";

import { useRailBlocks } from "../features/usePluginModules";
import { clockSuffix, formatClock, shortDate, zonedParts } from "../lib/dates";
import { useT } from "../lib/lang";
import { useStore } from "../lib/store";
import { useMinute } from "../lib/time";
import { Button } from "../ui/Button";
import { Digits } from "../ui/Digits";
import { LiveStatusButton } from "../ui/LiveStatus";
import { roomHeader } from "./roomHeader";
import { AttentionButton } from "../features/problems/AttentionButton";

/**
 * Today, at the header's left (UX §3): the date (semi-bold), the time at glance size (weight
 * 800, digits in fixed boxes so it never jiggles, AM or PM small and soft), then what the plugins
 * put by the clock (the weather's pill), 24 px apart. The date and the time are text and share
 * one baseline; a plugin's block is an object, centred on the time's line box, which is
 * symmetric about its digits. The block is a tap target tall, so portrait's first row never
 * grows when the weather arrives (ADR 0033; ADR 0032 centred all three, and the date floated
 * 6 px above the line the time stands on).
 */
function HeaderToday() {
  const now = useMinute();
  const day = zonedParts(now).day;
  const time = formatClock(now);
  const suffix = clockSuffix(now);
  const blocks = useRailBlocks();
  return (
    <div className="mr-3 flex min-h-tap shrink-0 items-center gap-x-6 landscape:ml-3">
      <div className="flex items-baseline gap-x-6">
        <p className="text-d-body font-semibold whitespace-nowrap">{shortDate(day)}</p>
        <p className="text-d-glance font-extrabold whitespace-nowrap">
          <Digits value={time} spoken={suffix ? `${time} ${suffix}` : time} />
          {suffix ? (
            <span aria-hidden="true" className="ml-1.5 text-d-secondary font-bold text-ink-soft">
              {suffix}
            </span>
          ) : null}
        </p>
      </div>
      <div className="flex items-center gap-x-6 empty:hidden">
        {blocks.map((Block, index) => (
          <Block key={index} place="header" />
        ))}
      </div>
    </div>
  );
}

/**
 * One of the header's two toggles: the rail's, or the Today panel's (ADR 0030). Each sits at
 * the header's end nearest its panel, and its icon faces that panel: a bar on the panel's side,
 * an arrow that says which way it will go.
 */
function PanelToggle({
  hide,
  show,
  open,
  side,
  onToggle,
}: {
  /** What the button says to a screen reader: "Hide the rail", "Show the Today panel". */
  hide: string;
  show: string;
  open: boolean;
  /** Where its panel is. */
  side: "left" | "right";
  onToggle: () => void;
}) {
  const Icon =
    side === "left"
      ? open
        ? PanelLeftClose
        : PanelLeftOpen
      : open
        ? PanelRightClose
        : PanelRightOpen;
  return (
    <span className="shrink-0 portrait:hidden">
      <Button
        variant="secondary"
        icon
        aria-expanded={open}
        onClick={onToggle}
        aria-label={open ? hide : show}
      >
        <Icon aria-hidden="true" className="size-8" />
      </Button>
    </span>
  );
}

/**
 * The wall's header (UX §3, ADR 0029, 0030): one bar over the board and the Today panel, the
 * full width in portrait. Hide the rail at its start, then today; after a thin rule, the room's
 * own part, handed over through shell/roomHeader (a way back and a title for a page the rail
 * can't name, then its controls); the Today panel's button at its end and, only while something
 * is wrong, the live-updates icon in the corner (connected, the corner is clear and nothing
 * holds its place). No room's name is written here when the rail already says it, and nothing
 * has a second line: the h1 is still there for a screen reader. The two toggles sit at the edge
 * nearest their panels, so in a mirrored shell (the rail on the right) they swap ends. One row
 * from 104rem of its own width (1920 px at Standard); narrower, the room's part takes a second
 * row. Nothing here animates in: it's part of the first paint. Portrait has neither toggle: its
 * rail is a bar that never folds, and its Today band has no button.
 *
 * Spacing (ADR 0030): 24 px at the sides and between today's three things, a 2 px rule with
 * 24 px either side, 16 px between the room's groups, 12 px before the end zone and inside it.
 * As one row it is exactly `--header-h` tall whatever the room puts in it (a bordered group is
 * taller than a button), so its rule always meets the one under the rail's mark.
 */
export function Header({
  panelShown,
  onTogglePanel,
  railCompact,
  railSide,
  onFoldRail,
}: {
  panelShown: boolean;
  onTogglePanel: () => void;
  railCompact: boolean;
  railSide: "left" | "right";
  onFoldRail: (compact: boolean) => void;
}) {
  const t = useT();
  const room = useStore(roomHeader);
  const rail = (
    <PanelToggle
      hide={t("shell.header.rail.hide")}
      show={t("shell.header.rail.show")}
      open={!railCompact}
      side={railSide}
      onToggle={() => {
        onFoldRail(!railCompact);
      }}
    />
  );
  const panel = (
    <PanelToggle
      hide={t("shell.header.panel.hide")}
      show={t("shell.header.panel.show")}
      open={panelShown}
      side={railSide === "left" ? "right" : "left"}
      onToggle={onTogglePanel}
    />
  );
  return (
    <header
      data-header=""
      className="@container/header flex min-h-[var(--header-h)] shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-6 py-2.5 @min-[104rem]/header:py-1"
    >
      {railSide === "left" ? rail : panel}
      <HeaderToday />
      {room ? (
        <div className="order-last flex min-w-0 grow-0 basis-full flex-wrap items-center gap-x-4 gap-y-2 @min-[104rem]/header:order-none @min-[104rem]/header:grow @min-[104rem]/header:basis-0 @min-[104rem]/header:border-l-2 @min-[104rem]/header:border-line @min-[104rem]/header:pl-6">
          {room.back}
          <h1
            className={
              room.visibleTitle
                ? "min-w-0 truncate text-d-title leading-tight font-bold"
                : "sr-only"
            }
          >
            {room.title}
          </h1>
          {/* Said as it appears: what a held chip is waiting for. */}
          <p
            aria-live="polite"
            className={
              room.notice
                ? "flex min-h-tap items-center rounded-full border-2 border-line px-5 text-d-secondary font-semibold whitespace-nowrap"
                : "sr-only"
            }
          >
            {room.notice}
          </p>
          {room.controls}
        </div>
      ) : null}
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {railSide === "left" ? panel : rail}
        <AttentionButton />
        <LiveStatusButton />
      </div>
    </header>
  );
}
