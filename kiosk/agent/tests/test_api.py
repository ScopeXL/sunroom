"""The agent's API on the pretend platform (docs/M7.md, "The agent's API"): every route, who may
call it (the loopback names, CORS for the Sunroom it shows and its own pages, the header on every
change), and what each change does to the pretend screen. Synthetic data only."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sunroom_kiosk import config as settings_file
from sunroom_kiosk import state as agent_module
from sunroom_kiosk.app import create_app
from sunroom_kiosk.browser import NoBrowser
from sunroom_kiosk.config import Config
from sunroom_kiosk.platform.fake import FakePlatform
from sunroom_kiosk.state import Agent
from tests.support import AGENT, CHANGE, PORT, SUNROOM, SUNROOM_ID, FakeSunrooms


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_module, "ACTION_DELAY_S", 0)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------- who may call


async def test_the_state_says_what_this_screen_is_and_can_do(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/screen")).json()
    assert body["platform"] == "pi"
    assert body["capabilities"] == [
        "restart",
        "shutdown",
        "update",
        "wifi",
        "rotate",
        "brightness",
        "run_sunroom",
    ]
    assert body["sunroom"] is None and body["open_url"] is None
    assert body["update"]["check"] == "nightly"  # every screen installs overnight by default
    assert body["display"] == {"rotation": 0, "brightness_method": "none"}


@pytest.mark.parametrize("host", ["evil.example:7800", "192.168.1.30:7800", "127.0.0.1:7801"])
async def test_only_a_loopback_name_reaches_it(client: httpx.AsyncClient, host: str) -> None:
    """A page that points its own name at 127.0.0.1 still sends that name."""
    response = await client.get("/api/screen", headers={"Host": host})
    assert response.status_code == 421
    assert response.json()["error"]["code"] == "unknown_host"


@pytest.mark.parametrize("host", ["127.0.0.1:7800", "localhost:7800", "[::1]:7800"])
async def test_the_loopback_names_all_work(client: httpx.AsyncClient, host: str) -> None:
    assert (await client.get("/api/screen", headers={"Host": host})).status_code == 200


async def test_a_change_needs_the_header(client: httpx.AsyncClient, platform: FakePlatform) -> None:
    refused = await client.post("/api/screen/restart")
    assert refused.status_code == 403
    assert refused.json() == {
        "error": {"code": "header", "message": "A change needs the X-Sunroom-Screen header."}
    }
    assert (await client.post("/api/screen/restart", headers=CHANGE)).status_code == 202


async def test_cors_answers_the_sunroom_it_shows_and_its_own_pages(
    client: httpx.AsyncClient, agent: Agent
) -> None:
    agent.save(Config(url=SUNROOM, sunroom_id=SUNROOM_ID, found="typed"))
    for origin in (SUNROOM, AGENT, f"http://localhost:{PORT}"):
        preflight = await client.options(
            "/api/screen/restart",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-sunroom-screen",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        assert preflight.status_code == 204, origin
        assert preflight.headers["access-control-allow-origin"] == origin
        assert preflight.headers["access-control-allow-private-network"] == "true"
        assert "X-Sunroom-Screen" in preflight.headers["access-control-allow-headers"]
        assert "access-control-allow-credentials" not in preflight.headers
        read = await client.get("/api/screen", headers={"Origin": origin})
        assert read.headers["access-control-allow-origin"] == origin
        assert "Origin" in read.headers["vary"]


async def test_another_page_gets_no_cors_and_changes_nothing(
    client: httpx.AsyncClient, platform: FakePlatform
) -> None:
    other = {"Origin": "https://calendar.example.com"}
    preflight = await client.options(
        "/api/screen/restart", headers={**other, "Access-Control-Request-Method": "POST"}
    )
    assert preflight.status_code == 403
    read = await client.get("/api/screen", headers=other)
    assert "access-control-allow-origin" not in read.headers  # the browser won't let it read
    change = await client.post("/api/screen/restart", headers={**other, **CHANGE})
    assert change.status_code == 403
    await settle()
    assert platform.calls == []


async def test_a_new_address_moves_the_allowed_origin(
    client: httpx.AsyncClient, agent: Agent
) -> None:
    old = "http://192.168.1.21:8080"
    agent.save(Config(url=old, found="typed"))
    assert (await client.get("/api/screen", headers={"Origin": old})).headers.get(
        "access-control-allow-origin"
    ) == old
    agent.save(Config(url=SUNROOM, found="typed"))
    assert (
        "access-control-allow-origin"
        not in (await client.get("/api/screen", headers={"Origin": old})).headers
    )


async def test_the_policy_is_the_same_for_every_address(
    agent: Agent, platform: FakePlatform
) -> None:
    """Every page may reach the agent (ADR 0042): only the Sunroom it shows gets an answer (CORS,
    above), so the policy needn't follow the address, and choosing one restarts nothing."""
    await agent.apply_policy()
    first = dict(platform.policies)
    agent.save(Config(url=SUNROOM, found="typed"))
    await agent.apply_policy()
    assert platform.policies == first
    assert next(iter(first.values()))["LocalNetworkAccessAllowedForUrls"] == ["*"]


# ---------------------------------------------------------------------------- the machine


async def test_restart_and_shut_down_answer_first_then_act(
    client: httpx.AsyncClient, platform: FakePlatform
) -> None:
    assert (await client.post("/api/screen/restart", headers=CHANGE)).json() == {"ok": True}
    assert (await client.post("/api/screen/shutdown", headers=CHANGE)).status_code == 202
    await settle()
    assert platform.calls == ["restart", "shutdown"]


async def test_a_fresh_pairing_is_written_to_disk_at_once(
    client: httpx.AsyncClient, agent: Agent
) -> None:
    """The wall's page asks right after it pairs (ADR 0040); it needs the header, as any change."""
    assert (await client.post("/api/screen/keep-pairing")).status_code == 403
    assert (await client.post("/api/screen/keep-pairing", headers=CHANGE)).status_code == 202
    await settle()
    assert isinstance(agent.browser, NoBrowser)
    assert agent.browser.calls == ["save cookies"]


async def test_what_a_screen_cant_do_is_refused_in_words(
    client: httpx.AsyncClient, platform: FakePlatform
) -> None:
    """A Pi has no Quit; a computer can't turn its picture or join Wi-Fi from here."""
    quit_ = await client.post("/api/screen/quit", headers=CHANGE)
    assert quit_.status_code == 409
    assert quit_.json()["error"]["message"] == "Quitting isn't something this screen can do."
    platform.kind = "desktop"
    assert (
        await client.put("/api/screen/display", json={"rotation": 90}, headers=CHANGE)
    ).status_code == 409
    assert (await client.get("/api/screen/wifi")).status_code == 409
    assert (
        await client.post("/api/screen/open-network-settings", headers=CHANGE)
    ).status_code == 202
    await settle()
    assert platform.calls == ["open_network_settings"]


async def test_rotation_turns_the_picture_and_is_kept(
    client: httpx.AsyncClient, platform: FakePlatform, config_path: Path
) -> None:
    response = await client.put("/api/screen/display", json={"rotation": 270}, headers=CHANGE)
    assert response.json()["display"]["rotation"] == 270
    assert platform.rotation == 270
    assert settings_file.load(config_path).rotate == 270
    bad = await client.put("/api/screen/display", json={"rotation": 45}, headers=CHANGE)
    assert bad.status_code == 422


# ---------------------------------------------------------------------------- Wi-Fi


async def test_wifi_lists_joins_and_forgets(
    client: httpx.AsyncClient, platform: FakePlatform
) -> None:
    networks = (await client.get("/api/screen/wifi")).json()["networks"]
    assert [n["ssid"] for n in networks] == ["HomeNet", "SampleStreet-5G", "Library Guest"]
    assert networks[0]["connected"] and networks[0]["saved"]
    wrong = await client.post(
        "/api/screen/wifi",
        json={"ssid": "SampleStreet-5G", "password": "wrong-password"},
        headers=CHANGE,
    )
    assert wrong.status_code == 409
    assert wrong.json()["error"]["message"] == (
        "That password didn't work for SampleStreet-5G. Check it and try again."
    )
    joined = await client.post(
        "/api/screen/wifi",
        json={"ssid": "SampleStreet-5G", "password": "sample-pass-1"},
        headers=CHANGE,
    )
    assert joined.json()["networks"][0]["ssid"] == "SampleStreet-5G"  # connected first
    state = (await client.get("/api/screen")).json()
    assert state["network"]["ssid"] == "SampleStreet-5G"
    forgot = await client.delete("/api/screen/wifi/HomeNet", headers=CHANGE)
    home = next(n for n in forgot.json()["networks"] if n["ssid"] == "HomeNet")
    assert home["saved"] is False and home["id"] is None


async def test_a_wifi_password_never_reaches_the_log(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG", logger="sunroom_kiosk")
    await client.post(
        "/api/screen/wifi",
        json={"ssid": "SampleStreet-5G", "password": "sample-secret-99"},
        headers=CHANGE,
    )
    assert "sample-secret-99" not in caplog.text
    assert "SampleStreet-5G" in caplog.text


# ---------------------------------------------------------------------------- the Sunroom


async def test_an_address_is_checked_in_plain_words(
    client: httpx.AsyncClient, sunrooms: FakeSunrooms
) -> None:
    found = (
        await client.post(
            "/api/screen/sunroom/check", json={"url": "192.168.1.20:8080"}, headers=CHANGE
        )
    ).json()
    assert found["ok"] is True
    assert found["sunroom"]["url"] == SUNROOM  # a number: http first
    assert found["sunroom"]["name"] == "The Sample Family"
    sunrooms.older["http://192.168.1.22:8080"] = "0.11.0"
    older = (
        await client.post(
            "/api/screen/sunroom/check", json={"url": "http://192.168.1.22:8080"}, headers=CHANGE
        )
    ).json()
    assert older["sunroom"]["older"] is True and older["sunroom"]["version"] == "0.11.0"
    sunrooms.other.add("http://192.168.1.1")
    router = (
        await client.post(
            "/api/screen/sunroom/check", json={"url": "http://192.168.1.1"}, headers=CHANGE
        )
    ).json()
    assert router == {
        "ok": False,
        "sunroom": None,
        "message": "That address isn't a Sunroom. Check it and try again.",
    }
    nowhere = (
        await client.post(
            "/api/screen/sunroom/check",
            json={"url": "https://calendar.example.com"},
            headers=CHANGE,
        )
    ).json()
    assert nowhere["message"] == "Can't reach that address from here."


async def test_saving_a_sunroom_restarts_nothing_and_says_so_at_once(
    client: httpx.AsyncClient,
    agent: Agent,
    platform: FakePlatform,
    browser: NoBrowser,
    config_path: Path,
) -> None:
    """The page that chose it opens it when it hears the new state (ADR 0042): the browser is
    neither restarted nor sent anywhere, so the wall shows Sunroom once, with one pair code."""
    published: list[str] = []
    publish = agent.hub.publish

    def note(kind: str, data: object) -> None:
        published.append(kind)
        publish(kind, data)

    agent.hub.publish = note  # type: ignore[method-assign]
    saved = await client.put(
        "/api/screen/sunroom", json={"url": SUNROOM, "found": "discovered"}, headers=CHANGE
    )
    body = saved.json()
    assert body["sunroom"] == {
        "url": SUNROOM,
        "id": SUNROOM_ID,
        "name": "The Sample Family",
        "found": "discovered",
        "reachable": True,
        "version": "0.13.0",
    }
    assert body["open_url"] == f"{SUNROOM}/display?dimmer=page&screen={PORT}"
    kept = settings_file.load(config_path)
    assert (kept.url, kept.sunroom_id, kept.found) == (SUNROOM, SUNROOM_ID, "discovered")
    policy = next(iter(platform.policies.values()))
    assert policy["LocalNetworkAccessAllowedForUrls"] == ["*"]
    assert policy["LocalNetworkAccessRestrictionsEnabled"] is True
    assert "state" in published
    await settle()
    assert browser.calls == []


async def test_only_a_sunroom_is_ever_saved(client: httpx.AsyncClient, config_path: Path) -> None:
    refused = await client.put(
        "/api/screen/sunroom",
        json={"url": "https://calendar.example.com", "found": "typed"},
        headers=CHANGE,
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == "Can't reach that address from here."
    assert settings_file.load(config_path).url is None


async def test_forgetting_the_address_keeps_the_rest(
    client: httpx.AsyncClient, agent: Agent, browser: NoBrowser, config_path: Path
) -> None:
    agent.save(Config(url=SUNROOM, sunroom_id=SUNROOM_ID, found="typed", rotate=90))
    body = (await client.delete("/api/screen/sunroom", headers=CHANGE)).json()
    assert body["sunroom"] is None
    kept = settings_file.load(config_path)
    assert (kept.url, kept.sunroom_id, kept.found, kept.rotate) == (None, None, None, 90)
    await settle()
    assert browser.calls == []  # the page that asked goes to Where Is Your Sunroom? itself


async def test_a_scan_streams_what_it_finds(
    client: httpx.AsyncClient, agent: Agent, sunrooms: FakeSunrooms
) -> None:
    sunrooms.older["http://192.168.1.22:8080"] = "0.11.0"
    seen: list[bytes] = []

    async def listen() -> None:
        async for chunk in agent.hub.stream():
            seen.append(chunk)
            if b"discovery.done" in chunk:
                return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    assert (await client.post("/api/screen/sunrooms/scan", headers=CHANGE)).status_code == 202
    await asyncio.wait_for(listener, 10)
    found = [
        json.loads(c.split(b"data: ", 1)[1])
        for c in seen
        if c.startswith(b"event: discovery.found")
    ]
    assert {f["url"] for f in found} == {SUNROOM, "http://192.168.1.22:8080"}
    listed = (await client.get("/api/screen/sunrooms")).json()
    assert listed["scanning"] is False and len(listed["found"]) == 2


# ---------------------------------------------------------------------------- updates, about


async def test_update_now_streams_its_progress(client: httpx.AsyncClient, agent: Agent) -> None:
    checked = (await client.get("/api/screen/update")).json()
    assert checked["state"] == "available" and checked["latest"] == "9.9.9"
    progress: list[dict[str, Any]] = []

    async def listen() -> None:
        async for chunk in agent.hub.stream():
            if chunk.startswith(b"event: update.progress"):
                progress.append(json.loads(chunk.split(b"data: ", 1)[1]))
                if progress[-1]["percent"] == 100:
                    return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    assert (await client.post("/api/screen/update", headers=CHANGE)).status_code == 202
    await asyncio.wait_for(listener, 5)
    assert [p["percent"] for p in progress] == [10, 45, 80, 100]
    assert (await client.get("/api/screen")).json()["update"]["installed"] == "9.9.9"


async def test_the_update_policy_is_kept(client: httpx.AsyncClient, config_path: Path) -> None:
    body = (
        await client.put("/api/screen/update-policy", json={"check": "off"}, headers=CHANGE)
    ).json()
    assert body["check"] == "off"
    assert settings_file.load(config_path).update_check == "off"


async def test_about_has_the_versions_and_the_log(client: httpx.AsyncClient, agent: Agent) -> None:
    agent.save(Config(url=SUNROOM, found="typed"))
    body = (await client.get("/api/screen/about")).json()
    assert body["platform"] == "pi" and body["hostname"] == "sunroom"
    assert body["sunroom_url"] == SUNROOM
    assert isinstance(body["log"], list) and len(body["log"]) <= 50


async def test_the_event_stream_starts_with_the_state(app: FastAPI, agent: Agent) -> None:
    stream = agent.hub.stream()
    assert await anext(stream) == b"retry: 2000\n\n"
    agent.publish_state()
    assert (await anext(stream)).startswith(b"event: state\ndata: {")
    await stream.aclose()


# ---------------------------------------------------------------------------- the fake


async def test_the_test_reset_puts_the_pretend_screen_back(
    client: httpx.AsyncClient, agent: Agent, platform: FakePlatform
) -> None:
    agent.save(Config(url=SUNROOM, found="typed"))
    await client.put("/api/screen/display", json={"rotation": 90}, headers=CHANGE)
    await client.post("/api/screen/_test/fake", json={"kind": "desktop"}, headers=CHANGE)
    assert "quit" in (await client.get("/api/screen")).json()["capabilities"]
    assert (await client.post("/api/screen/_test/reset", headers=CHANGE)).status_code == 204
    body = (await client.get("/api/screen")).json()
    assert body["sunroom"] is None and body["platform"] == "pi"
    assert platform.calls == [] and platform.rotation == 0


def test_the_test_routes_exist_only_with_fake(make_agent: Callable[..., Agent]) -> None:
    real = create_app(make_agent(), static=None, test_routes=False, run_agent=False)
    paths = {getattr(route, "path", "") for route in real.routes}
    assert not any(path.startswith("/api/screen/_test") for path in paths)


async def test_the_schema_has_every_route(app: FastAPI) -> None:
    from sunroom_kiosk.cli import main

    assert main(["openapi", "--out", "/dev/null"]) == 0
    from fastapi.openapi.utils import get_openapi

    from sunroom_kiosk.app import router

    paths = get_openapi(title="t", version="0", routes=router.routes)["paths"]
    assert len(paths) == 19
    assert not any("_test" in path for path in paths)
