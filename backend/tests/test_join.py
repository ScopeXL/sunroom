"""Add a phone with a one-time code (PLAN §10.1, §12.2; auth/join.py). Synthetic data only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from structlog.testing import capture_logs

from sunroom.auth import join
from sunroom.auth.models import JoinCode
from sunroom.core.clock import FakeClock
from sunroom.state import AppState
from tests.support import BASE_URL, CSRF, run_setup


@pytest.fixture
async def new_phone(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http:
        yield http


async def make_code(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/auth/join-codes", headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


async def use_code(client: httpx.AsyncClient, code: str) -> httpx.Response:
    return await client.post("/api/auth/join", json={"code": code}, headers=CSRF)


async def test_a_code_signs_in_a_new_phone(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    await run_setup(client)
    made = await make_code(client)
    code = made["code"]
    assert len(code) == 6 and set(code) <= set(join.ALPHABET)
    assert made["display"] == f"{code[:3]} {code[3:]}"
    assert made["url"] == f"{BASE_URL}/join#{code}"
    assert made["expires_at"].startswith("2026-10-07T14:10")

    joined = await use_code(new_phone, code)
    assert joined.status_code == 200, joined.text
    assert joined.json()["member"] is None  # it picks "Who's using this?" next
    assert joined.json()["device_kind"] == "phone"
    assert new_phone.cookies.get("sunroom")
    assert (await new_phone.get("/api/auth/session")).status_code == 200
    devices = (await client.get("/api/auth/devices")).json()
    assert len(devices) == 2


async def test_codes_can_be_typed_loosely(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient
) -> None:
    await run_setup(client)
    code = (await make_code(client))["code"]
    typed = f" {code[:3].lower()}-{code[3:].lower()} "
    assert (await use_code(new_phone, typed)).status_code == 200


async def test_a_code_works_once(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient, app: FastAPI
) -> None:
    await run_setup(client)
    code = (await make_code(client))["code"]
    assert (await use_code(new_phone, code)).status_code == 200
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as third:
        again = await use_code(third, code)
    assert again.status_code == 401
    assert again.json()["error"] == {
        "code": "join_code_invalid",
        "message": "That code didn't work. A code works once, for 10 minutes. Make a new one "
        "on a signed-in device.",
    }


async def test_a_code_lasts_ten_minutes(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient, clock: FakeClock
) -> None:
    await run_setup(client)
    code = (await make_code(client))["code"]
    clock.advance(minutes=10)
    assert (await use_code(new_phone, code)).status_code == 401


async def test_a_new_code_retires_the_last_one(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient
) -> None:
    await run_setup(client)
    old = (await make_code(client))["code"]
    new = (await make_code(client))["code"]
    assert (await use_code(new_phone, old)).status_code == 401
    assert (await use_code(new_phone, new)).status_code == 200


async def test_a_signed_out_phones_code_stops_working(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient
) -> None:
    await run_setup(client)
    code = (await make_code(client))["code"]
    await client.post("/api/auth/logout", headers=CSRF)
    assert (await use_code(new_phone, code)).status_code == 401


async def test_wrong_codes_count_like_wrong_passwords(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient
) -> None:
    await run_setup(client)
    code = (await make_code(client))["code"]
    for guess in ("AAA AAA", "not a code", "BBBBBB", "CCCCCC", "DDDDDD"):
        assert (await use_code(new_phone, guess)).status_code == 401
    limited = await use_code(new_phone, code)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    password = await new_phone.post(
        "/api/auth/login", json={"password": "anything-at-all"}, headers=CSRF
    )
    assert password.status_code == 429


async def test_making_a_code_needs_a_signed_in_phone(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/join-codes", headers=CSRF)
    assert response.status_code == 401


async def test_codes_are_stored_as_hmacs_and_never_logged(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient, app: FastAPI
) -> None:
    await run_setup(client)
    with capture_logs() as logs:
        code = (await make_code(client))["code"]
        await use_code(new_phone, code)
    assert code not in repr(logs)
    state: AppState = app.state.sunroom
    async with state.db.read() as db:
        stored = list(await db.scalars(select(JoinCode.code_hash)))
    assert stored and all(code not in value for value in stored)


async def test_used_and_expired_codes_are_tidied_away(
    client: httpx.AsyncClient, new_phone: httpx.AsyncClient, app: FastAPI, clock: FakeClock
) -> None:
    await run_setup(client)
    await use_code(new_phone, (await make_code(client))["code"])
    await make_code(client)
    state: AppState = app.state.sunroom

    async def count() -> int:
        async with state.db.read() as db:
            return await db.scalar(select(func.count()).select_from(JoinCode)) or 0

    assert await count() == 2
    async with state.db.write() as tx:
        await join.prune(tx.session, clock.now())
    assert await count() == 1  # the used one
    clock.advance(minutes=11)
    async with state.db.write() as tx:
        await join.prune(tx.session, clock.now())
    assert await count() == 0


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("4F7K9Q", "4F7K9Q"),
        ("4f7 k9q", "4F7K9Q"),
        ("4F7-K9Q", "4F7K9Q"),
        ("4F7K9", None),  # too short
        ("4F7K90", None),  # 0 isn't used: it looks like O
        ("", None),
    ],
)
def test_normalize(typed: str, expected: str | None) -> None:
    assert join.normalize(typed) == expected
