"""CalDAV for iCloud and other servers (PLAN §8.1, ADR 0005): discovery (RFC 6764), changes by
sync-collection (RFC 6578) or an etag listing, reads by calendar-multiget, and writes with
If-Match (RFC 4791).

A small client of our own rather than a library, because every request has to go through the
plugin's guarded HTTP client (PLAN §12.6): it checks each address, pins the connection to it,
follows at most three redirects (checking each one) and caps the size. This module only writes
requests and reads replies.

* Hrefs come back percent-encoded, relative or absolute, and on whatever host the server picks
  (iCloud keeps calendars on a ``pNN-caldav`` host that discovery finds; nothing here names it).
  Each one is resolved against the URL it came from and returned in one canonical spelling, so a
  resource keeps one id however a server chooses to spell it.
* Failures become ``SyncError`` with a plain-English message that never carries a URL or the
  password. The password only travels in the Basic header, which is built for each request.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol
from urllib.parse import quote, unquote, unquote_to_bytes, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, ParseError, TreeBuilder, XMLParser
from xml.sax.saxutils import escape

from sunroom.core.http import FetchResult
from sunroom.core.logging import get_logger
from sunroom.core.netguard import OutboundError
from sunroom.plugins.calendar_sync.providers.base import ErrorKind, RemoteCalendar, SyncError

log = get_logger(__name__)

CALDAV_MAX_BYTES = 50 * 1024 * 1024  # PLAN §12.6
MULTIGET_BATCH = 50
SYNC_ROUNDS = 20  # a truncated sync-collection reply (507) is continued at most this often
NAME_MAX = 120  # characters in a new resource's name, before ".ics"

DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
CS = "http://calendarserver.org/ns/"
APPLE = "http://apple.com/ns/ical/"

# Replies use any prefixes they like, so elements are matched by namespace URI (Clark notation).
_MULTISTATUS = "{DAV:}multistatus"
_RESPONSE = "{DAV:}response"
_HREF = "{DAV:}href"
_STATUS = "{DAV:}status"
_PROPSTAT = "{DAV:}propstat"
_PROP = "{DAV:}prop"
_ERROR = "{DAV:}error"
_CURRENT_USER_PRINCIPAL = "{DAV:}current-user-principal"
_RESOURCETYPE = "{DAV:}resourcetype"
_DISPLAYNAME = "{DAV:}displayname"
_PRIVILEGES = "{DAV:}current-user-privilege-set"
_PRIVILEGE = "{DAV:}privilege"
_GETETAG = "{DAV:}getetag"
_GETCONTENTTYPE = "{DAV:}getcontenttype"
_SYNC_TOKEN = "{DAV:}sync-token"  # noqa: S105 - an element name, not a secret
_VALID_SYNC_TOKEN = "{DAV:}valid-sync-token"  # noqa: S105 - an element name
_SUPPORTED_REPORT = "{DAV:}supported-report"
_WRITE_PRIVILEGES = frozenset({"{DAV:}write", "{DAV:}write-content", "{DAV:}bind", "{DAV:}all"})
_CALENDAR = f"{{{CALDAV}}}calendar"
_CALENDAR_HOME_SET = f"{{{CALDAV}}}calendar-home-set"
_COMPONENT_SET = f"{{{CALDAV}}}supported-calendar-component-set"
_COMP = f"{{{CALDAV}}}comp"
_CALENDAR_DATA = f"{{{CALDAV}}}calendar-data"
_NO_UID_CONFLICT = f"{{{CALDAV}}}no-uid-conflict"
_GETCTAG = f"{{{CS}}}getctag"
_CALENDAR_COLOR = f"{{{APPLE}}}calendar-color"

_XML_HEADERS = {"Content-Type": "application/xml; charset=utf-8"}
_DECLARATIONS = (
    f'xmlns:d="{DAV}" xmlns:c="{CALDAV}" xmlns:cs="{CS}" xmlns:ical="{APPLE}"'  # explicit, always
)

# iCloud is Apple's CalDAV service; the family reads "Apple" (ADR 0032), so each failure has a
# sentence for Apple and one for any other server (keys in lang/en.json, ADR 0043).
_ICLOUD_AUTH = "api.sync.caldav.auth_apple"
_AUTH = "api.sync.caldav.auth"
_ICLOUD_DOWN = "api.sync.caldav.no_answer_apple"
_NO_CALENDARS = "api.sync.caldav.no_calendars"
_NO_ANSWER = frozenset({"timeout", "unreachable", "not_found"})  # the guard's codes

_Doing = Literal["discover", "read", "write"]


class HttpLike(Protocol):
    """What the client needs from ``PluginHttp`` (plugins/context.py), and nothing more."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        max_bytes: int | None = None,
        follow_redirects: bool = True,
    ) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class Resource:
    href: str  # absolute URL
    etag: str | None
    ical: str  # the calendar-data text


@dataclass(frozen=True, slots=True)
class Delta:
    changed: dict[str, str | None]  # href -> etag (new or changed since the token)
    removed: list[str]  # hrefs gone
    token: str | None  # the new sync token


class SyncTokenInvalid(Exception):  # noqa: N818 - the name callers know
    """The server no longer accepts the token: do a full listing."""


class SyncCollectionUnsupported(SyncError):  # noqa: N818 - says what it means
    """The server can't report changes by sync token: compare etags (``list_etags``) instead."""

    code: str

    def __init__(self, key: str) -> None:
        super().__init__(ErrorKind.BAD_DATA, key)
        self.code = "unsupported"


class CaldavClient:
    """One account on one CalDAV server. Every method raises ``SyncError`` when it fails."""

    def __init__(self, http: HttpLike, server_url: str, username: str, password: str) -> None:
        url = server_url.strip()
        if "://" not in url:
            url = f"https://{url}"  # a bare host name, as people type them
        self._http = http
        self._server_url = _canonical(url)
        self._username = username
        self._password = password
        self._icloud = _is_icloud(self._server_url)

    def __repr__(self) -> str:
        return f"CaldavClient({_host(self._server_url)!r})"

    # ---- discovery ------------------------------------------------------------------------

    async def discover(self) -> list[RemoteCalendar]:
        """The account's calendars that hold events: principal, then home set, then a listing."""
        principal = await self._principal()
        homes = await self._home_sets(principal) if principal else []
        if not homes:
            # No principal or no home set: the address may be a home, or a calendar, itself.
            homes = [principal or self._server_url]
        found: dict[str, RemoteCalendar] = {}
        for home in homes:
            for calendar in await self._calendars_in(home):
                found.setdefault(calendar.remote_id, calendar)
        return list(found.values())

    async def _principal(self) -> str | None:
        """RFC 6764: /.well-known/caldav first (the guarded client follows its redirect), then
        the address itself."""
        well_known = urljoin(self._server_url, "/.well-known/caldav")
        result: FetchResult | None
        try:
            result = await self._send(
                "PROPFIND", well_known, headers=_dav("0"), body=_PRINCIPAL_BODY
            )
        except OutboundError as error:
            if error.code in _NO_ANSWER:  # the same host: the address won't answer either
                raise self._unreachable(error, well_known) from None
            result = None  # a redirect somewhere the guard refused: try the address itself
        if result is not None:
            if result.status in (401, 429, 503):
                raise self._failure(result, "discover")
            if principal := _principal_in(result):
                return principal
        result = await self._request(
            "PROPFIND", self._server_url, headers=_dav("0"), body=_PRINCIPAL_BODY
        )
        if result.status not in (200, 207):
            raise self._failure(result, "discover")
        return _principal_in(result)

    async def _home_sets(self, principal: str) -> list[str]:
        result = await self._request("PROPFIND", principal, headers=_dav("0"), body=_HOME_SET_BODY)
        homes: list[str] = []
        for member in _members(self._multistatus(result, "discover"), result.url):
            home_set = member.props.get(_CALENDAR_HOME_SET)
            if home_set is not None:
                homes.extend(_hrefs_in(home_set, result.url))
        return list(dict.fromkeys(homes))

    async def _calendars_in(self, home: str) -> list[RemoteCalendar]:
        result = await self._request("PROPFIND", home, headers=_dav("1"), body=_CALENDARS_BODY)
        calendars: list[RemoteCalendar] = []
        for member in _members(self._multistatus(result, "discover"), result.url):
            if member.ok and (calendar := _calendar(member)):
                calendars.append(calendar)
        return calendars

    # ---- changes --------------------------------------------------------------------------

    async def sync_collection(self, calendar_href: str, token: str | None) -> Delta:
        """What changed since ``token`` (None: everything, an initial sync). Raises
        ``SyncTokenInvalid`` when the server has forgotten the token, and
        ``SyncCollectionUnsupported`` when it can't do this at all."""
        changed: dict[str, str | None] = {}
        removed: dict[str, None] = {}  # an ordered set
        sent = token
        for _round in range(SYNC_ROUNDS):
            result = await self._request(
                "REPORT", calendar_href, headers=_dav("0"), body=_sync_body(sent)
            )
            if result.status not in (200, 207):
                raise self._sync_failure(result, with_token=sent is not None)
            root = self._multistatus(result, "read")
            truncated = False
            for member in _members(root, result.url):
                if _same(member.href, calendar_href) or _same(member.href, result.url):
                    # The collection itself: 507 means "there is more, ask again".
                    truncated = truncated or member.status == 507
                elif member.href.endswith("/"):
                    continue  # a collection inside the calendar, not an event
                elif member.status in (404, 410):
                    changed.pop(member.href, None)
                    removed[member.href] = None
                elif member.ok:
                    removed.pop(member.href, None)
                    changed[member.href] = member.etag
            new_token = _text(root.find(_SYNC_TOKEN)) or None
            if not truncated or new_token is None or new_token == sent:
                return Delta(changed, list(removed), new_token)
            sent = new_token
        # Still truncated: the token covers what arrived, so the next sync carries on from it.
        log.warning("caldav.sync_rounds_exhausted", host=_host(calendar_href), rounds=SYNC_ROUNDS)
        return Delta(changed, list(removed), sent)

    async def list_etags(self, calendar_href: str) -> dict[str, str | None]:
        """Every event resource in the calendar with its etag: the fallback for servers without
        sync-collection (compare with what's stored, then multiget what differs)."""
        result = await self._request("PROPFIND", calendar_href, headers=_dav("1"), body=_ETAGS_BODY)
        etags: dict[str, str | None] = {}
        for member in _members(self._multistatus(result, "read"), result.url):
            if (
                not member.ok
                or member.href.endswith("/")
                or _same(member.href, calendar_href)
                or _same(member.href, result.url)
            ):
                continue
            content_type = member.text(_GETCONTENTTYPE).lower()
            if content_type.startswith("text/calendar") or _path(member.href).endswith(".ics"):
                etags[member.href] = member.etag
        return etags

    async def ctag(self, calendar_href: str) -> str | None:
        """A value that changes whenever anything in the calendar does: getctag, else the
        sync-token property, else None."""
        result = await self._request("PROPFIND", calendar_href, headers=_dav("0"), body=_CTAG_BODY)
        for member in _members(self._multistatus(result, "read"), result.url):
            if value := member.text(_GETCTAG) or member.text(_SYNC_TOKEN):
                return value
        return None

    # ---- reads and writes -----------------------------------------------------------------

    async def multiget(self, calendar_href: str, hrefs: Sequence[str]) -> list[Resource]:
        """The resources at ``hrefs`` with their etags, in batches of ``MULTIGET_BATCH``.
        Always by href: iCloud can't look events up by UID. Any that are gone are left out."""
        wanted = list(dict.fromkeys(_canonical(href) for href in hrefs))
        resources: list[Resource] = []
        for start in range(0, len(wanted), MULTIGET_BATCH):
            batch = wanted[start : start + MULTIGET_BATCH]
            result = await self._request(
                "REPORT", calendar_href, headers=_dav("1"), body=_multiget_body(batch)
            )
            for member in _members(self._multistatus(result, "read"), result.url):
                if member.ok and (ical := member.text(_CALENDAR_DATA)):
                    resources.append(Resource(member.href, member.etag, ical))
        return resources

    async def put(self, href: str, ical: str, *, etag: str | None) -> str | None:
        """Create (no etag) or replace (If-Match) the resource. Returns the new etag when the
        server says it, else None (the next pull fills it in)."""
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        else:
            headers["If-None-Match"] = "*"  # create only: never overwrite something unseen
        result = await self._request("PUT", href, headers=headers, body=_crlf(ical).encode())
        if not result.ok:
            raise self._failure(result, "write")
        return (result.headers.get("etag") or "").strip() or None

    async def delete(self, href: str, *, etag: str | None) -> None:
        """Remove the resource (If-Match when the etag is known). Already gone counts as done."""
        headers = {"If-Match": etag} if etag else {}
        result = await self._request("DELETE", href, headers=headers)
        if not result.ok and result.status not in (404, 410):
            raise self._failure(result, "write")

    def new_href(self, calendar_href: str, uid: str) -> str:
        """Where a new event with this UID goes: the calendar, a name made from the UID, .ics."""
        base = calendar_href if calendar_href.endswith("/") else f"{calendar_href}/"
        return _canonical(f"{base}{_resource_name(uid)}.ics")

    # ---- HTTP -----------------------------------------------------------------------------

    def _authorization(self) -> str:
        pair = f"{self._username}:{self._password}".encode()
        return f"Basic {base64.b64encode(pair).decode('ascii')}"

    async def _send(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None = None
    ) -> FetchResult:
        """One request, with the Basic header built for it alone (never stored, never logged).
        The guard's own errors (OutboundError) pass through."""
        send = {**headers, "Authorization": self._authorization()}
        return await self._http.request(
            method, url, headers=send, content=body, max_bytes=CALDAV_MAX_BYTES
        )

    async def _request(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None = None
    ) -> FetchResult:
        try:
            return await self._send(method, url, headers=headers, body=body)
        except OutboundError as error:
            raise self._unreachable(error, url) from None

    def _multistatus(self, result: FetchResult, doing: _Doing) -> Element:
        if result.status not in (200, 207):
            raise self._failure(result, doing)
        root = _parse(result.content)
        if root is None or root.tag != _MULTISTATUS:
            if doing == "discover" and result.status != 207:
                raise SyncError(ErrorKind.NOT_FOUND, _NO_CALENDARS)  # a web page, say
            raise SyncError(
                ErrorKind.BAD_DATA,
                _either(
                    self._on_icloud(result.url),
                    "api.sync.caldav.unreadable_apple",
                    "api.sync.caldav.unreadable",
                ),
            )
        return root

    # ---- errors ---------------------------------------------------------------------------

    def _on_icloud(self, url: str) -> bool:
        return self._icloud or _is_icloud(url)

    def _unreachable(self, error: OutboundError, url: str) -> SyncError:
        if error.code in _NO_ANSWER and self._on_icloud(url):
            return SyncError(ErrorKind.UNREACHABLE, _ICLOUD_DOWN)
        return SyncError(
            ErrorKind.UNREACHABLE, error.key, params=error.params
        )  # the guard's: no URL

    def _failure(self, result: FetchResult, doing: _Doing) -> SyncError:
        status = result.status
        icloud = self._on_icloud(result.url)
        if status == 401 or (status == 403 and doing != "write"):
            return SyncError(ErrorKind.AUTH, _ICLOUD_AUTH if icloud else _AUTH)
        if status in (429, 503):  # iCloud's undocumented rate limit is a 503
            return SyncError(
                ErrorKind.RATE_LIMITED,
                _either(icloud, "api.sync.caldav.slow_down_apple", "api.sync.caldav.slow_down"),
                retry_after=_retry_after(result.headers),
            )
        if status >= 500:
            return SyncError(
                ErrorKind.UNREACHABLE,
                _either(icloud, "api.sync.caldav.trouble_apple", "api.sync.caldav.trouble"),
            )
        if doing == "discover":
            return SyncError(ErrorKind.NOT_FOUND, _NO_CALENDARS)
        if status in (404, 410):
            return SyncError(
                ErrorKind.NOT_FOUND,
                _either(
                    icloud, "api.sync.caldav.calendar_gone_apple", "api.sync.caldav.calendar_gone"
                ),
            )
        if doing == "read":
            return SyncError(
                ErrorKind.BAD_DATA,
                _either(icloud, "api.sync.caldav.unreadable_apple", "api.sync.caldav.unreadable"),
            )
        if status == 412:
            return SyncError(
                ErrorKind.CONFLICT,
                _either(icloud, "api.sync.caldav.changed_apple", "api.sync.caldav.changed"),
            )
        if _NO_UID_CONFLICT in _conditions(result.content):  # iCloud: one UID, one calendar
            return SyncError(
                ErrorKind.REFUSED,
                _either(icloud, "api.sync.caldav.uid_taken_apple", "api.sync.caldav.uid_taken"),
            )
        if status == 403:
            return SyncError(
                ErrorKind.REFUSED,
                _either(icloud, "api.sync.caldav.not_allowed_apple", "api.sync.caldav.not_allowed"),
            )
        return SyncError(
            ErrorKind.REFUSED,
            _either(icloud, "api.sync.caldav.rejected_apple", "api.sync.caldav.rejected"),
        )

    def _sync_failure(self, result: FetchResult, *, with_token: bool) -> Exception:
        """RFC 6578: a forgotten token is 403 or 409 with DAV:valid-sync-token; servers also
        send 400 or 412 (and 410). A server without the report says DAV:supported-report."""
        conditions = _conditions(result.content)
        status = result.status
        if with_token and (_VALID_SYNC_TOKEN in conditions or status in (400, 410, 412)):
            return SyncTokenInvalid("The server asked Sunroom to read the whole calendar again.")
        if (
            _SUPPORTED_REPORT in conditions
            or _VALID_SYNC_TOKEN in conditions
            or status in (405, 415, 501)
            or (status == 400 and not with_token)
        ):
            return SyncCollectionUnsupported(
                _either(
                    self._on_icloud(result.url),
                    "api.sync.caldav.no_change_list_apple",
                    "api.sync.caldav.no_change_list",
                )
            )
        return self._failure(result, "read")


# ---- requests ------------------------------------------------------------------------------


def _dav(depth: str) -> dict[str, str]:
    """Headers for a PROPFIND or REPORT with an XML body."""
    return {**_XML_HEADERS, "Depth": depth}


def _xml(root: str, inner: str) -> bytes:
    head = '<?xml version="1.0" encoding="utf-8"?>\n'
    return f"{head}<{root} {_DECLARATIONS}>{inner}</{root}>".encode()


def _propfind(*props: str) -> bytes:
    return _xml("d:propfind", "<d:prop>" + "".join(f"<{prop}/>" for prop in props) + "</d:prop>")


_PRINCIPAL_BODY = _propfind("d:current-user-principal")
_HOME_SET_BODY = _propfind("c:calendar-home-set")
_CALENDARS_BODY = _propfind(
    "d:resourcetype",
    "d:displayname",
    "c:supported-calendar-component-set",
    "d:current-user-privilege-set",
    "ical:calendar-color",
    "cs:getctag",
    "d:sync-token",
)
_ETAGS_BODY = _propfind("d:getetag", "d:getcontenttype")
_CTAG_BODY = _propfind("cs:getctag", "d:sync-token")


def _sync_body(token: str | None) -> bytes:
    sync_token = f"<d:sync-token>{escape(token)}</d:sync-token>" if token else "<d:sync-token/>"
    return _xml(
        "d:sync-collection",
        f"{sync_token}<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop>",
    )


def _multiget_body(hrefs: Sequence[str]) -> bytes:
    # Paths, not whole URLs: every server matches those, and the batch shares one host.
    listed = "".join(f"<d:href>{escape(_path(href))}</d:href>" for href in hrefs)
    return _xml("c:calendar-multiget", f"<d:prop><d:getetag/><c:calendar-data/></d:prop>{listed}")


# ---- replies -------------------------------------------------------------------------------


class _Builder(TreeBuilder):
    """ElementTree's tree builder, refusing any document that declares a DTD."""

    def doctype(self, name: str, pubid: str, system: str) -> None:
        raise ValueError("a DTD")


def _parse(content: bytes) -> Element | None:
    """A reply's XML, or None when it isn't XML Sunroom will read.

    Python 3.14's bundled expat caps entity expansion (no "billion laughs"), and ElementTree
    never resolves external entities or fetches DTDs. CalDAV never needs a DTD, so a reply that
    declares one is refused before anything in it is used."""
    parser = XMLParser(target=_Builder())  # noqa: S314 - safe as above
    try:
        parser.feed(content)
        return parser.close()
    except ParseError, ValueError:
        return None


@dataclass(frozen=True, slots=True)
class _Member:
    """One href of a multistatus reply, with the properties the server found for it."""

    href: str  # absolute and canonical
    status: int | None  # the response's own status, when it has one (404: gone)
    props: dict[str, Element]  # from the propstats with a 2xx status, by Clark name

    @property
    def ok(self) -> bool:
        return self.status is None or 200 <= self.status < 300

    @property
    def etag(self) -> str | None:
        return self.text(_GETETAG) or None

    def text(self, name: str) -> str:
        return _text(self.props.get(name))


def _members(root: Element, base: str) -> list[_Member]:
    members: list[_Member] = []
    for response in root.findall(_RESPONSE):
        props: dict[str, Element] = {}
        for propstat in response.findall(_PROPSTAT):
            status = _status(propstat.find(_STATUS))
            prop = propstat.find(_PROP)
            if prop is not None and (status is None or 200 <= status < 300):
                props.update((child.tag, child) for child in prop)
        status = _status(response.find(_STATUS))
        members.extend(_Member(href, status, props) for href in _hrefs_in(response, base))
    return members


def _hrefs_in(element: Element, base: str) -> list[str]:
    return [
        _canonical(urljoin(base, href.text.strip()))
        for href in element.findall(_HREF)
        if href.text and href.text.strip()
    ]


def _principal_in(result: FetchResult) -> str | None:
    if result.status not in (200, 207):
        return None
    root = _parse(result.content)
    if root is None or root.tag != _MULTISTATUS:
        return None
    for member in _members(root, result.url):
        principal = member.props.get(_CURRENT_USER_PRINCIPAL)
        if principal is not None and (hrefs := _hrefs_in(principal, result.url)):
            return hrefs[0]
    return None


def _calendar(member: _Member) -> RemoteCalendar | None:
    resourcetype = member.props.get(_RESOURCETYPE)
    if resourcetype is None or resourcetype.find(_CALENDAR) is None:
        return None  # a plain collection, an inbox, a subscription, a notification box
    components = member.props.get(_COMPONENT_SET)
    if components is not None:
        names = {(comp.get("name") or "").upper() for comp in components.iter(_COMP)}
        if names and "VEVENT" not in names:
            return None  # a reminders or tasks list
    read_only = False
    privileges = member.props.get(_PRIVILEGES)
    if privileges is not None:
        granted = {grant.tag for privilege in privileges.iter(_PRIVILEGE) for grant in privilege}
        read_only = not granted & _WRITE_PRIVILEGES
    name = member.text(_DISPLAYNAME) or _last_segment(member.href) or "Calendar"
    return RemoteCalendar(member.href, name, _color(member.text(_CALENDAR_COLOR)), read_only)


def _conditions(content: bytes) -> set[str]:
    """The preconditions a DAV:error body names (RFC 4918 §16), by Clark name."""
    root = _parse(content) if content else None
    if root is None or root.tag != _ERROR:
        return set()
    return {child.tag for child in root}


_STATUS_LINE = re.compile(r"\s*HTTP/\S+\s+(\d{3})")


def _status(element: Element | None) -> int | None:
    match = _STATUS_LINE.match(element.text or "") if element is not None else None
    return int(match.group(1)) if match else None


def _text(element: Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


_COLOR = re.compile(r"#?([0-9A-Fa-f]{6})(?:[0-9A-Fa-f]{2})?")


def _color(value: str) -> str | None:
    """Apple's calendar-color as "#RRGGBB" (iCloud sends "#RRGGBBAA")."""
    match = _COLOR.fullmatch(value)
    return f"#{match.group(1).upper()}" if match else None


# ---- URLs ----------------------------------------------------------------------------------

# Besides letters, digits and -._~ (never escaped), these stay as they are in a path; anything
# else is percent-encoded. "%2F" inside a segment stays escaped, so the path keeps its shape.
_PATH_SAFE = "@:"


def _canonical(url: str) -> str:
    """One spelling for one URL: escapes decoded where that's harmless and otherwise written in
    upper case, the host in lower case, no default port, no fragment."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        return url.strip()  # the guard refuses it with a plain message
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    default = {"https": 443, "http": 80}.get(scheme)
    netloc = host if port is None or port == default else f"{host}:{port}"
    path = "/".join(
        quote(unquote_to_bytes(segment), safe=_PATH_SAFE) for segment in parts.path.split("/")
    )
    return urlunsplit((scheme, netloc, path or "/", parts.query, ""))


def _same(a: str, b: str) -> bool:
    return _canonical(a).rstrip("/") == _canonical(b).rstrip("/")


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _last_segment(url: str) -> str:
    return unquote(urlsplit(url).path.rstrip("/").rpartition("/")[2]).strip()


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").rstrip(".")
    except ValueError:
        return ""


def _is_icloud(url: str) -> bool:
    host = _host(url)
    return host == "icloud.com" or host.endswith(".icloud.com")


_PLAIN_NAME = re.compile(r"[A-Za-z0-9_@-][A-Za-z0-9._@-]*")


def _resource_name(uid: str) -> str:
    """A file name for a new resource, the same every time for the same UID (so a retried
    create meets If-None-Match instead of making a twin).

    A UID of letters, digits and "-._@" (UUIDs, "…@google.com", Outlook's hex) is the name as it
    is. Escaping doesn't make other characters safe, because servers decode before they check:
    Radicale refuses ":", "?", ",", "*" and quotes, and names that start with a dot. So any
    other UID, or a long one, becomes its plain characters plus a hash of the whole UID."""
    if len(uid) <= NAME_MAX and _PLAIN_NAME.fullmatch(uid):
        return uid
    digest = hashlib.sha256(uid.encode()).hexdigest()[:32]
    head = re.sub(r"[^A-Za-z0-9_@-]+", "", uid)[:40]
    return f"{head}-{digest}" if head else digest


# ---- small things --------------------------------------------------------------------------

_NEWLINES = re.compile(r"\r\n|\r|\n")


def _crlf(text: str) -> str:
    """iCalendar lines end in CRLF (RFC 5545); text read back out of XML has bare LFs."""
    return _NEWLINES.sub("\r\n", text)


def _either(icloud: bool, apple: str, server: str) -> str:
    """Apple's sentence on iCloud, the other server's everywhere else."""
    return apple if icloud else server


def _retry_after(headers: Mapping[str, str]) -> float | None:
    """Retry-After in seconds: a number, or an HTTP date measured from the reply's own Date."""
    value = (headers.get("retry-after") or "").strip()
    if not value:
        return None
    if value.isascii() and value.isdigit():
        return float(value)
    when = _http_date(value)
    if when is None:
        return None
    now = _http_date(headers.get("date") or "") or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())


def _http_date(value: str) -> datetime | None:
    try:
        when = parsedate_to_datetime(value)
    except TypeError, ValueError, IndexError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)
