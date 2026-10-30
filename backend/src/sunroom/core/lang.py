"""The server's words, by key (ADR 0043, docs/LANGUAGES.md).

Every sentence the family reads lives in the repo's ``lang/en.json``; the page speaks the family's
language from it. The server keeps saying English, read from that same file so no English stays in
Python, and names each sentence's key and parameters beside it so the page can say it in the
household's language. Its messages (``api.*``) are plain ``{name}`` substitutions, no plural or
select (``just lang`` checks), so ``t_en`` needs no ICU of its own.

The files are ``sunroom/lang/`` inside the package when it was built with them (the image, the
server wheel), and the checkout's ``lang/`` otherwise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TypedDict

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_PIECES = re.compile(r"(\{\w+\})")

# A value a sentence's placeholder takes: what the page's formatter takes too.
type Value = str | int | float


class LanguageInfo(TypedDict):
    name: str
    locale: str
    dir: str
    status: str
    chrono: str
    keyboard: str


def lang_dir() -> Path:
    packaged = Path(__file__).resolve().parent.parent / "lang"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[4] / "lang"


@cache
def english() -> dict[str, str]:
    return json.loads((lang_dir() / "en.json").read_text(encoding="utf-8"))


@cache
def languages() -> dict[str, LanguageInfo]:
    """The registry: each language's code, its own name, its locale, and whether it's complete."""
    return json.loads((lang_dir() / "languages.json").read_text(encoding="utf-8"))


def known_language(code: str) -> str:
    """A pydantic validator: a language the registry has."""
    if code not in languages():
        raise ValueError("That language isn't one Sunroom has.")
    return code


def t_en(key: str, **params: object) -> str:
    """The key's English, with its ``{name}`` placeholders filled in. A key the file lacks is a
    KeyError, which a test meets first (``tests/test_lang.py``)."""
    return _PLACEHOLDER.sub(lambda match: str(params[match.group(1)]), english()[key])


def plain(params: Mapping[str, object] | None) -> dict[str, Value]:
    """A sentence's values as JSON carries them to the page: text and numbers as they are,
    anything else as its text."""
    return {
        name: value if isinstance(value, str | int | float) else str(value)
        for name, value in (params or {}).items()
    }


@dataclass(frozen=True, slots=True)
class Words:
    """One sentence for people, by its key and values: the server says ``english``, and names
    the key and values beside it so the page can say it in the family's language."""

    key: str
    params: Mapping[str, Value] = field(default_factory=dict[str, Value])

    @property
    def english(self) -> str:
        return t_en(self.key, **self.params)


def match_english(text: str, keys: Iterable[str]) -> Words | None:
    """Which of these keys ``text`` is the English of, with the values that fill it in: for a
    sentence kept as English (a photo source's last line), named again by its key."""
    for key in keys:
        seen: set[str] = set()
        pattern: list[str] = []
        for piece in _PIECES.split(english()[key]):
            name = piece[1:-1] if _PIECES.fullmatch(piece) else None
            if name is None:
                pattern.append(re.escape(piece))
            elif name in seen:
                pattern.append(f"(?P={name})")
            else:
                seen.add(name)
                pattern.append(f"(?P<{name}>.+?)")
        found = re.fullmatch("".join(pattern), text, re.DOTALL)
        if found is not None:
            return Words(key, found.groupdict())
    return None
