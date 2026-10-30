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
from functools import cache
from pathlib import Path
from typing import TypedDict

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


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
