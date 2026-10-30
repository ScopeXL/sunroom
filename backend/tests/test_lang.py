"""The server's words (ADR 0043, core/lang.py): English from the repo's lang/ files, by key."""

from __future__ import annotations

import pytest

from sunroom.core import lang


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
