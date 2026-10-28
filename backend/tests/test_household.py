"""Household settings, people, the display's panels and the network allowlist (PLAN §11.1)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from tests.support import CSRF, PASSWORD, add_member, picture, set_pin, state_of


async def test_settings_start_with_the_household_defaults(parent: httpx.AsyncClient) -> None:
    settings = (await parent.get("/api/settings")).json()
    assert settings["household_name"] == "Sample Family"
    assert settings["timezone"] == "America/New_York"
    assert settings["timezone_chosen"] is True
    assert settings["week_starts_on"] == 6  # Sunday
    assert settings["theme"] == "auto"
    assert settings["display_home_view"] == "week"
    assert settings["display_week_layout"] == "hours"  # a new household's start (ADR 0042)
    assert "display_rolling_week" not in settings  # a home view of its own since ADR 0042
    assert settings["show_tips"] is True  # on by default since 0.12.0 (ADR 0034)
    assert settings["text_size"] == "standard"
    assert settings["display_rail_compact"] is False  # the full rail until a parent folds it
    assert settings["display_start"] == "last"  # a screen comes back to where it left off
    assert settings["has_pin"] is False
    assert settings["pin_length"] is None
    assert settings["setup_complete"] is True


async def test_a_parent_changes_settings_and_everyone_hears(
    app: FastAPI, parent: httpx.AsyncClient, events: list[tuple[str, dict[str, Any]]]
) -> None:
    response = await parent.patch(
        "/api/settings",
        json={
            "theme": "dark",
            "text_size": "large",
            "timezone": "America/Chicago",
            "sleep_from": "22:00",
            "sleep_to": "06:30",
            "display_return_minutes": 10,
        },
        headers=CSRF,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["theme"], body["text_size"], body["sleep_from"]) == ("dark", "large", "22:00")
    assert str(state_of(app).zone()) == "America/Chicago"
    assert ("settings.changed", {}) in events
    off = await parent.patch(
        "/api/settings", json={"sleep_from": None, "sleep_to": None}, headers=CSRF
    )
    assert off.json()["sleep_from"] is None


async def test_the_week_layout_and_tips_are_a_parents_to_change(
    parent: httpx.AsyncClient,
) -> None:
    agenda = await parent.patch(
        "/api/settings", json={"display_week_layout": "agenda"}, headers=CSRF
    )
    assert agenda.status_code == 200, agenda.text
    assert (agenda.json()["display_week_layout"], agenda.json()["show_tips"]) == ("agenda", True)
    tips = await parent.patch("/api/settings", json={"show_tips": False}, headers=CSRF)
    assert (tips.json()["display_week_layout"], tips.json()["show_tips"]) == ("agenda", False)
    again = (await parent.get("/api/settings")).json()
    assert (again["display_week_layout"], again["show_tips"]) == ("agenda", False)


async def test_a_parent_picks_the_rolling_week_home_view(parent: httpx.AsyncClient) -> None:
    """Rolling Week is a view of its own since ADR 0042, and a home view like any other."""
    rolling = await parent.patch(
        "/api/settings", json={"display_home_view": "rolling"}, headers=CSRF
    )
    assert rolling.status_code == 200, rolling.text
    assert rolling.json()["display_home_view"] == "rolling"
    # Another setting leaves it as it is.
    hours = await parent.patch("/api/settings", json={"display_week_layout": "hours"}, headers=CSRF)
    assert hours.json()["display_home_view"] == "rolling"
    assert (await parent.get("/api/settings")).json()["display_home_view"] == "rolling"
    week = await parent.patch("/api/settings", json={"display_home_view": "week"}, headers=CSRF)
    assert week.json()["display_home_view"] == "week"
    wrong = await parent.patch("/api/settings", json={"display_home_view": "month"}, headers=CSRF)
    assert wrong.status_code == 422


async def test_a_parent_folds_the_rail_and_picks_small_text(parent: httpx.AsyncClient) -> None:
    compact = await parent.patch("/api/settings", json={"display_rail_compact": True}, headers=CSRF)
    assert compact.status_code == 200, compact.text
    assert compact.json()["display_rail_compact"] is True
    small = await parent.patch("/api/settings", json={"text_size": "small"}, headers=CSRF)
    assert small.status_code == 200, small.text
    assert (small.json()["text_size"], small.json()["display_rail_compact"]) == ("small", True)
    again = (await parent.get("/api/settings")).json()
    assert (again["text_size"], again["display_rail_compact"]) == ("small", True)


async def test_a_parent_picks_what_a_screen_shows_when_it_starts(
    parent: httpx.AsyncClient,
) -> None:
    home = await parent.patch("/api/settings", json={"display_start": "home"}, headers=CSRF)
    assert home.status_code == 200, home.text
    assert home.json()["display_start"] == "home"
    assert (await parent.get("/api/settings")).json()["display_start"] == "home"
    last = await parent.patch("/api/settings", json={"display_start": "last"}, headers=CSRF)
    assert last.json()["display_start"] == "last"
    never = await parent.patch("/api/settings", json={"display_start": "never"}, headers=CSRF)
    assert never.status_code == 422
    assert (await parent.get("/api/settings")).json()["display_start"] == "last"


async def test_bad_settings_are_refused(parent: httpx.AsyncClient) -> None:
    zone = await parent.patch("/api/settings", json={"timezone": "Mars/Base"}, headers=CSRF)
    assert zone.status_code == 422
    half = await parent.patch("/api/settings", json={"sleep_from": "22:00"}, headers=CSRF)
    assert half.status_code == 422
    minutes = await parent.patch("/api/settings", json={"display_return_minutes": 7}, headers=CSRF)
    assert minutes.status_code == 422
    grid = await parent.patch("/api/settings", json={"display_week_layout": "grid"}, headers=CSRF)
    assert grid.status_code == 422
    tiny = await parent.patch("/api/settings", json={"text_size": "tiny"}, headers=CSRF)
    assert tiny.status_code == 422


async def test_people_get_the_next_color_and_names_stay_unique(
    parent: httpx.AsyncClient,
) -> None:
    ana = await add_member(parent, "Ana")
    mia = await add_member(parent, "Mia", "kid", birthday="2017-10-19")
    assert (ana["color"], ana["color_word"]) == ("clay", "Red")
    assert (mia["color"], mia["role"], mia["birthday"]) == ("olive", "kid", "2017-10-19")
    taken = await parent.post("/api/members", json={"name": "mia"}, headers=CSRF)
    assert taken.status_code == 409
    assert taken.json()["error"]["message"] == "That name is already in use. Pick another."
    changed = await parent.patch(
        f"/api/members/{mia['id']}", json={"color": "rose", "birthday": None}, headers=CSRF
    )
    assert (changed.json()["color"], changed.json()["birthday"]) == ("rose", None)


async def test_archiving_hides_a_person_and_restore_brings_them_back(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    leo = await add_member(parent, "Leo", "kid")
    await parent.post(f"/api/members/{leo['id']}/archive", headers=CSRF)
    assert leo["id"] not in state_of(app).household.members
    names = [m["name"] for m in (await parent.get("/api/members")).json()]
    assert "Leo" not in names
    everyone = (await parent.get("/api/members", params={"archived": True})).json()
    assert any(m["name"] == "Leo" and m["archived"] for m in everyone)
    await parent.post(f"/api/members/{leo['id']}/restore", headers=CSRF)
    assert leo["id"] in state_of(app).household.members


async def test_an_avatar_is_stored_as_a_square_webp(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    sam = await add_member(parent, "Sam")
    response = await parent.put(
        f"/api/members/{sam['id']}/avatar",
        content=picture((900, 600)),
        headers=CSRF | {"content-type": "image/jpeg"},
    )
    assert response.status_code == 200, response.text
    url = response.json()["avatar_url"]
    assert url.startswith("/photos/avatars/") and url.endswith(".webp")
    image = await parent.get(url)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/webp"
    assert image.headers["cache-control"] == "private, max-age=31536000, immutable"
    removed = await parent.delete(f"/api/members/{sam['id']}/avatar", headers=CSRF)
    assert removed.json()["avatar_url"] is None


async def test_a_file_that_isnt_a_picture_says_so(parent: httpx.AsyncClient) -> None:
    sam = await add_member(parent, "Sam")
    wrong_type = await parent.put(
        f"/api/members/{sam['id']}/avatar",
        content=b"%PDF-1.7",
        headers=CSRF | {"content-type": "application/pdf"},
    )
    assert wrong_type.status_code == 415
    broken = await parent.put(
        f"/api/members/{sam['id']}/avatar",
        content=b"not really a jpeg",
        headers=CSRF | {"content-type": "image/jpeg"},
    )
    assert broken.status_code == 422
    assert broken.json()["error"]["code"] == "photo_unreadable"


async def test_the_display_layout_keeps_panels_it_wasnt_told_about(
    parent: httpx.AsyncClient,
) -> None:
    layout = (await parent.get("/api/kiosk/layout")).json()
    assert layout == [{"key": "calendar.today", "position": 0, "visible": True, "size": "m"}]
    updated = await parent.put(
        "/api/kiosk/layout",
        json={"panels": [{"key": "chores.today", "size": "l"}]},
        headers=CSRF,
    )
    assert [(p["key"], p["position"]) for p in updated.json()] == [
        ("chores.today", 0),
        ("calendar.today", 1),
    ]
    twice = await parent.put(
        "/api/kiosk/layout",
        json={"panels": [{"key": "chores.today"}, {"key": "chores.today"}]},
        headers=CSRF,
    )
    assert twice.status_code == 422


async def test_a_command_reaches_every_screen(
    parent: httpx.AsyncClient, events: list[tuple[str, dict[str, Any]]]
) -> None:
    response = await parent.post("/api/kiosk/command", json={"command": "reload"}, headers=CSRF)
    assert response.status_code == 204
    assert ("kiosk.command", {"command": "reload"}) in events


async def test_the_network_allowlist_is_for_parents(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    added = await parent.post(
        "/api/network-allowlist",
        json={"target": "NAS.lan", "label": "Photos server"},
        headers=CSRF,
    )
    assert added.status_code == 201
    entry = added.json()
    assert entry["target"] == "nas.lan"
    cidr = await parent.post(
        "/api/network-allowlist", json={"target": "192.168.1.7/24"}, headers=CSRF
    )
    assert cidr.json()["target"] == "192.168.1.0/24"
    await parent.delete(f"/api/network-allowlist/{cidr.json()['id']}", headers=CSRF)
    for junk in ("http://nas.lan/photos", "two words", "-bad-.lan"):
        refused = await parent.post("/api/network-allowlist", json={"target": junk}, headers=CSRF)
        assert refused.status_code == 422, junk
    assert [e["id"] for e in (await parent.get("/api/network-allowlist")).json()] == [entry["id"]]
    await set_pin(parent)
    await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert (await other.get("/api/network-allowlist")).status_code == 403
    assert (
        await parent.delete(f"/api/network-allowlist/{entry['id']}", headers=CSRF)
    ).status_code == 204
    assert (
        await parent.delete(f"/api/network-allowlist/{entry['id']}", headers=CSRF)
    ).status_code == 404


async def test_only_parents_manage_people(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await set_pin(parent)
    kid_phone = (
        await other.post("/api/auth/login", json={"password": PASSWORD}, headers=CSRF)
    ).json()["device_id"]
    await parent.patch(f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF)
    assert (await other.get("/api/members")).status_code == 200
    refused = await other.post("/api/members", json={"name": "Guest"}, headers=CSRF)
    assert refused.status_code == 403


async def test_a_parent_sets_the_default_reminder_and_clears_it(parent: httpx.AsyncClient) -> None:
    """ADR 0034: events with no reminder of their own remind this long before; none by default."""
    assert (await parent.get("/api/settings")).json()["default_reminder_minutes"] is None
    ten = await parent.patch("/api/settings", json={"default_reminder_minutes": 10}, headers=CSRF)
    assert ten.json()["default_reminder_minutes"] == 10
    # Another setting leaves it; an explicit null clears it.
    tips = await parent.patch("/api/settings", json={"show_tips": False}, headers=CSRF)
    assert tips.json()["default_reminder_minutes"] == 10
    cleared = await parent.patch(
        "/api/settings", json={"default_reminder_minutes": None}, headers=CSRF
    )
    assert cleared.json()["default_reminder_minutes"] is None
    odd = await parent.patch("/api/settings", json={"default_reminder_minutes": 7}, headers=CSRF)
    assert odd.status_code == 422
