"""The one place an outbound HTTP client is made (PLAN §12.6). A test fails if any other module
constructs ``httpx.AsyncClient(``.

Every request goes through core/netguard first. The connection is then pinned to an address the
guard checked: the URL's host is swapped for that IP, while the ``Host`` header and the TLS
server name (httpcore's ``sni_hostname``) keep the real name, so certificates still verify.
Redirects are followed by hand, at most three, and each hop is checked again; credentials
(``Authorization``, cookies, a photo library's ``X-Api-Key``) never follow a redirect to another
server. Bodies are capped; a
response bigger than its cap is refused rather than truncated.

A fresh client per request, on purpose: connections pinned by IP must never be pooled across
host names (two sites on one address would share a TLS session with the wrong name).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from sunroom.core.netguard import NetGuard, OutboundError, Target
from sunroom.core.version import build_info

CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0
MAX_REDIRECTS = 3
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

TransportFactory = Callable[[], httpx.AsyncBaseTransport]
# Never sent on to another server by a redirect: a password, a cookie, or a photo library's API
# key (Immich's), which would otherwise follow a redirect wherever it pointed.
CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key"})


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: int
    headers: httpx.Headers
    content: bytes
    url: str  # the final URL, after redirects (with its real host name)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        return self.content.decode(self._charset(), errors="replace")

    def _charset(self) -> str:
        content_type = self.headers.get("content-type", "")
        for part in content_type.split(";")[1:]:
            name, _, value = part.strip().partition("=")
            if name.lower() == "charset" and value:
                return value.strip('"')
        return "utf-8"


def _pinned_url(target: Target) -> str:
    address = target.addresses[0]
    host = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)
    netloc = f"{host}:{target.port}"
    parts = target.url
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    return scheme, (parts.hostname or "").lower(), port or (443 if scheme == "https" else 80)


def _host_header(target: Target) -> str:
    default = 443 if target.url.scheme == "https" else 80
    host = f"[{target.host}]" if ":" in target.host else target.host
    return host if target.port == default else f"{host}:{target.port}"


class GuardedHttp:
    def __init__(
        self, guard: NetGuard, *, transport_factory: TransportFactory | None = None
    ) -> None:
        self._guard = guard
        self._transport_factory = transport_factory
        self.user_agent = f"Sunroom/{build_info().version} (+self-hosted family calendar)"

    async def request(
        self,
        method: str,
        url: str,
        *,
        allow_private: bool = False,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        follow_redirects: bool = True,
    ) -> FetchResult:
        current = url
        origin = _origin(url)
        send: dict[str, str] = dict(headers) if headers else {}
        for _hop in range(MAX_REDIRECTS + 1):
            target = await self._guard.check(current, allow_private=allow_private)
            response = await self._send(method, target, send, content, max_bytes)
            location = response.headers.get("location")
            if follow_redirects and response.status in REDIRECT_CODES and location:
                current = urljoin(current, location)
                if _origin(current) != origin:
                    # A password or cookie meant for one server never goes to another.
                    send = {k: v for k, v in send.items() if k.lower() not in CREDENTIAL_HEADERS}
                if response.status == 303 or (
                    response.status in {301, 302} and method.upper() == "POST"
                ):
                    method, content = "GET", None
                continue
            return FetchResult(response.status, response.headers, response.content, current)
        raise OutboundError("too_many_redirects", "api.network.too_many_redirects")

    async def get(
        self,
        url: str,
        *,
        allow_private: bool = False,
        headers: Mapping[str, str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> FetchResult:
        return await self.request(
            "GET", url, allow_private=allow_private, headers=headers, max_bytes=max_bytes
        )

    async def _send(
        self,
        method: str,
        target: Target,
        headers: Mapping[str, str] | None,
        content: bytes | None,
        max_bytes: int,
    ) -> _Raw:
        send_headers = {"User-Agent": self.user_agent, **(headers or {})}
        send_headers["Host"] = _host_header(target)
        extensions: dict[str, object] = {}
        if target.url.scheme == "https" and not target.is_ip_literal:
            extensions["sni_hostname"] = target.host
        timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        transport = self._transport_factory() if self._transport_factory else None
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                request = client.build_request(
                    method,
                    _pinned_url(target),
                    headers=send_headers,
                    content=content,
                    extensions=extensions,
                )
                response = await client.send(request, stream=True)
                try:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            raise OutboundError("too_large", "api.network.too_large")
                    return _Raw(response.status_code, response.headers, bytes(body))
                finally:
                    await response.aclose()
        except httpx.TimeoutException:
            raise OutboundError("timeout", "api.network.timeout") from None
        except httpx.TransportError:
            raise OutboundError("unreachable", "api.network.unreachable") from None


@dataclass(frozen=True, slots=True)
class _Raw:
    status: int
    headers: httpx.Headers
    content: bytes
