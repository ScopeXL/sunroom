import type { ReactNode } from "react";

import type { BoardView } from "../../lib/displayState";

/*
 * A small drawing of each view for the View menu (ADR 0042): what the board looks like, at a
 * glance, beside the view's name and its line.
 * - Decorative: the row says it all, so each drawing is aria-hidden (the row's span is).
 * - The row's own color (currentColor), lighter or heavier, so a drawing reads on the menu's
 *   surface and on a chosen row's ink alike; the sun's color only for what is "now" (today's
 *   column, today's square), as the board lights it.
 * - Token classes only, no inline style; one 72 × 48 box.
 */

const WIDTH = 72;
const HEIGHT = 48;

function Frame({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={WIDTH}
      height={HEIGHT}
      fill="none"
      className="block"
    >
      <rect
        x="0.75"
        y="0.75"
        width={WIDTH - 1.5}
        height={HEIGHT - 1.5}
        rx="6"
        className="stroke-current opacity-60"
        strokeWidth="1.5"
      />
      {children}
    </svg>
  );
}

/** An event: a short bar in the row's color. */
function Bar({
  x,
  y,
  width,
  height = 4,
}: {
  x: number;
  y: number;
  width: number;
  height?: number;
}) {
  return (
    <rect x={x} y={y} width={width} height={height} rx="1.5" className="fill-current opacity-50" />
  );
}

/** Seven columns from x = 5, each 8 wide and 1.5 apart, with a head; `lit` is today's. */
function SevenColumns({
  lit,
  quiet,
  bars,
}: {
  lit: number;
  /** Yesterday, a shade quieter (Rolling Week). */
  quiet?: number;
  bars: Record<number, number[]>;
}) {
  return (
    <>
      {Array.from({ length: 7 }, (_, column) => {
        const x = 5 + column * 9.5;
        return (
          <g key={column}>
            {column === lit ? (
              <rect x={x - 1} y="4" width="10" height="40" rx="2" className="fill-sun opacity-35" />
            ) : null}
            <rect
              x={x}
              y="6"
              width="8"
              height="3"
              rx="1.5"
              className={
                column === lit
                  ? "fill-sun"
                  : column === quiet
                    ? "fill-current opacity-25"
                    : "fill-current opacity-60"
              }
            />
            {(bars[column] ?? []).map((y) => (
              <Bar key={y} x={x} y={y} width={8} />
            ))}
          </g>
        );
      })}
    </>
  );
}

function WeekArt() {
  return (
    <Frame>
      <SevenColumns
        lit={2}
        bars={{ 0: [14], 1: [14, 22], 2: [14, 28], 4: [18], 5: [14, 22], 6: [30] }}
      />
    </Frame>
  );
}

function RollingArt() {
  return (
    <Frame>
      <SevenColumns
        lit={1}
        quiet={0}
        bars={{ 0: [14], 1: [14, 22], 3: [18], 4: [14, 26], 6: [22] }}
      />
      <circle cx="10" cy="40" r="2" className="fill-sun" />
    </Frame>
  );
}

function DayArt() {
  return (
    <Frame>
      {[14, 22, 30, 38].map((y) => (
        <path key={y} d={`M6 ${y}H66`} className="stroke-current opacity-25" strokeWidth="1" />
      ))}
      <rect x="6" y="5" width="20" height="4" rx="2" className="fill-current opacity-60" />
      <Bar x={14} y={15} width={40} height={6} />
      <Bar x={14} y={31} width={28} height={6} />
    </Frame>
  );
}

function MonthArt() {
  return (
    <Frame>
      {Array.from({ length: 28 }, (_, cell) => {
        const column = cell % 7;
        const row = Math.floor(cell / 7);
        const today = cell === 10;
        return (
          <rect
            key={cell}
            x={5 + column * 9.25}
            y={6 + row * 9.5}
            width="7"
            height="7"
            rx="1.5"
            className={today ? "fill-sun" : "fill-current opacity-30"}
          />
        );
      })}
    </Frame>
  );
}

function PeopleArt() {
  return (
    <Frame>
      {[0, 1, 2, 3].map((column) => {
        const x = 6 + column * 16;
        return (
          <g key={column}>
            <circle cx={x + 6} cy="10" r="4" className="fill-current opacity-60" />
            <Bar x={x} y={19} width={12} />
            {column % 2 === 0 ? <Bar x={x} y={27} width={12} /> : null}
            {column === 1 ? <Bar x={x} y={35} width={12} /> : null}
          </g>
        );
      })}
    </Frame>
  );
}

function TodayArt() {
  return (
    <Frame>
      <rect x="5" y="5" width="62" height="22" rx="3" className="fill-sun opacity-35" />
      <rect x="9" y="9" width="24" height="4" rx="2" className="fill-current opacity-60" />
      <Bar x={9} y={17} width={40} />
      {[0, 1, 2, 3].map((block) => (
        <rect
          key={block}
          x={5 + block * 16}
          y="31"
          width="14"
          height="12"
          rx="2"
          className="fill-current opacity-25"
        />
      ))}
    </Frame>
  );
}

/** Each view's drawing, for its row in the View menu. */
export const VIEW_ART: Record<BoardView, () => ReactNode> = {
  week: WeekArt,
  rolling: RollingArt,
  day: DayArt,
  month: MonthArt,
  people: PeopleArt,
  today: TodayArt,
};
