"""Pairing the wall screen (PLAN §12.3, auth/kiosk.py). Synthetic data only."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from sunroom.auth import join
from sunroom.auth.models import JoinCode
from sunroom.core.clock import FakeClock
from tests.support import BASE_URL, CSRF, PASSWORD, PIN, set_pin, state_of


async def ask_for_code(screen: httpx.AsyncClient) -> dict[str, Any]:
    response = await screen.post("/api/auth/kiosk/pairings", headers=CSRF)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def poll(screen: httpx.AsyncClient, token: str, wait: int = 0) -> httpx.Response:
    return await screen.get(f"/api/auth/kiosk/pairings/{token}", params={"wait": wait})


async def test_the_screen_needs_setup_first(other: httpx.AsyncClient) -> None:
    response = await other.post("/api/auth/kiosk/pairings", headers=CSRF)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "setup_required"


async def test_a_parent_pairs_the_screen_with_its_code(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    pairing = await ask_for_code(other)
    assert len(pairing["code"]) == 6 and set(pairing["code"]) <= set(join.ALPHABET)
    assert pairing["display"] == f"{pairing['code'][:3]} {pairing['code'][3:]}"
    assert pairing["pair_url"] == f"{BASE_URL}/pair#{pairing['code']}"
    assert pairing["expires_in"] == 600
    waiting = await poll(other, pairing["poll_token"])
    assert waiting.json() == {"status": "waiting", "session": None}

    claimed = await parent.post(
        "/api/auth/kiosk/pair",
        json={"code": pairing["display"].lower(), "label": "Wall screen"},
        headers=CSRF,
    )
    assert claimed.status_code == 201, claimed.text
    paired = await poll(other, pairing["poll_token"])
    body = paired.json()
    assert body["status"] == "paired"
    assert body["session"]["device_kind"] == "kiosk"
    assert body["session"]["device_label"] == "Wall screen"
    assert body["session"]["member"] is None  # the screen is everyone's
    assert "sunroom=v1." in paired.headers["set-cookie"]
    assert (await other.get("/api/auth/session")).json()["device_kind"] == "kiosk"
    # The poll token is spent once the screen has its sign-in.
    assert (await poll(other, pairing["poll_token"])).json()["status"] == "expired"


async def test_the_long_poll_wakes_when_the_code_is_claimed(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    pairing = await ask_for_code(other)
    waiting = asyncio.create_task(poll(other, pairing["poll_token"], wait=5))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await parent.post("/api/auth/kiosk/pair", json={"code": pairing["code"]}, headers=CSRF)
    response = await asyncio.wait_for(waiting, timeout=2)
    assert response.json()["status"] == "paired"
    assert state_of(app).pairing_waiters == {}


async def test_a_code_is_good_for_ten_minutes_and_once(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, clock: FakeClock
) -> None:
    pairing = await ask_for_code(other)
    clock.advance(minutes=10)
    assert (await poll(other, pairing["poll_token"])).json()["status"] == "expired"
    late = await parent.post("/api/auth/kiosk/pair", json={"code": pairing["code"]}, headers=CSRF)
    assert late.status_code == 401
    assert late.json()["error"]["message"] == (
        "That code didn't work. Codes change every 10 minutes; read the one on the screen now."
    )
    fresh = await ask_for_code(other)
    assert (
        await parent.post("/api/auth/kiosk/pair", json={"code": fresh["code"]}, headers=CSRF)
    ).status_code == 201
    again = await parent.post("/api/auth/kiosk/pair", json={"code": fresh["code"]}, headers=CSRF)
    assert again.status_code == 401


async def test_a_phone_code_doesnt_pair_a_screen(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    phone_code = (await parent.post("/api/auth/join-codes", headers=CSRF)).json()["code"]
    response = await parent.post("/api/auth/kiosk/pair", json={"code": phone_code}, headers=CSRF)
    assert response.status_code == 401


async def test_only_a_parent_claims_a_code(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, app: FastAPI
) -> None:
    await set_pin(parent)
    kid_phone = (
        await other.post("/api/auth/login", json={"password": PASSWORD}, headers=CSRF)
    ).json()["device_id"]
    await parent.patch(f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as screen:
        pairing = await ask_for_code(screen)
        refused = await other.post(
            "/api/auth/kiosk/pair", json={"code": pairing["code"]}, headers=CSRF
        )
        assert refused.status_code == 403
        await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
        allowed = await other.post(
            "/api/auth/kiosk/pair", json={"code": pairing["code"]}, headers=CSRF
        )
        assert allowed.status_code == 201


async def test_pairing_with_the_password_on_the_screen(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    wrong = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": "not it at all"}, headers=CSRF
    )
    assert wrong.status_code == 401
    paired = await other.post(
        "/api/auth/kiosk/pair-with-password",
        json={"password": PASSWORD, "label": "Hallway"},
        headers=CSRF,
    )
    assert paired.status_code == 200
    assert paired.json()["device_kind"] == "kiosk"
    renamed = await other.put("/api/auth/device/label", json={"label": "Kitchen"}, headers=CSRF)
    assert renamed.json()["device_label"] == "Kitchen"


async def test_a_claimed_code_survives_until_the_screen_collects_it(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient, clock: FakeClock
) -> None:
    """A tidy-up between the claim and the screen's next poll must not strand the screen."""
    pairing = await ask_for_code(other)
    await parent.post("/api/auth/kiosk/pair", json={"code": pairing["code"]}, headers=CSRF)
    state = state_of(app)
    async with state.db.write() as tx:
        await join.prune(tx.session, clock.now())
    assert (await poll(other, pairing["poll_token"])).json()["status"] == "paired"
    async with state.db.write() as tx:
        await join.prune(tx.session, clock.now())
    async with state.db.read() as db:
        assert list(await db.scalars(select(JoinCode))) == []
