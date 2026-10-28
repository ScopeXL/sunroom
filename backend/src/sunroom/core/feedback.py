"""Send Feedback's message (ADR 0042): what a family wrote, shaped as Discord's webhook body, so
the project's relay only forwards it (meta/feedback.py posts it). Nothing else goes in: no
household name, no address, no member and no event; only Sunroom's version and how this server
is installed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sunroom.core.config import InstallKind

FeedbackKind = Literal["problem", "idea"]

# Discord's limits on a message's embeds, in characters (its webhook and message docs, read for
# ADR 0042): a title, a description, a field's value, and all of them together.
TITLE_MAX = 256
DESCRIPTION_MAX = 4096
FIELD_MAX = 1024
TOTAL_MAX = 6000

SENDS_PER_HOUR = 5
HOUR = timedelta(hours=1)
KEPT = 10

INSTALL_WORDS: dict[InstallKind, str] = {
    InstallKind.DOCKER: "Docker",
    InstallKind.PI: "a Raspberry Pi",
    InstallKind.PORTAINER: "Portainer",
    InstallKind.HA: "Home Assistant",
    InstallKind.COMPUTER: "a computer",
}

# A line of color down the message's side, one per kind, as Discord takes it (an RGB number).
COLORS: dict[FeedbackKind, int] = {"problem": 0xD9480F, "idea": 0xF5B014}


@dataclass
class Outbox:
    """What Send Feedback sent in the last hour (at most SENDS_PER_HOUR from one server), and on
    the test server what it would have sent instead (the last few, for the end-to-end tests)."""

    sent_at: deque[datetime] = field(default_factory=deque[datetime])
    kept: deque[dict[str, Any]] = field(default_factory=lambda: deque[dict[str, Any]](maxlen=KEPT))

    def take(self, now: datetime) -> bool:
        """One more send this hour, if there's room for it."""
        while self.sent_at and now - self.sent_at[0] >= HOUR:
            self.sent_at.popleft()
        if len(self.sent_at) >= SENDS_PER_HOUR:
            return False
        self.sent_at.append(now)
        return True

    def clear(self) -> None:
        self.sent_at.clear()
        self.kept.clear()


def cut(text: str, limit: int) -> str:
    """At most ``limit`` characters, an ellipsis last where it was cut."""
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def message(
    *,
    kind: FeedbackKind,
    title: str,
    words: str,
    contact: str,
    version: str,
    install: str,
) -> dict[str, Any]:
    """Discord's webhook body: one embed, "Problem: …" or "Idea: …" over the words, then the
    version, the install and who to reply to; no mentions, whatever the words say."""
    values = {
        "Version": cut(version, FIELD_MAX),
        "Install": cut(install, FIELD_MAX),
        "Reply to": cut(contact, FIELD_MAX) or "—",
    }
    fields = [
        {"name": name, "value": value, "inline": name != "Reply to"}
        for name, value in values.items()
    ]
    heading = cut(f"{'Problem' if kind == 'problem' else 'Idea'}: {title.strip()}", TITLE_MAX)
    embed: dict[str, Any] = {"title": heading, "color": COLORS[kind], "fields": fields}
    # Whatever room the title and the fields leave under Discord's total goes to the words.
    room = TOTAL_MAX - len(heading) - sum(len(name) + len(value) for name, value in values.items())
    description = cut(words, min(DESCRIPTION_MAX, room))
    if description:
        embed["description"] = description
    return {
        "username": "Sunroom feedback",
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }
