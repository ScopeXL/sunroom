"""The daily check for a newer Sunroom (PLAN §13.6, ADR 0046).

On by default, so every install hears the day a version comes out: Settings → About → "Tell me about
new versions" turns it off, and ``SUNROOM_UPDATE_CHECK=0`` keeps it off. One request a day to
sunroom.day's ``version.json``, or to GitHub's latest Release when that doesn't answer, tells them
the server's address (PRIVACY.md says so). The site writes that file when a Release is published,
and the deploy skill publishes that last, so nothing here names a version whose image and files
aren't out yet. The answer lives in memory (one process serves the API); after a restart the next
hourly tick asks again. How to update is worded by
``SUNROOM_INSTALL_KIND``: Compose, Portainer, a NAS's own app, a Pi, or the screen that runs Sunroom
as a program (ADR 0038).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sunroom.core.config import InstallKind
from sunroom.core.http import GuardedHttp, OutboundError

# Written by the site's release bot: {"version": "1.0.0", "published": "…", "notes": "…"}.
# SUNROOM_UPDATE_URL points at a self-hoster's own copy.
VERSION_URL = "https://sunroom.day/version.json"
RELEASE_URL = "https://api.github.com/repos/ScopeXL/sunroom/releases/latest"
CHECK_EVERY = timedelta(hours=24)
TICK_S = 3600
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


# The sentence in lang/en.json that says how to update each kind of install (ADR 0046).
HOW_KEYS: dict[InstallKind, str] = {
    InstallKind.DOCKER: "api.update.how.docker",
    InstallKind.PORTAINER: "api.update.how.portainer",
    InstallKind.UNRAID: "api.update.how.unraid",
    InstallKind.CASAOS: "api.update.how.casaos",
    InstallKind.SYNOLOGY: "api.update.how.synology",
    InstallKind.OTHER: "api.update.how.other",
    InstallKind.PI: "api.update.how.pi",
    InstallKind.HA: "api.update.how.ha",
    InstallKind.COMPUTER: "api.update.how.computer",
}


@dataclass
class UpdateCheck:
    latest: str | None = None  # "0.6.1", the latest Release's version
    published: datetime | None = None  # when that came out, if the answer said
    checked_at: datetime | None = None
    problem: str | None = None  # plain English, when the last check didn't get an answer

    def due(self, now: datetime) -> bool:
        return self.checked_at is None or now - self.checked_at >= CHECK_EVERY


def parse(version: str) -> tuple[int, int, int] | None:
    found = _VERSION.match(version.strip())
    if found is None:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


def made_up(current: str) -> str | None:
    """The test server's answer instead of GitHub's: the next minor version, so Settings → About
    shows a new version without anything leaving the machine."""
    found = parse(current)
    if found is None:
        return None
    major, minor, _ = found
    return f"{major}.{minor + 1}.0"


def newer(candidate: str | None, current: str) -> bool:
    """Whether ``candidate`` is a later release than the running ``current``."""
    if candidate is None:
        return False
    theirs, ours = parse(candidate), parse(current)
    return theirs is not None and ours is not None and theirs > ours


async def check(
    http: GuardedHttp,
    current: str,
    now: datetime,
    into: UpdateCheck,
    *,
    url: str = VERSION_URL,
) -> None:
    """Ask for the latest version; never raises (a quiet line in About says why not)."""
    into.checked_at = now
    found = await _ask(http, url, current, _from_site) or await _ask(
        http, RELEASE_URL, current, _from_release
    )
    if found is None:
        into.problem = "Sunroom couldn't find out its latest version. It will try again tomorrow."
        return
    into.latest, into.published = found
    into.problem = None


type Found = tuple[str, datetime | None]


async def _ask(
    http: GuardedHttp, url: str, current: str, read: Callable[[dict[str, object]], Found | None]
) -> Found | None:
    try:
        answer = await http.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"Sunroom/{current}",
            },
            max_bytes=256 * 1024,
        )
    except OutboundError:
        return None
    if not answer.ok:
        return None
    try:
        body: object = json.loads(answer.content)
    except ValueError:
        return None
    return read(cast("dict[str, object]", body)) if isinstance(body, dict) else None


def _from_site(body: dict[str, object]) -> Found | None:
    """version.json: {"version": "1.0.0", "published": "2027-01-06T12:00:00Z", …}."""
    return _found(body.get("version"), body.get("published"))


def _from_release(body: dict[str, object]) -> Found | None:
    """A Release: {"tag_name": "v0.9.1", "prerelease": false, "published_at": "…", …}. GitHub
    answers with neither a draft nor a pre-release here; one that came anyway wouldn't count."""
    if body.get("draft") or body.get("prerelease"):
        return None
    return _found(body.get("tag_name"), body.get("published_at"))


def _found(name: object, published: object) -> Found | None:
    version = parse(name) if isinstance(name, str) else None
    if version is None:
        return None
    return ".".join(str(part) for part in version), _when(published)


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
