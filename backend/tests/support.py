"""Helpers shared by the tests (constants, settings builder, setup and sign-in, an SSE probe)."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from PIL import Image

from sunroom.core.config import Settings
from sunroom.state import AppState

PASSWORD = "test-household-passphrase"
SECRET = "test-secret-key-" + "0" * 32
CSRF = {"x-sunroom": "1"}
BASE_URL = "http://localhost:7867"
ENV_PREFIXES = ("APP_", "SUNROOM_", "DATA_DIR")
ENV_NAMES = {"TZ", "PORT", "LOG_LEVEL"}
PIN = "2468"


def make_settings(data_dir: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_secret_key": SECRET,
        "tz": "America/New_York",
        "data_dir": str(data_dir),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def state_of(app: FastAPI) -> AppState:
    state: AppState = app.state.sunroom
    return state


async def run_setup(
    client: httpx.AsyncClient, password: str = PASSWORD, **extra: Any
) -> httpx.Response:
    body = {"password": password, "household_name": "Sample Family", "timezone": "America/New_York"}
    return await client.post("/api/setup", json=body | extra, headers=CSRF)


async def login(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/login", json={"password": password}, headers=CSRF)


async def add_member(
    client: httpx.AsyncClient, name: str, role: str = "parent", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/members", json={"name": name, "role": role} | extra, headers=CSRF
    )
    assert response.status_code == 201, response.text
    member: dict[str, Any] = response.json()
    return member


async def set_pin(client: httpx.AsyncClient, pin: str = PIN) -> None:
    response = await client.put("/api/auth/pin", json={"pin": pin}, headers=CSRF)
    assert response.status_code == 204, response.text


def picture(size: tuple[int, int] = (64, 48), fmt: str = "JPEG", **save: Any) -> bytes:
    """A synthetic photo (a flat color), so no real picture is ever in the tests."""
    out = io.BytesIO()
    Image.new("RGB", size, (200, 170, 90)).save(out, fmt, **save)
    return out.getvalue()


def session_cookie(client: httpx.AsyncClient) -> str:
    value = client.cookies.get("sunroom")
    assert value, "not signed in"
    return f"sunroom={value}"


# ---- a hand-written ASGI harness for streaming responses ------------------------------------
# httpx's ASGITransport waits for the whole response body, so it can't read an endless SSE
# stream. This drives the app directly and exposes the frames as they are sent.


@dataclass
class StreamProbe:
    app: FastAPI
    path: str = "/api/events"
    query: str = ""
    cookie: str | None = None
    extra_headers: list[tuple[bytes, bytes]] = field(default_factory=list[tuple[bytes, bytes]])
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    _body: str = ""
    _messages: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue[dict[str, Any]]()
    )
    _disconnect: asyncio.Event = field(default_factory=asyncio.Event)
    _requested: bool = False
    _task: asyncio.Task[None] | None = None

    def start(self) -> StreamProbe:
        headers = [(b"host", b"localhost:7867"), *self.extra_headers]
        if self.cookie:
            headers.append((b"cookie", self.cookie.encode()))
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": self.query.encode(),
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("localhost", 7867),
        }

        async def receive() -> dict[str, Any]:
            if not self._requested:
                self._requested = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await self._disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            await self._messages.put(message)

        self._task = asyncio.create_task(self.app(scope, receive, send))  # pyright: ignore[reportArgumentType]
        return self

    async def _pump(self, within_s: float) -> bool:
        try:
            message = await asyncio.wait_for(self._messages.get(), timeout=within_s)
        except TimeoutError:
            return False
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            self._body += message.get("body", b"").decode()
        return True

    async def wait_started(self, within_s: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + within_s
        while self.status is None:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 or not await self._pump(remaining):
                raise AssertionError("stream never started")

    def frames(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for block in self._body.split("\n\n"):
            data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
            if data_lines:
                event = json.loads("\n".join(data_lines))
                ids = [line[4:] for line in block.splitlines() if line.startswith("id: ")]
                if ids:
                    event["_id"] = ids[0]
                out.append(event)
        return out

    def raw(self) -> str:
        return self._body

    async def wait_for(
        self, predicate: Callable[[list[dict[str, Any]]], bool], within_s: float = 2.0
    ) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + within_s
        while True:
            frames = self.frames()
            if predicate(frames):
                return frames
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError(f"condition not met; frames so far: {frames}")
            await self._pump(remaining)

    async def finished(self, within_s: float = 2.0) -> bool:
        assert self._task is not None
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=within_s)
        except TimeoutError:
            return False
        while not self._messages.empty():
            await self._pump(0.01)
        return True

    async def close(self) -> None:
        self._disconnect.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except TimeoutError:
                self._task.cancel()


async def startup_backup_done(app: FastAPI) -> None:
    """Wait for the copy the app's first nightly-backup tick writes (the FakeClock's 14:00 UTC is
    past 03:30 in the household's zone and a fresh data dir has no copy yet), which runs in a thread
    and, when it finishes, sets ``last_success_at`` and clears ``last_error``: a test that sets
    either first can see them overwritten mid-test."""
    backups = state_of(app).backups
    deadline = asyncio.get_running_loop().time() + 10.0
    while backups.status()["busy"] or (backups.last_success_at is None and backups.due()):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the startup backup never finished")
        await asyncio.sleep(0.01)
