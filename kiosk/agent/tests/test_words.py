"""Sunroom Screen's sentences (words.py, ADR 0043): English from the repo's lang/en.json, every
key the agent names is there, and its messages are plain ``{name}`` substitutions the page can
say in the household's language. Synthetic values only."""

from __future__ import annotations

import re
from pathlib import Path

from sunroom_kiosk import words
from sunroom_kiosk.app import AppError
from sunroom_kiosk.platform.base import PlatformError, UnsupportedError


def named_keys() -> set[str]:
    """Every ``"agent.…"`` literal in the agent's sources."""
    package = Path(words.__file__).parent
    found: set[str] = set()
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"[\"'](agent\.[a-z0-9_.]+)[\"']", text))
    return found


def test_the_words_are_the_checkouts_until_the_wheel_carries_them() -> None:
    assert (words.lang_dir() / "en.json").is_file()


def test_every_key_the_agent_names_is_in_english() -> None:
    keys = named_keys()
    assert len(keys) > 50
    assert sorted(key for key in keys if key not in words.english()) == []


def test_its_messages_are_plain_substitutions() -> None:
    for key, message in words.english().items():
        if key.startswith("agent."):
            assert not re.search(r"\{\w+,", message), key  # no plural or select: t_en says it


def test_a_sentence_carries_its_key_its_values_and_its_english() -> None:
    sentence = words.said("agent.wifi.out_of_range", ssid="HomeNet")
    assert sentence.out() == {
        "message": "HomeNet is out of range. Move closer, or try another network.",
        "key": "agent.wifi.out_of_range",
        "params": {"ssid": "HomeNet"},
    }
    failed = PlatformError("agent.rotate.failed")
    assert str(failed) == "The picture didn't turn. Try again in a moment."  # the log's English
    assert failed.said.key == "agent.rotate.failed"
    assert str(UnsupportedError()) == "That isn't something this screen can do."
    refused = AppError(409, "not_here", "agent.unsupported.wifi")
    assert (refused.status, refused.code, str(refused)) == (
        409,
        "not_here",
        "Wi-Fi isn't something this screen can do.",
    )
