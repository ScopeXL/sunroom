"""Outbound URL checks (PLAN §12.6): every address the server fetches is classified first.

Calendar feeds, CalDAV servers and photo libraries are URLs a household member types. Without a
check, one of them could point the server at something on the home network it shouldn't touch
(a router's admin page, another container). So:

* only http and https, never a ``user:pass@`` part;
* the host is resolved, and any address that isn't public (loopback, link-local, RFC 1918, ULA,
  carrier-grade NAT, multicast, reserved) makes the target *private*;
* a private target is allowed only when the account opted in ("This server is on your home
  network") **and** the host or one of its addresses is on the network allowlist, or
  SUNROOM_ALLOW_PRIVATE_URLS is on. A parent's tick writes the host into the allowlist itself
  (``ctx.network``, ADR 0036), and the row goes with the account or source;
* the connection is pinned to an address that was checked (core/http.py), so DNS can't change
  its answer between the check and the request.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from sunroom.core.lang import Words, plain, t_en

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]
AllowlistProvider = Callable[[], Awaitable[Sequence[str]]]


class OutboundError(Exception):
    """A fetch that won't be made, with a plain-English reason a parent can act on: ``key``
    names it in ``lang/en.json`` (``api.network.*``), and ``message`` is its English."""

    def __init__(self, code: str, key: str, **params: object) -> None:
        self.code = code
        self.key = key
        self.params = plain(params)
        self.message = t_en(key, **self.params)
        super().__init__(self.message)

    @property
    def words(self) -> Words:
        return Words(self.key, self.params)


@dataclass(frozen=True, slots=True)
class Target:
    url: SplitResult
    host: str
    port: int
    addresses: tuple[IPAddress, ...]
    private: bool

    @property
    def is_ip_literal(self) -> bool:
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            return False
        return True


async def system_resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        address = str(sockaddr[0])
        if address not in seen:
            seen.append(address)
    return seen


def is_public(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_global
    return address.is_global and not address.is_multicast


def _matches(entry: str, host: str, addresses: Sequence[IPAddress]) -> bool:
    entry = entry.strip().lower()
    if not entry:
        return False
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return entry.rstrip(".") == host
    return any(address in network for address in addresses)


class NetGuard:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolve,
        allowlist: AllowlistProvider | None = None,
        allow_private_everywhere: bool = False,
    ) -> None:
        self._resolve = resolver
        self._allowlist = allowlist
        self._allow_private_everywhere = allow_private_everywhere

    async def check(self, url: str, *, allow_private: bool = False) -> Target:
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError:
            raise OutboundError("bad_address", "api.network.bad_address") from None
        if parts.scheme not in {"http", "https"}:
            raise OutboundError("bad_address", "api.network.http_only")
        if parts.username is not None or parts.password is not None:
            raise OutboundError("bad_address", "api.network.no_password_in_address")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise OutboundError("bad_address", "api.network.no_server")
        port = port or (443 if parts.scheme == "https" else 80)
        addresses = await self._addresses(host, port)
        private = not all(is_public(address) for address in addresses)
        if private and not (allow_private and await self._private_allowed(host, addresses)):
            raise OutboundError("private_address", "api.network.private")
        return Target(parts, host, port, tuple(addresses), private)

    async def _addresses(self, host: str, port: int) -> list[IPAddress]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            found = await self._resolve(host, port)
        except OSError:
            found = []
        addresses: list[IPAddress] = []
        for value in found:
            try:
                addresses.append(ipaddress.ip_address(value.split("%", 1)[0]))
            except ValueError:
                continue
        if not addresses:
            raise OutboundError("not_found", "api.network.not_found")
        return addresses

    async def _private_allowed(self, host: str, addresses: Sequence[IPAddress]) -> bool:
        if self._allow_private_everywhere:
            return True
        if self._allowlist is None:
            return False
        entries = await self._allowlist()
        return any(_matches(entry, host, addresses) for entry in entries)
