import { Check } from "lucide-react";

import type { Member } from "../../lib/household";
import { Avatar } from "../../ui/Avatar";

/**
 * A person to pick, with their avatar (Who's using this device?). Whoever already uses this
 * device is pressed three ways: an ink border, a check and "Using this device" (UX §5).
 */
export function MemberButton({
  member,
  chosen,
  disabled,
  onChoose,
}: {
  member: Member;
  /** Whether this person uses this device; left out where nobody is picked yet. */
  chosen?: boolean;
  disabled?: boolean;
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={chosen}
      disabled={disabled}
      onClick={onChoose}
      className="press-row flex min-h-16 w-full items-center gap-4 rounded-button border-2 border-line bg-surface px-4 py-2 text-left disabled:opacity-60 aria-pressed:border-ink"
    >
      <Avatar member={member} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-row font-semibold">{member.name}</span>
        {chosen ? <span className="text-secondary text-ink-soft">Using this device</span> : null}
      </span>
      {chosen ? <Check aria-hidden="true" className="size-6 shrink-0 text-ink" /> : null}
    </button>
  );
}
