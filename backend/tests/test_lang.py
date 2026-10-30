"""The server's words (ADR 0043, core/lang.py): English from the repo's lang/ files, by key."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from sunroom.core import lang

SOURCES = Path(lang.__file__).resolve().parents[1]
SERVER_KEY = re.compile(r"^api\.[a-z0-9_]+(\.[a-z0-9_]+)+$")
PLAIN = re.compile(r"\{\w+\}")


def test_the_words_are_the_checkouts_until_a_package_carries_them() -> None:
    assert (lang.lang_dir() / "en.json").is_file()
    assert (lang.lang_dir() / "languages.json").is_file()


def test_english_is_complete_and_every_language_names_itself() -> None:
    registry = lang.languages()
    assert registry["en"]["status"] == "complete"
    assert registry["en"]["locale"] == "en-US"
    for code, info in registry.items():
        assert (lang.lang_dir() / f"{code}.json").is_file(), code
        assert info["name"]
        assert info["status"] in {"complete", "preview"}
        assert info["dir"] in {"ltr", "rtl"}


def test_a_key_says_its_english_with_its_values() -> None:
    assert lang.t_en("app.action.done") == "Done"
    assert lang.t_en("app.language.aria", name="English") == "Language: English"
    with pytest.raises(KeyError):
        lang.t_en("api.nothing.here")


def test_only_a_language_sunroom_has_is_known() -> None:
    assert lang.known_language("es") == "es"
    with pytest.raises(ValueError, match="isn't one Sunroom has"):
        lang.known_language("xx")


# ---- the server's words (M10 T5) ----------------------------------------------------------------


def _server_keys() -> dict[str, str]:
    """Every ``"api.…"`` literal in the server's code, and where it is."""
    found: dict[str, str] = {}
    for path in sorted(SOURCES.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if SERVER_KEY.match(node.value):
                    found.setdefault(node.value, f"{path.relative_to(SOURCES)}:{node.lineno}")
    return found


def test_every_key_the_server_names_is_english() -> None:
    named = _server_keys()
    assert len(named) > 300  # the scan sees the code
    missing = {key: where for key, where in named.items() if key not in lang.english()}
    assert missing == {}


def test_the_servers_words_are_plain_substitutions() -> None:
    """No plural or select in ``api.*`` (ADR 0043): ``t_en`` fills in ``{name}`` and nothing
    more, so the English the server says is the English the page would."""
    for key, english in lang.english().items():
        if not key.startswith("api."):
            continue
        rest = PLAIN.sub("", english)
        assert "{" not in rest and "}" not in rest, key
        assert not re.search(r"'[{}#<|]", english), key  # an apostrophe ICU reads as a quote
        values = {name[1:-1]: "x" for name in PLAIN.findall(english)}
        assert "{" not in lang.t_en(key, **values), key


def test_a_sentence_s_values_travel_as_text_or_numbers() -> None:
    assert lang.plain(None) == {}
    assert lang.plain({"name": "Mia", "count": 3, "size": 1.5, "why": OSError("full")}) == {
        "name": "Mia",
        "count": 3,
        "size": 1.5,
        "why": "full",
    }
    said = lang.Words("api.tasks.not_enough", {"name": "Mia", "have": 3, "cost": 5})
    assert said.english == "Mia has 3 of 5 stars."


def test_a_kept_sentence_is_named_by_its_key_again() -> None:
    keys = ("api.photos.inbox.unreadable_one", "api.photos.inbox.unreadable", "api.http.404")
    kept = "3 files weren't photos Sunroom could read. They're in the inbox's unreadable folder."
    assert lang.match_english(kept, keys) == lang.Words(
        "api.photos.inbox.unreadable", {"count": "3"}
    )
    assert lang.match_english("That couldn't be found.", keys) == lang.Words("api.http.404")
    assert lang.match_english("Something else entirely.", keys) is None
