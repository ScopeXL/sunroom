/**
 * Settings → Support Sunroom (UX §4, ADR 0034): the owner's links and addresses, filled in by
 * the owner before a release. An empty value hides its row, so the page shows only what's set.
 * Nothing here is sent anywhere: a link opens in the browser, and an address is shown with a QR
 * code to scan or copy.
 */

/** The project's page on GitHub, where Send Feedback opens a new issue. */
export const REPO_URL = "https://github.com/ScopeXL/sunroom";

/** The Sunroom Discord: help, ideas and what's new. An invite that never expires, public by
 * design (ADR 0042). */
export const DISCORD_URL = "https://discord.gg/y6AeQRpsPQ";

/** The Patreon page; empty hides the row. (`as string`: it's the owner's to fill in.) */
export const PATREON_URL = "" as string;

/** Donation addresses, each with its name ("Bitcoin"); an empty list hides them all. */
export const ADDRESSES: readonly { name: string; address: string }[] = [
  // { name: "Bitcoin", address: "" },
];

/** The longest link Send Feedback builds: GitHub takes longer, a QR code can't. */
export const FEEDBACK_URL_MAX = 2000;

export type FeedbackKind = "problem" | "idea";

/** Where the server is installed, in words: "Docker", "a Raspberry Pi". */
export function installWords(kind: string | null | undefined): string | null {
  switch (kind) {
    case "docker":
      return "Docker";
    case "pi":
      return "a Raspberry Pi";
    case "portainer":
      return "Portainer";
    case "ha":
      return "Home Assistant";
    case "computer":
      return "a computer";
    default:
      return null;
  }
}

/**
 * GitHub's new-issue page with the feedback filled in: "Problem: " or "Idea: " before the title,
 * the words, then the version and the install under a rule. The page's CSP lets the app talk to
 * Sunroom's own server only, and a token inside a public image is out of the question, so the
 * person signs in to GitHub there and taps Submit (ADR 0034). The whole link is at most
 * FEEDBACK_URL_MAX characters: the words are cut, never the title or the version.
 */
export function feedbackUrl({
  kind,
  title,
  body,
  version,
  install,
}: {
  kind: FeedbackKind;
  title: string;
  body: string;
  version: string;
  install: string | null;
}): string {
  const prefix = kind === "problem" ? "Problem: " : "Idea: ";
  const footer = `---\nSunroom ${version}${install ? `, ${install}` : ""}`;
  const link = (words: string) => {
    const text = words ? `${words}\n\n${footer}` : footer;
    return `${REPO_URL}/issues/new?title=${encodeURIComponent(prefix + title.trim())}&body=${encodeURIComponent(text)}`;
  };
  const words = body.trim();
  const whole = link(words);
  if (whole.length <= FEEDBACK_URL_MAX) return whole;
  // The most words that fit, then an ellipsis: found by halving, since a letter can take one
  // character of the link or nine.
  const cut = (n: number) => link(n > 0 ? `${words.slice(0, n).trimEnd()}…` : "");
  let low = 0;
  let high = words.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (cut(middle).length <= FEEDBACK_URL_MAX) low = middle;
    else high = middle - 1;
  }
  return cut(low);
}
