"""Sunroom Screen's sentences, by key (ADR 0043, docs/LANGUAGES.md).

Every sentence the family reads lives in the repo's ``lang/en.json``. The agent says its English
(its log, an older page) from that same file, so no English stays in Python, and sends each
sentence's key and values beside it: the page says it in the household's language. Its messages
(``agent.*``) are plain ``{name}`` substitutions, no plural or select (``just lang`` checks).

The words are ``sunroom_kiosk/lang/`` inside the package (the wheel carries them, hatchling's
``force-include``), and the checkout's ``lang/`` otherwise (``--dev``, ``--fake``, the tests).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def lang_dir() -> Path:
    packaged = Path(__file__).resolve().parent / "lang"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[4] / "lang"


@cache
def english() -> dict[str, str]:
    return json.loads((lang_dir() / "en.json").read_text(encoding="utf-8"))


def t_en(key: str, **params: object) -> str:
    """The key's English with its ``{name}`` values filled in; a key the file lacks is a
    KeyError, which a test meets first (``tests/test_words.py``)."""
    return _PLACEHOLDER.sub(lambda match: str(params[match.group(1)]), english()[key])


@dataclass(frozen=True)
class Said:
    """A sentence for the family: its key, its values, and its English."""

    key: str
    params: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def message(self) -> str:
        return t_en(self.key, **self.params)

    def out(self) -> dict[str, Any]:
        return {"message": self.message, "key": self.key, "params": self.params}


def said(key: str, **params: object) -> Said:
    return Said(key, {name: str(value) for name, value in params.items()})


class SaidError(Exception):
    """A failure the family reads: ``str(error)`` is its English, ``said`` its key and values."""

    def __init__(self, key: str, **params: object) -> None:
        self.said = said(key, **params)
        super().__init__(self.said.message)
