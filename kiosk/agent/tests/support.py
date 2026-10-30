"""What the agent's tests share: the pretend Sunroom servers discovery and the health checks
talk to (httpx.MockTransport, by base address), and the addresses they use. Synthetic data only."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from sunroom_kiosk.platform.base import CommandResult
from sunroom_kiosk.platform.windows import BIOS_KEY, RegistryKind

PORT = 7800
AGENT = f"http://127.0.0.1:{PORT}"
SUNROOM = "http://192.168.1.20:8080"
SUNROOM_ID = "00000000-0000-7000-8000-0000000000e1"
CHANGE = {"X-Sunroom-Screen": "1"}


class FakeSunrooms:
    """Pretend servers by base address: a new one (``/api/discover``), an older one (only
    ``/api/setup/status``), something else, and nothing at all for every other address."""

    def __init__(self) -> None:
        self.new: dict[str, dict[str, Any]] = {
            SUNROOM: {
                "sunroom": True,
                "id": SUNROOM_ID,
                "version": "0.13.0",
                "setup_complete": True,
                "name": "The Sample Family",
                "url": None,
            }
        }
        self.older: dict[str, str] = {}  # base -> version
        self.other: set[str] = set()  # answers, but isn't a Sunroom
        self.healthy: set[str] = {SUNROOM}
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        base = f"{request.url.scheme}://{request.url.netloc.decode()}"
        path = request.url.path
        self.asked.append(f"{base}{path}")
        if base in self.new:
            if path == "/api/discover":
                return httpx.Response(200, json=self.new[base])
            if path == "/api/health":
                ok = base in self.healthy
                return httpx.Response(200 if ok else 503, json={"status": "ok" if ok else "x"})
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if base in self.older:
            if path == "/api/setup/status":
                body = {
                    "setup_complete": True,
                    "password_from_env": False,
                    "server_timezone": None,
                    "advertised_url": base,
                    "version": self.older[base],
                }
                return httpx.Response(200, content=json.dumps(body).encode())
            if path == "/api/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404, json={"detail": "Not Found"})
        if base in self.other:
            return httpx.Response(200, text="<html>Sample router page</html>")
        raise httpx.ConnectError("nothing answers there", request=request)

    def client(self, connect: float = 0.3) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@dataclass
class Shell:
    """Answers command lines by their start; records each with what went to its stdin."""

    answers: dict[str, CommandResult] = field(default_factory=dict[str, CommandResult])
    calls: list[tuple[list[str], str | None]] = field(
        default_factory=list[tuple[list[str], str | None]]
    )

    async def __call__(
        self, argv: Sequence[str], *, limit: float = 20.0, stdin: str | None = None
    ) -> CommandResult:
        line = " ".join(argv)
        self.calls.append((list(argv), stdin))
        for start, result in self.answers.items():
            if line.startswith(start):
                return result
        return CommandResult(0, "")

    def lines(self) -> list[str]:
        return [" ".join(argv) for argv, _ in self.calls]


def ok(output: str = "") -> CommandResult:
    return CommandResult(0, output)


@dataclass
class FakeRegistry:
    """HKEY_CURRENT_USER as {key: {name: (kind, data)}}, and the firmware's two names."""

    keys: dict[str, dict[str, tuple[RegistryKind, int | str]]] = field(
        default_factory=dict[str, dict[str, tuple[RegistryKind, int | str]]]
    )
    machine: dict[str, str] = field(default_factory=dict[str, str])

    def set_value(self, key: str, name: str, kind: RegistryKind, data: int | str) -> None:
        self.keys.setdefault(key, {})[name] = (kind, data)

    def user_value(self, key: str, name: str) -> str | None:
        found = self.keys.get(key, {}).get(name)
        return None if found is None else str(found[1])

    def delete_value(self, key: str, name: str) -> None:
        self.keys.get(key, {}).pop(name, None)

    def delete_key(self, key: str) -> None:
        self.keys.pop(key, None)

    def machine_value(self, key: str, name: str) -> str | None:
        assert key == BIOS_KEY
        return self.machine.get(name)
