"""Finding a Sunroom on the network (docs/M7.md, "Finding a Sunroom on the network").

Two ways, side by side, for about five seconds:

1. **DNS-SD**: Sunroom servers that announce ``_sunroom._tcp`` (an all-in-one Pi does, through
   the avahi file ``kiosk/install.sh`` writes; a NAS can, with the four lines in KIOSK.md).
2. **A sweep of this screen's own networks**: every address in each IPv4 subnet (at most 1024 of
   them), ``GET /api/discover`` on ports 8080 (Sunroom's own), 80 and 443, with 300 ms to
   connect and 64 at a time. That finds the default Compose setup; a proxy that routes by name
   isn't found, and its household types the address instead.

Every hit is confirmed with ``GET /api/discover`` ({sunroom, id, version, setup_complete, name,
url}). A server older than that route is recognised by ``/api/setup/status`` and listed as "a
Sunroom" with its version. Only this screen's own subnets are touched.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from sunroom_kiosk import logs
from sunroom_kiosk.words import SaidError

log = logs.get("discovery")

SERVICE = "_sunroom._tcp.local."
PORTS: tuple[tuple[int, str], ...] = ((8080, "http"), (80, "http"), (443, "https"))
CONNECT_S = 0.3
READ_S = 3.0
IN_FLIGHT = 64
MOST_HOSTS = 1024
BROWSE_S = 5.0
USER_AGENT = "sunroom-kiosk"


@dataclass(frozen=True)
class Found:
    url: str
    id: str | None
    name: str | None
    version: str | None
    setup_complete: bool | None
    older: bool = False  # no /api/discover: a Sunroom before 0.13.0
    advertised: str | None = None  # the server's own idea of its address (SUNROOM_ADVERTISED_URL)
    language: str | None = None  # the household's, once it's set up (ADR 0043)


class CheckFailedError(SaidError):
    """The address isn't a Sunroom, or can't be reached; what it says says which, plainly."""


def candidates(text: str) -> list[str]:
    """The addresses to try for what someone typed: as typed with a scheme, else https first
    for a name and http first for a number or a ``.local`` name, each without a trailing slash.
    """
    typed = text.strip().rstrip("/")
    if not typed or any(c.isspace() for c in typed):
        return []
    if "://" in typed:
        scheme = typed.split("://", 1)[0].lower()
        return [typed] if scheme in ("http", "https") else []
    host = urlsplit(f"//{typed}").hostname or ""
    local = host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host
    try:
        ipaddress.ip_address(host)
        local = True
    except ValueError:
        pass
    first, second = ("http", "https") if local else ("https", "http")
    return [f"{first}://{typed}", f"{second}://{typed}"]


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _found_from(url: str, body: Any) -> Found | None:
    if not isinstance(body, dict):
        return None
    fields = cast(dict[str, Any], body)
    if fields.get("sunroom") is not True:
        return None

    def text(key: str) -> str | None:
        value = fields.get(key)
        return value if isinstance(value, str) and value else None

    complete = fields.get("setup_complete")
    advertised = text("url")
    return Found(
        url=url,
        id=text("id"),
        name=text("name"),
        version=text("version"),
        setup_complete=complete if isinstance(complete, bool) else None,
        advertised=advertised.rstrip("/") if advertised else None,
        language=text("language"),
    )


async def _json(client: httpx.AsyncClient, url: str) -> tuple[int, Any]:
    response = await client.get(url, headers={"Accept": "application/json"})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


async def probe(client: httpx.AsyncClient, base: str) -> Found | None:
    """Whether ``base`` is a Sunroom: its ``/api/discover``, else the older pair of routes.
    None for anything else; network errors propagate."""
    base = base.rstrip("/")
    status, body = await _json(client, f"{base}/api/discover")
    if status == 200:
        return _found_from(base, body)
    if status != 404:
        return None
    status, body = await _json(client, f"{base}/api/setup/status")
    if status != 200 or not isinstance(body, dict):
        return None
    fields = cast(dict[str, Any], body)
    if not isinstance(fields.get("setup_complete"), bool) or "advertised_url" not in fields:
        return None
    version = fields.get("version")
    return Found(
        url=base,
        id=None,
        name=None,
        version=version if isinstance(version, str) else None,
        setup_complete=bool(fields["setup_complete"]),
        older=True,
    )


async def check(client: httpx.AsyncClient, typed: str) -> Found:
    """What someone typed, checked: the Sunroom there, or CheckFailedError saying why not."""
    tries = candidates(typed)
    if not tries:
        raise CheckFailedError("agent.find.not_an_address")
    unreachable = False
    for url in tries:
        try:
            found = await probe(client, url)
        except httpx.HTTPError:
            unreachable = True
            continue
        if found is not None:
            return found
        # Something answered, and it isn't a Sunroom: no point trying the other scheme.
        raise CheckFailedError("agent.find.not_sunroom")
    raise CheckFailedError("agent.find.unreachable" if unreachable else "agent.find.not_sunroom")


def subnets(addresses: Iterable[tuple[str, int]]) -> list[ipaddress.IPv4Network]:
    """This screen's IPv4 networks from (address, prefix length) pairs: loopback and link-local
    left out, and anything bigger than 1024 addresses cut to the 1024 around this screen."""
    seen: list[ipaddress.IPv4Network] = []
    for address, prefix in addresses:
        try:
            ip = ipaddress.IPv4Address(address)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            continue
        prefix = max(prefix, 32 - (MOST_HOSTS.bit_length() - 1))  # 1024 hosts: at least a /22
        network = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        if network not in seen:
            seen.append(network)
    return seen


def interface_addresses() -> list[tuple[str, int]]:
    """Every IPv4 address this machine has, with its prefix length (ifaddr, through zeroconf)."""
    import ifaddr  # here, not at the top: only a real scan needs it

    pairs: list[tuple[str, int]] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                pairs.append((ip.ip, ip.network_prefix))
    return pairs


def targets(networks: Sequence[ipaddress.IPv4Network]) -> list[str]:
    """Each host in the networks on each port, as base addresses: ``http://192.168.1.7:8080``."""
    bases: list[str] = []
    for network in networks:
        hosts = list(network.hosts()) if network.prefixlen < 31 else list(network)
        for host in hosts:
            for port, scheme in PORTS:
                default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
                bases.append(f"{scheme}://{host}" if default else f"{scheme}://{host}:{port}")
    return bases


async def sweep(
    client: httpx.AsyncClient, bases: Sequence[str], on_found: Callable[[Found], Awaitable[None]]
) -> None:
    gate = asyncio.Semaphore(IN_FLIGHT)

    async def one(base: str) -> None:
        async with gate:
            try:
                found = await probe(client, base)
            except httpx.HTTPError:
                return
            except Exception as error:  # a surprise from one host never stops the sweep
                log.debug("The sweep's look at %s failed: %r", base, error)
                return
        if found is not None:
            await on_found(found)

    await asyncio.gather(*(one(base) for base in bases))


async def browse(seconds: float = BROWSE_S) -> list[str]:
    """Base addresses of every ``_sunroom._tcp`` service announced in ``seconds``."""
    # Here, not at the top: only a real scan needs them.
    from zeroconf import ServiceStateChange, Zeroconf
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    names: list[str] = []

    def changed(
        zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if state_change is ServiceStateChange.Added and name not in names:
            names.append(name)

    bases: list[str] = []
    zc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(zc.zeroconf, SERVICE, handlers=[changed])
        await asyncio.sleep(seconds)
        await browser.async_cancel()
        for name in names:
            info = AsyncServiceInfo(SERVICE, name)
            if not await info.async_request(zc.zeroconf, 1500) or not info.port:
                continue
            for address in info.parsed_addresses():
                if ":" in address:
                    continue  # IPv4 only, as the sweep
                scheme = "https" if info.port == 443 else "http"
                bases.append(f"{scheme}://{address}:{info.port}")
    except OSError as error:
        log.info("Looking for announced Sunrooms didn't work here: %s.", error)
    finally:
        await zc.async_close()
    return bases


CHECK_CONNECT_S = 5.0  # a typed address may be across the internet


def new_client(connect: float = CONNECT_S) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(READ_S, connect=connect),
        limits=httpx.Limits(max_connections=IN_FLIGHT, max_keepalive_connections=8),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )


type Publish = Callable[[str, Any], None]


class Discovery:
    """The scans (one at a time) and what the last one found. Results also go out as
    ``discovery.found`` events while it runs, then ``discovery.done``."""

    def __init__(
        self,
        publish: Publish,
        *,
        client: Callable[..., httpx.AsyncClient] = new_client,
        addresses: Callable[[], list[tuple[str, int]]] = interface_addresses,
        announced: Callable[[float], Awaitable[list[str]]] = browse,
    ) -> None:
        self.publish = publish
        self.client = client
        self.addresses = addresses
        self.announced = announced
        self.found: list[Found] = []
        self.scanning = False
        self._lock = asyncio.Lock()

    def _keep(self, found: Found) -> bool:
        """Add ``found`` unless the same Sunroom is already there (by id, else by address)."""
        for known in self.found:
            if (found.id is not None and known.id == found.id) or known.url == found.url:
                return False
        self.found.append(found)
        return True

    async def scan(self) -> list[Found]:
        async with self._lock:
            self.scanning = True
            self.found = []
            self.publish("discovery.started", {})
            try:
                async with self.client() as client:

                    async def hit(found: Found) -> None:
                        better = await self._advertised(client, found)
                        if self._keep(better):
                            log.info("Found a Sunroom at %s.", better.url)
                            self.publish("discovery.found", found_out(better))

                    networks = subnets(self.addresses())
                    bases = targets(networks)
                    log.info(
                        "Looking for Sunroom on %s.",
                        ", ".join(str(n) for n in networks) or "no network",
                    )
                    announced = asyncio.ensure_future(self.announced(BROWSE_S))
                    await sweep(client, bases, hit)
                    await sweep(client, await announced, hit)
            finally:
                self.scanning = False
                self.publish("discovery.done", {"count": len(self.found)})
            return list(self.found)

    async def _advertised(self, client: httpx.AsyncClient, found: Found) -> Found:
        """The server's own idea of its address (SUNROOM_ADVERTISED_URL), when this screen can
        reach it and it is the same Sunroom: a name outlasts a number the router hands out."""
        if found.advertised is None or found.advertised == found.url or found.id is None:
            return found
        try:
            there = await probe(client, found.advertised)
        except httpx.HTTPError:
            return found
        return there if there is not None and there.id == found.id else found

    async def check(self, typed: str) -> Found:
        """What someone typed (or a saved address), checked with time to connect."""
        async with self.client(connect=CHECK_CONNECT_S) as client:
            return await check(client, typed)

    async def refind(self, sunroom_id: str) -> Found | None:
        for found in await self.scan():
            if found.id == sunroom_id:
                return found
        return None


def found_out(found: Found) -> dict[str, Any]:
    """A Found as the API's ScreenFoundOut."""
    return {
        "url": found.url,
        "id": found.id,
        "name": found.name,
        "version": found.version,
        "setup_complete": found.setup_complete,
        "older": found.older,
    }


async def _announced_by_nobody(seconds: float) -> list[str]:
    return []


# ``--fake``'s made-up older Sunroom: TEST-NET-2, an address no network uses, so nothing real is
# ever asked about it.
OLDER = Found(
    url="http://198.51.100.21:8080",
    id=None,
    name=None,
    version="0.11.0",
    setup_complete=True,
    older=True,
)


class FakeDiscovery(Discovery):
    """``--fake``: finds the Sunrooms it is given (asked for real, so the e2e server answers as
    itself) and a made-up older one; never sweeps a network."""

    def __init__(self, publish: Publish, urls: Iterable[str]) -> None:
        super().__init__(publish, addresses=lambda: [], announced=_announced_by_nobody)
        self.urls = [url.rstrip("/") for url in urls]
        self.pause_s = 0.3  # results arrive one after another, as on a network

    async def scan(self) -> list[Found]:
        async with self._lock:
            self.scanning = True
            self.found = []
            self.publish("discovery.started", {})
            try:
                async with self.client(connect=CHECK_CONNECT_S) as client:
                    for url in self.urls:
                        await asyncio.sleep(self.pause_s)
                        try:
                            found = await probe(client, url)
                        except httpx.HTTPError:
                            continue
                        if found is not None and self._keep(found):
                            self.publish("discovery.found", found_out(found))
                await asyncio.sleep(self.pause_s)
                if self._keep(OLDER):
                    self.publish("discovery.found", found_out(OLDER))
            finally:
                self.scanning = False
                self.publish("discovery.done", {"count": len(self.found)})
            return list(self.found)

    async def check(self, typed: str) -> Found:
        if typed.strip().rstrip("/") == OLDER.url:
            return OLDER
        return await super().check(typed)
