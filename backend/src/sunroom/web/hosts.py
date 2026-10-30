"""The Host rule (PLAN §13.4, ADR 0017 and 0034), instead of a configured base URL.

By default Sunroom answers to any Host, so ``http://<the server>:8080`` works the moment the
container starts, through any proxy, with nothing to set (ADR 0034).

APP_ALLOWED_HOSTS is an optional lock. Set, every request's Host must be one a household would
use, as before 0.12.0:

* ``localhost`` (and ``*.localhost``), or any IP literal;
* this container's own host name, or any single-label name (``sunroom``, ``nas``);
* a name ending in ``.local``, ``.lan``, ``.home``, ``.home.arpa``, ``.internal`` or ``.ts.net``;
* a name in APP_ALLOWED_HOSTS (exact, or ``*.example.com`` for any name under it).

Anything else then gets 421 with the fix spelled out. The lock is what stops DNS rebinding: a
web page on ``evil.example`` that resolves its name to the server's address still sends
``Host: evil.example``, which is refused, even before setup has a password. Without it, ADR 0034
accepts that such a page could read Sunroom's public pages and leave a name in About's
"Recently reached at"; a household that puts Sunroom on the internet sets the lock.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from sunroom.core.errors import envelope
from sunroom.core.lang import t_en

LAN_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".ts.net", ".localhost")
# Asked by machines, not people: they never go into About's "Recently reached at".
UNNOTED = frozenset({"/api/health", "/api/discover"})


def host_name(host_header: str) -> str:
    """The name in a Host header, lowercased, without the port or IPv6 brackets."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def is_ip_literal(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def own_hostname() -> str:
    """This machine's (the container's) own name, as a Host header would carry it."""
    return socket.gethostname().lower().rstrip(".")


def is_local_name(name: str, own: str) -> bool:
    """A name only the home network uses: ``localhost``, an IP literal, this machine's own name
    ``own``, a single-label name, or one with a LAN suffix. A page on the internet can't send
    one as its Host, even rebound to a home address, which is why the lock trusts these and why
    ``GET /api/discover`` names the household only to them (ADR 0035)."""
    if not name:
        return False
    return (
        name == "localhost"
        or is_ip_literal(name)
        or name == own
        or "." not in name
        or name.endswith(LAN_SUFFIXES)
    )


class HostRule:
    def __init__(
        self,
        allowed: tuple[str, ...],
        *,
        container_hostname: str | None = None,
    ) -> None:
        self.exact = {name for name in allowed if not name.startswith("*.")}
        self.suffixes = tuple(name[1:] for name in allowed if name.startswith("*."))
        own = container_hostname if container_hostname is not None else own_hostname()
        self.own = own.lower().rstrip(".")
        # Only with APP_ALLOWED_HOSTS set: otherwise any name is answered (ADR 0034).
        self.strict = bool(allowed)

    def allows(self, name: str) -> bool:
        if not self.strict:
            return True
        if not name:
            return False
        if is_local_name(name, self.own):
            return True
        return name in self.exact or name.endswith(self.suffixes)


class HostGuard:
    """Refuses requests whose Host the rule doesn't allow; notes the ones it does."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        rule: HostRule,
        note: Callable[[str], None] | None = None,
    ) -> None:
        self.app = app
        self.rule = rule
        self.note = note

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get("host", "")
        name = host_name(header)
        if self.rule.allows(name):
            if self.note is not None and header.strip() and scope.get("path") not in UNNOTED:
                self.note(header.strip().lower())
            await self.app(scope, receive, send)
            return
        shown = name[:80] or "(none)"
        if str(scope.get("path", "")).startswith("/api/"):
            body = json.dumps(
                envelope("unknown_host", "api.host.unknown", {"host": shown})
            ).encode()
            content_type = b"application/json"
        else:
            body = t_en("api.host.unknown", host=shown).encode()
            content_type = b"text/plain; charset=utf-8"
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 421,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
