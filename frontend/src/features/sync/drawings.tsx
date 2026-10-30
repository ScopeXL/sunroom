import { Calendar, Copy, Settings } from "lucide-react";
import type { ReactNode } from "react";

import { useT } from "../../lib/lang";

/*
 * Drawings for the account steps on a phone (docs/UX.md §6 "Connect an Apple calendar",
 * "Connect Google"): a browser window, quiet lines for what doesn't matter, and the one thing to
 * tap filled with the sun color and ringed, named in the step's own words.
 * - Schematic, not a copy of Apple's or Google's pages: no logos, brand colors or people.
 * - Decorative: the step's text says it all, so every drawing is aria-hidden.
 * - Colors come only from token classes, so both themes work; there is no inline style.
 * - One 320 × 152 box, drawn 1:1 at its widest (20rem), so its words are 14 to 17 px there.
 *   Lexend's widths were measured to fit each English word in its box; the words are the pages'
 *   own (`sync.drawing.*` in lang/), so a translation is checked against its box too.
 */

/** What the steps show or say to type, the same in every language. */
const PASSWORD_SHAPE = "xxxx-xxxx-xxxx-xxxx";
const SERVICE_ACCOUNT = "sunroom";

const WIDTH = 320;
const HEIGHT = 152;
/** Where the page starts, under the address bar. */
const TOP = 36;

/** The baseline that centres a line's capitals on `middle` (Lexend's capitals are 0.7 em). */
function baseline(middle: number, size: number): number {
  return middle + size * 0.35;
}

/** A browser window: the address bar (with the address, when the step names one), then the page. */
function Window({ address, children }: { address?: string; children: ReactNode }) {
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={WIDTH}
      height={HEIGHT}
      fill="none"
      aria-hidden="true"
      className="mt-3 block h-auto w-full max-w-80"
    >
      <rect
        x="0.75"
        y="0.75"
        width={WIDTH - 1.5}
        height={HEIGHT - 1.5}
        rx="14"
        className="fill-wall stroke-ink-soft"
        strokeWidth="1.5"
      />
      <path d={`M1.5 ${TOP}H${WIDTH - 1.5}`} className="stroke-line" strokeWidth="1.5" />
      <rect
        x="12"
        y="7"
        width="204"
        height="22"
        rx="11"
        className="fill-surface stroke-line"
        strokeWidth="1.5"
      />
      {address ? (
        <text x="24" y={baseline(18, 14)} fontSize="14" className="fill-ink">
          {address}
        </text>
      ) : (
        <Line x={24} y={15} width={84} />
      )}
      {children}
    </svg>
  );
}

/** Words that don't matter here, as a soft line. */
function Line({ x, y, width }: { x: number; y: number; width: number }) {
  return <rect x={x} y={y} width={width} height="6" rx="3" className="fill-line" />;
}

/** A panel on the page. */
function Card({ x, y, width, height }: { x: number; y: number; width: number; height: number }) {
  return (
    <rect
      x={x}
      y={y}
      width={width}
      height={height}
      rx="10"
      className="fill-surface stroke-line"
      strokeWidth="1.5"
    />
  );
}

/** A box with something typed in it, and the caret after the words (`wide` px of them). */
function Field({
  x,
  y,
  width,
  text,
  wide,
}: {
  x: number;
  y: number;
  width: number;
  text: string;
  wide: number;
}) {
  return (
    <>
      <rect
        x={x}
        y={y}
        width={width}
        height="28"
        rx="8"
        className="fill-surface stroke-ink-soft"
        strokeWidth="1.5"
      />
      <text x={x + 12} y={baseline(y + 14, 15)} fontSize="15" className="fill-ink">
        {text}
      </text>
      <path
        d={`M${x + 16 + wide} ${y + 6}v16`}
        className="stroke-ink"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </>
  );
}

/**
 * The thing to tap: filled with the sun, a ring around it, and its name. A button is a pill; a
 * row or a menu item has softer corners. `children` draws what's inside instead of the name.
 */
function Target({
  x,
  y,
  width,
  label,
  pill = true,
  children,
}: {
  x: number;
  y: number;
  width: number;
  label?: string;
  pill?: boolean;
  children?: ReactNode;
}) {
  const height = 26;
  const radius = pill ? height / 2 : 8;
  return (
    <>
      <rect
        x={x - 4}
        y={y - 4}
        width={width + 8}
        height={height + 8}
        rx={radius + 4}
        className="stroke-sun-ink"
        strokeWidth="2"
      />
      <rect x={x} y={y} width={width} height={height} rx={radius} className="fill-sun" />
      {label ? (
        <text
          x={x + width / 2}
          y={baseline(y + height / 2, 15)}
          fontSize="15"
          fontWeight="600"
          textAnchor="middle"
          className="fill-on-sun"
        >
          {label}
        </text>
      ) : null}
      {children}
    </>
  );
}

/** A plus on the sun, drawn rather than typed so it sits dead centre. */
function Plus({ x, y }: { x: number; y: number }) {
  return (
    <path
      d={`M${x} ${y - 6}v12M${x - 6} ${y}h12`}
      className="stroke-on-sun"
      strokeWidth="2.5"
      strokeLinecap="round"
    />
  );
}

/** Apple, step 1: appleid.apple.com, the two boxes, and Sign in. */
export function AppleSignInArt() {
  const t = useT();
  return (
    <Window address="appleid.apple.com">
      <Card x={84} y={46} width={152} height={26} />
      <Line x={96} y={56} width={76} />
      <Card x={84} y={78} width={152} height={26} />
      <g className="fill-ink-soft">
        {[0, 1, 2, 3, 4, 5].map((dot) => (
          <circle key={dot} cx={98 + dot * 11} cy="91" r="2.75" />
        ))}
      </g>
      <Target x={112} y={112} width={96} label={t("sync.drawing.apple.sign_in")} />
    </Window>
  );
}

/** Apple, step 2: under Sign-In and Security, App-Specific Passwords and its plus, then the name. */
export function AppleNewPasswordArt() {
  const t = useT();
  return (
    <Window>
      <text x="18" y={baseline(49, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.apple.security")}
      </text>
      <rect x="16" y="68" width="288" height="34" rx="10" className="fill-surface" />
      <text x="30" y={baseline(85, 15)} fontSize="15" fontWeight="500" className="fill-ink">
        {t("sync.drawing.apple.passwords")}
      </text>
      <circle cx="283" cy="85" r="12" className="fill-sun" />
      <Plus x={283} y={85} />
      <rect
        x="12"
        y="64"
        width="296"
        height="42"
        rx="14"
        className="stroke-sun-ink"
        strokeWidth="2"
      />
      <Line x={18} y={119} width={112} />
      <Line x={18} y={133} width={80} />
      <Field x={176} y={115} width={128} text={t("app.sunroom")} wide={66} />
    </Window>
  );
}

/** Apple, step 3: the new password, and Copy. */
export function AppleCopyPasswordArt() {
  const t = useT();
  return (
    <Window>
      <Card x={36} y={46} width={248} height={96} />
      <Line x={52} y={58} width={96} />
      <text
        x="160"
        y={baseline(86, 17)}
        fontSize="17"
        fontWeight="600"
        textAnchor="middle"
        className="fill-ink"
      >
        {PASSWORD_SHAPE}
      </text>
      <Target x={124} y={104} width={72} label={t("sync.drawing.apple.copy")} />
    </Window>
  );
}

/** The week in Google's settings drawing: where it starts, and each day's width. */
const WEEK_X = 16;
const DAY_W = 172 / 7;

/** Google's secret address, step 1: the calendar, the gear, and Settings in its menu. */
export function GoogleSettingsArt() {
  const t = useT();
  /** Where day `n` (0 to 6) starts. */
  const day = (n: number) => WEEK_X + n * DAY_W;
  return (
    <Window>
      <Line x={18} y={47} width={64} />
      <circle cx="290" cy="50" r="11" className="fill-line" />
      <Settings x={281} y={41} size={18} className="text-ink" />
      <Card x={WEEK_X} y={64} width={172} height={78} />
      <path
        d={`M${WEEK_X} 78h172${[1, 2, 3, 4, 5, 6].map((n) => `M${day(n).toFixed(1)} 64v78`).join("")}`}
        className="stroke-line"
        strokeWidth="1"
      />
      <g className="fill-line">
        <rect x={day(0) + 3} y="84" width={DAY_W - 6} height="16" rx="3" />
        <rect x={day(2) + 3} y="96" width={DAY_W - 6} height="24" rx="3" />
        <rect x={day(3) + 3} y="84" width={DAY_W - 6} height="12" rx="3" />
        <rect x={day(5) + 3} y="104" width={DAY_W - 6} height="20" rx="3" />
      </g>
      <Card x={200} y={66} width={104} height={76} />
      <Target x={208} y={74} width={88} label={t("sync.drawing.google.settings")} pill={false} />
      <Line x={214} y={116} width={64} />
      <Line x={214} y={128} width={48} />
    </Window>
  );
}

/** Google's secret address, step 2: Settings for my calendars, the calendar, Integrate calendar. */
export function GoogleIntegrateArt() {
  const t = useT();
  return (
    <Window>
      <text x="18" y={baseline(49, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.google.my_calendars")}
      </text>
      <rect
        x="16"
        y="64"
        width="196"
        height="24"
        rx="8"
        className="fill-surface stroke-line"
        strokeWidth="1.5"
      />
      <circle cx="30" cy="76" r="5" className="fill-ink-soft" />
      <Line x={42} y={73} width={84} />
      <Line x={42} y={97} width={100} />
      <Target x={34} y={108} width={164} label={t("sync.drawing.google.integrate")} pill={false} />
      <Card x={226} y={46} width={78} height={96} />
      <Line x={236} y={58} width={50} />
      <Line x={236} y={72} width={36} />
      <Line x={236} y={86} width={56} />
      <Line x={236} y={100} width={30} />
      <Line x={236} y={114} width={44} />
    </Window>
  );
}

/** Google's secret address, step 3: the public address (not this one), then the secret one. */
export function GoogleSecretAddressArt() {
  const t = useT();
  return (
    <Window>
      <Line x={18} y={46} width={150} />
      <rect
        x="16"
        y="58"
        width="244"
        height="22"
        rx="8"
        className="fill-surface stroke-line"
        strokeWidth="1.5"
      />
      <Line x={28} y={66} width={140} />
      <text x="18" y={baseline(100, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.google.secret_address")}
      </text>
      <rect
        x="16"
        y="112"
        width="244"
        height="28"
        rx="8"
        className="fill-surface stroke-ink-soft"
        strokeWidth="1.5"
      />
      <Line x={28} y={123} width={150} />
      <circle cx="284" cy="126" r="18" className="stroke-sun-ink" strokeWidth="2" />
      <circle cx="284" cy="126" r="14" className="fill-sun" />
      <Copy x={276} y={118} size={16} className="text-on-sun" />
    </Window>
  );
}

/** The helper, step 1: console.cloud.google.com, the project's name, and Create. */
export function HelperProjectArt() {
  const t = useT();
  return (
    <Window address="console.cloud.google.com">
      <text x="18" y={baseline(52, 14)} fontSize="14" className="fill-ink-soft">
        {t("sync.drawing.helper.project_name")}
      </text>
      <Field x={16} y={62} width={180} text={t("app.sunroom")} wide={66} />
      <Target x={216} y={63} width={80} label={t("sync.drawing.helper.create")} />
      <Line x={18} y={106} width={200} />
      <Line x={18} y={120} width={150} />
      <Line x={18} y={134} width={176} />
    </Window>
  );
}

/** The helper, step 2: APIs & Services, the Google Calendar API, and Enable. */
export function HelperCalendarApiArt() {
  const t = useT();
  return (
    <Window>
      <text x="18" y={baseline(52, 14)} fontSize="14" fontWeight="500" className="fill-ink-soft">
        {t("sync.drawing.helper.apis")}
      </text>
      <Card x={16} y={62} width={288} height={80} />
      <rect
        x="28"
        y="74"
        width="32"
        height="32"
        rx="8"
        className="fill-wall stroke-line"
        strokeWidth="1.5"
      />
      <Calendar x={34} y={80} size={20} className="text-ink-soft" />
      <text x="72" y={baseline(80, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.helper.calendar_api")}
      </text>
      <Line x={72} y={93} width={140} />
      <Target x={72} y={106} width={76} label={t("sync.drawing.helper.enable")} />
    </Window>
  );
}

/** The helper, step 3: IAM & Admin, Service accounts, Create, and the name. */
export function HelperServiceAccountArt() {
  const t = useT();
  return (
    <Window>
      <text x="18" y={baseline(52, 14)} fontSize="14" fontWeight="500" className="fill-ink-soft">
        {t("sync.drawing.helper.iam")}
      </text>
      <Line x={28} y={67} width={84} />
      <rect x="16" y="78" width="156" height="28" rx="8" className="fill-line" />
      <text x="28" y={baseline(92, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.helper.service_accounts")}
      </text>
      <Line x={28} y={117} width={96} />
      <Line x={28} y={131} width={72} />
      <Target x={192} y={62} width={92}>
        <Plus x={210} y={75} />
        <text x="222" y={baseline(75, 15)} fontSize="15" fontWeight="600" className="fill-on-sun">
          {t("sync.drawing.helper.create")}
        </text>
      </Target>
      <Field x={192} y={104} width={112} text={SERVICE_ACCOUNT} wide={64} />
    </Window>
  );
}

/** The helper, step 4: the Keys tab, Add key, JSON, and the file that downloads. */
export function HelperKeyArt() {
  const t = useT();
  return (
    <Window>
      <Line x={18} y={47} width={44} />
      <Line x={78} y={47} width={60} />
      <text x="154" y={baseline(49, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.helper.keys")}
      </text>
      <path d="M1.5 64.75H318.5" className="stroke-line" strokeWidth="1.5" />
      <rect x="152" y="62" width="40" height="3" rx="1.5" className="fill-ink" />
      <rect
        x="16"
        y="74"
        width="104"
        height="28"
        rx="8"
        className="fill-surface stroke-ink-soft"
        strokeWidth="1.5"
      />
      <text x="28" y={baseline(88, 15)} fontSize="15" fontWeight="600" className="fill-ink">
        {t("sync.drawing.helper.add_key")}
      </text>
      <path
        d="M97 85.75l4.5 4.5 4.5-4.5"
        className="stroke-ink"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Target x={16} y={112} width={88} pill={false}>
        <circle cx="32" cy="125" r="6" className="stroke-on-sun" strokeWidth="2" />
        <circle cx="32" cy="125" r="2.75" className="fill-on-sun" />
        <text x="46" y={baseline(125, 15)} fontSize="15" fontWeight="600" className="fill-on-sun">
          JSON
        </text>
      </Target>
      <circle cx="130" cy="125" r="6" className="stroke-ink-soft" strokeWidth="1.5" />
      <Line x={142} y={122} width={28} />
      <path
        d="M244 76h22l14 14v38a4 4 0 0 1-4 4h-32a4 4 0 0 1-4-4V80a4 4 0 0 1 4-4z"
        className="fill-surface stroke-ink-soft"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M266 76v10a4 4 0 0 0 4 4h10"
        className="stroke-ink-soft"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M260 98v20M252 110l8 8 8-8"
        className="stroke-ink"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Window>
  );
}
