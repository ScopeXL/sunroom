"""Google Calendar (PLAN §8.1, ADR 0004): a small REST client and the provider built on it.

Two ways in, both two-way, both for the scope ``https://www.googleapis.com/auth/calendar``:

* **The helper** (a service account). The family uploads its JSON key once and shares calendars
  with its address. Sunroom signs a one-hour JWT with the key (RS256) and trades it for an
  access token. Nothing expires on the family's side.
* **Sign in with Google.** The standard web flow with PKCE gives a refresh token, traded for
  access tokens as they run out. Google revoking it (``invalid_grant``) means signing in again.

A client of our own rather than Google's libraries (ADR 0024): every request goes through the
plugin's guarded HTTP client, which checks the address, pins the connection, caps the size and
times out. Google's hosts are constants here, and redirects are never followed, so a bearer
token can't travel on to another host.

Reading, in the core's terms (``calendar/synced.py``):

* A recurring event (the master) and its changed occurrences (exceptions: events with
  ``recurringEventId`` and ``originalStartTime``) are one series, keyed by the iCalUID. A
  cancelled exception is a cancelled occurrence (it becomes an EXDATE).
* ``events.list`` with ``showDeleted`` and ``singleEvents=false`` lists masters and exceptions;
  its sync token makes the next listing only what changed. A token Google has forgotten (410)
  means reading the whole calendar again (``complete``).
* A stored series is replaced whole when its master arrives, so a recurring master that changed
  is read again with all its exceptions (``events.list`` by iCalUID). Exceptions that changed on
  their own become a partial series (``master`` None), after one look at their master for its
  iCalUID, zone and etag. Occurrences whose series lives in another calendar (an invitation to
  one of them) are events of their own.

Pushing edits Google's own copy: get it, change what Sunroom keeps (title, notes, place, times,
repeats), put it back with ``If-Match``. Guests, reminders, colors and video links stay. Changed
occurrences are put to their instance ids; cancelled ones go out as EXDATEs.

Failures become ``SyncError``s in plain English that never carry a token, a key, an address or
an event's text.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sunroom.calendar.synced import PendingSeries, SyncedEvent, SyncedOverride, SyncedSeries
from sunroom.core.http import FetchResult
from sunroom.core.lang import t_en
from sunroom.core.logging import get_logger
from sunroom.core.netguard import OutboundError
from sunroom.domain.recurrence import Timing
from sunroom.domain.timeparts import from_local, parse_rid, rid_date, rid_timed, to_local
from sunroom.plugins.calendar_sync.ical import (
    DESCRIPTION_MAX,
    LOCATION_MAX,
    NO_TITLE,
    TITLE_MAX,
    parse_recurrence_lines,
    recurrence_lines,
)
from sunroom.plugins.calendar_sync.providers.base import (
    Changes,
    ErrorKind,
    Pushed,
    RemoteCalendar,
    SyncError,
)

log = get_logger(__name__)

SCOPE = "https://www.googleapis.com/auth/calendar"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an address, not a secret
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
API_URL = "https://www.googleapis.com/calendar/v3"
# The token addresses a key file may name (older keys carry the second).
TOKEN_URIS = frozenset({TOKEN_URL, "https://accounts.google.com/o/oauth2/token"})
JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"

ASSERTION_S = 3600  # a signed JWT's lifetime: Google's maximum
EARLY_S = 60  # an access token is replaced this long before it runs out
PAGE_SIZE = 2500  # events.list's most per page
CALENDARS_PAGE = 250  # calendarList.list's most per page
MAX_PAGES = 200  # a listing longer than this isn't a family calendar
GOOGLE_MAX_BYTES = 20 * 1024 * 1024
TOKEN_MAX_BYTES = 64 * 1024
KEY_MAX_CHARS = 64 * 1024

# What Google's failures say, by their keys in lang/en.json (ADR 0043).
NOT_A_KEY = "api.sync.google.not_a_key"
KEY_AGAIN = "api.sync.google.key_again"
KEY_REFUSED = "api.sync.google.key_refused"
SIGNED_OUT = "api.sync.google.signed_out"
CLIENT_REFUSED = "api.sync.google.client_refused"
SIGN_IN_FAILED = "api.sync.google.sign_in_failed"
NO_CALENDARS_GRANTED = "api.sync.google.no_calendars_granted"
CLOCK_WRONG = "api.sync.google.clock_wrong"
NO_ANSWER = "api.sync.google.no_answer"
SLOW_DOWN = "api.sync.google.slow_down"
API_OFF = "api.sync.google.api_off"
HELPER_REFUSED = "api.sync.google.helper_refused"
ACCOUNT_REFUSED = "api.sync.google.account_refused"
CANT_SEE = "api.sync.google.cant_see"
NOT_SHARED = "api.sync.google.not_shared"
CALENDAR_GONE = "api.sync.google.calendar_gone"
EVENT_GONE = "api.sync.google.event_gone"
CHANGED = "api.sync.google.changed"
ALREADY_THERE = "api.sync.google.already_there"
REJECTED = "api.sync.google.rejected"
UNREADABLE = "api.sync.google.unreadable"
TOO_BIG = "api.sync.google.too_big"
TOO_MANY = "api.sync.google.too_many"

# Error reasons, folded (rateLimitExceeded and RATE_LIMIT_EXCEEDED are one).
_SLOW_DOWN = frozenset(
    {"ratelimitexceeded", "userratelimitexceeded", "quotaexceeded", "dailylimitexceeded"}
)
_API_OFF = frozenset({"accessnotconfigured", "servicedisabled"})
_CLIENT_ERRORS = frozenset(
    {"invalid_client", "unauthorized_client", "deleted_client", "disabled_client"}
)
_WRITABLE = frozenset({"owner", "writer"})

_Doing = Literal["read", "write"]


class HttpLike(Protocol):
    """What this module needs from ``PluginHttp`` (plugins/context.py), and nothing more."""

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


class GoogleAuth(Protocol):
    """Where the client's access tokens come from."""

    @property
    def helper(self) -> bool:
        """True for the helper (a service account), False for a signed-in account."""
        ...

    async def access_token(self, *, stale: str | None = None) -> str:
        """A token good for at least another minute; ``stale`` is one Google just refused."""
        ...


class SyncTokenExpired(Exception):  # noqa: N818 - the name callers know
    """Google forgot the sync token (410): list the whole calendar again."""


class EventExists(SyncError):  # noqa: N818 - says what it means
    """events.insert found the iCalUID taken (409): the event is there already, or was."""

    def __init__(self) -> None:
        super().__init__(ErrorKind.CONFLICT, ALREADY_THERE)


# ---- tokens ------------------------------------------------------------------------------------


class _TokenSource:
    """An access token, kept until a minute before it runs out. One caller at a time fetches a
    new one; the others wait for it and use it."""

    helper = False

    def __init__(self, http: HttpLike, now_of: Callable[[], datetime]) -> None:
        self._http = http
        self._now_of = now_of
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"  # never the key or a token

    async def access_token(self, *, stale: str | None = None) -> str:
        """A token good for at least another minute. ``stale`` is one Google just refused: it is
        replaced, unless another caller replaced it already."""
        async with self._lock:
            token, expires_at = self._token, self._expires_at
            if (
                token is not None
                and token != stale
                and expires_at is not None
                and self._now_of() < expires_at - timedelta(seconds=EARLY_S)
            ):
                return token
            token, lifetime = await self._fetch()
            self._token = token
            self._expires_at = self._now_of() + timedelta(seconds=lifetime)
            return token

    async def _fetch(self) -> tuple[str, float]:
        raise NotImplementedError


class ServiceAccountAuth(_TokenSource):
    """The helper: its key signs a JWT that Google trades for an access token."""

    helper = True

    def __init__(
        self, key: Mapping[str, Any], http: HttpLike, now_of: Callable[[], datetime]
    ) -> None:
        super().__init__(http, now_of)
        email = _text(key.get("client_email"))
        token_uri = _text(key.get("token_uri")) or TOKEN_URL
        private = _rsa_key(_text(key.get("private_key")))
        if not email or private is None or token_uri not in TOKEN_URIS:
            raise SyncError(ErrorKind.AUTH, KEY_AGAIN)
        self.email = email  # the helper's address, which calendars are shared with
        self._private = private
        self._key_id = _text(key.get("private_key_id")) or None
        self._token_uri = token_uri

    def assertion(self) -> str:
        """The signed JWT (RS256) Google trades for an access token: good for an hour."""
        issued = int(self._now_of().timestamp())
        header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
        if self._key_id:
            header["kid"] = self._key_id
        claims = {
            "iss": self.email,
            "scope": SCOPE,
            "aud": self._token_uri,
            "iat": issued,
            "exp": issued + ASSERTION_S,
        }
        signing_input = f"{_b64(_compact(header))}.{_b64(_compact(claims))}"
        signature = self._private.sign(
            signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{signing_input}.{_b64(signature)}"

    async def _fetch(self) -> tuple[str, float]:
        form = {"grant_type": JWT_BEARER, "assertion": self.assertion()}
        body = await _token_request(self._http, self._token_uri, form, _helper_refusal)
        return _access(body)


class OAuthAuth(_TokenSource):
    """A signed-in account: its refresh token, traded for access tokens as they run out."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        http: HttpLike,
        now_of: Callable[[], datetime],
    ) -> None:
        super().__init__(http, now_of)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

    async def _fetch(self) -> tuple[str, float]:
        form = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
        }
        body = await _token_request(self._http, TOKEN_URL, form, _account_refusal)
        return _access(body)


def parse_service_account_key(text: str) -> dict[str, str]:
    """An uploaded key file, checked: a service account's JSON key with an RSA private key and
    Google's own token address. Returns the parts Sunroom keeps; raises ValueError (with a
    message for people) for anything else."""
    if len(text) > KEY_MAX_CHARS:
        raise ValueError(t_en(NOT_A_KEY))
    try:
        raw: Any = json.loads(text)
    except ValueError:
        raise ValueError(t_en(NOT_A_KEY)) from None
    data = _object(raw)
    email = _text(data.get("client_email")).strip()
    pem = _text(data.get("private_key"))
    token_uri = _text(data.get("token_uri")) if "token_uri" in data else TOKEN_URL
    if (
        data.get("type") != "service_account"
        or "@" not in email
        or token_uri not in TOKEN_URIS
        or _rsa_key(pem) is None
    ):
        raise ValueError(t_en(NOT_A_KEY))
    key = {
        "type": "service_account",
        "client_email": email,
        "private_key": pem,
        "token_uri": token_uri,
    }
    for name in ("private_key_id", "project_id"):
        if value := _text(data.get(name)):
            key[name] = value
    return key


def new_pkce() -> tuple[str, str]:
    """A code verifier for one sign-in and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)  # 86 characters, all of them unreserved
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """Google's sign-in page for this sign-in. ``prompt=consent`` makes Google send a refresh
    token every time, even to someone who signed in before."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    http: HttpLike,
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """The code Google sent back, traded for tokens: ``refresh_token`` (keep it, encrypted),
    ``access_token`` and ``expires_in`` (seconds)."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    body = await _token_request(http, TOKEN_URL, form, _sign_in_refusal)
    access, lifetime = _access(body)
    refresh = _text(body.get("refresh_token"))
    if not refresh:
        raise SyncError(ErrorKind.AUTH, SIGN_IN_FAILED)
    granted = _text(body.get("scope")).split()
    if granted and SCOPE not in granted:
        raise SyncError(ErrorKind.AUTH, NO_CALENDARS_GRANTED)
    return {"refresh_token": refresh, "access_token": access, "expires_in": int(lifetime)}


async def _token_request(
    http: HttpLike,
    url: str,
    form: Mapping[str, str],
    refusal: Callable[[str, str], SyncError],
) -> dict[str, Any]:
    """POST a form to Google's token endpoint. ``refusal`` names what a 4xx means for this kind
    of credential, from Google's ``error`` and ``error_description``."""
    try:
        result = await http.request(
            "POST",
            url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            content=urlencode(form).encode(),
            max_bytes=TOKEN_MAX_BYTES,
            follow_redirects=False,
        )
    except OutboundError:
        raise SyncError(ErrorKind.UNREACHABLE, NO_ANSWER) from None
    body = _json_object(result.content)
    if result.ok:
        return body
    if result.status == 429:
        raise SyncError(ErrorKind.RATE_LIMITED, SLOW_DOWN, retry_after=_retry_after(result.headers))
    if not 400 <= result.status < 500:
        raise SyncError(ErrorKind.UNREACHABLE, NO_ANSWER)
    raise refusal(_text(body.get("error")), _text(body.get("error_description")).lower())


def _helper_refusal(error: str, description: str) -> SyncError:
    if error == "invalid_grant" and ("timeframe" in description or "iat and exp" in description):
        return SyncError(ErrorKind.REFUSED, CLOCK_WRONG)  # a new key wouldn't help
    return SyncError(ErrorKind.AUTH, KEY_REFUSED)


def _account_refusal(error: str, description: str) -> SyncError:
    if error in _CLIENT_ERRORS:
        return SyncError(ErrorKind.AUTH, CLIENT_REFUSED)
    return SyncError(ErrorKind.AUTH, SIGNED_OUT)


def _sign_in_refusal(error: str, description: str) -> SyncError:
    if error in _CLIENT_ERRORS:
        return SyncError(ErrorKind.AUTH, CLIENT_REFUSED)
    return SyncError(ErrorKind.AUTH, SIGN_IN_FAILED)


def _access(body: Mapping[str, Any]) -> tuple[str, float]:
    token = _text(body.get("access_token"))
    lifetime = body.get("expires_in", ASSERTION_S)
    if not token or isinstance(lifetime, bool) or not isinstance(lifetime, int | float):
        raise SyncError(ErrorKind.BAD_DATA, UNREADABLE)
    return token, float(lifetime)


def _rsa_key(pem: str) -> rsa.RSAPrivateKey | None:
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except ValueError, TypeError, UnsupportedAlgorithm:
        return None
    return key if isinstance(key, rsa.RSAPrivateKey) else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _compact(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


# ---- the Calendar API --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventsPage:
    """A whole listing of one calendar, every page of it: the events as Google sends them, the
    sync token for next time, and the calendar's own time zone (an IANA name)."""

    items: list[dict[str, Any]]
    sync_token: str | None
    time_zone: str | None


class GoogleClient:
    """Google Calendar's REST API for one account. Every method raises SyncError when it fails.

    The time zone of each calendar travels two ways: ``calendar_list`` notes it (read it with
    ``calendar_zones``), and every ``events`` listing carries it (``EventsPage.time_zone``).
    """

    def __init__(self, http: HttpLike, auth: GoogleAuth) -> None:
        self._http = http
        self._auth = auth
        self._zones: dict[str, str] = {}

    def __repr__(self) -> str:
        return "GoogleClient()"

    # ---- calendars --------------------------------------------------------------------------

    async def calendar_list(self) -> list[RemoteCalendar]:
        """The calendars the account sees; for the helper, the ones added with
        ``insert_calendar`` (its own empty calendar is left out)."""
        url = f"{API_URL}/users/me/calendarList"
        calendars: list[RemoteCalendar] = []
        page: str | None = None
        for _page in range(MAX_PAGES):
            query = {"maxResults": str(CALENDARS_PAGE)}
            if page:
                query["pageToken"] = page
            result = await self._call("GET", f"{url}?{urlencode(query)}")
            if not result.ok:
                raise self._failure(result, "read")
            data = _reply(result)
            for entry in _objects(data.get("items")):
                if self._auth.helper and entry.get("primary") is True:
                    continue
                if (calendar := self._remember(entry)) is not None:
                    calendars.append(calendar)
            page = _text(data.get("nextPageToken")) or None
            if page is None:
                return calendars
        raise SyncError(ErrorKind.BAD_DATA, TOO_MANY)

    def calendar_zones(self) -> dict[str, str]:
        """Each calendar's time zone by its id, as the latest ``calendar_list`` or
        ``insert_calendar`` said it."""
        return dict(self._zones)

    async def insert_calendar(self, calendar_id: str) -> RemoteCalendar:
        """Add a calendar to the account's list by its address. The helper sees a calendar shared
        with it only after this. Already in the list counts as done."""
        url = f"{API_URL}/users/me/calendarList"
        result = await self._call("POST", url, body={"id": calendar_id})
        if result.status == 409:
            result = await self._call("GET", f"{url}/{_segment(calendar_id)}")
        if result.status in (400, 403, 404) and not _reasons(result.content) & (
            _SLOW_DOWN | _API_OFF
        ):
            raise SyncError(ErrorKind.NOT_FOUND, NOT_SHARED)
        if not result.ok:
            raise self._failure(result, "read")
        calendar = self._remember(_reply(result))
        if calendar is None:
            raise SyncError(ErrorKind.BAD_DATA, UNREADABLE)
        return calendar

    def _remember(self, entry: Mapping[str, Any]) -> RemoteCalendar | None:
        calendar_id = _text(entry.get("id"))
        if not calendar_id or entry.get("deleted") is True:
            return None
        if zone := _text(entry.get("timeZone")):
            self._zones[calendar_id] = zone
        name = _text(entry.get("summaryOverride")).strip() or _text(entry.get("summary")).strip()
        return RemoteCalendar(
            remote_id=calendar_id,
            name=name or "Google calendar",
            color_hint=_color(_text(entry.get("backgroundColor"))),
            read_only=_text(entry.get("accessRole")) not in _WRITABLE,
        )

    # ---- events -----------------------------------------------------------------------------

    async def events(self, calendar_id: str, sync_token: str | None) -> EventsPage:
        """Every event of the calendar (masters, exceptions and deleted ones), or with a sync
        token only what changed since. Raises SyncTokenExpired when Google forgot the token."""
        query = {"showDeleted": "true", "singleEvents": "false", "maxResults": str(PAGE_SIZE)}
        if sync_token:
            query["syncToken"] = sync_token
        return await self._listing(calendar_id, query, with_token=bool(sync_token))

    async def events_by_uid(self, calendar_id: str, ical_uid: str) -> list[dict[str, Any]]:
        """One series whole: its master and every exception (they share the iCalUID), deleted
        ones included."""
        query = {
            "iCalUID": ical_uid,
            "showDeleted": "true",
            "singleEvents": "false",
            "maxResults": str(PAGE_SIZE),
        }
        return (await self._listing(calendar_id, query, with_token=False)).items

    async def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any] | None:
        """One event: a master, an exception, or any occurrence by its instance id. None when the
        calendar has no such event."""
        result = await self._call("GET", _event_url(calendar_id, event_id))
        if result.status in (404, 410):
            return None
        if not result.ok:
            raise self._failure(result, "read")
        return _reply(result)

    async def insert_event(self, calendar_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """A new event. Raises EventExists (a CONFLICT) when its iCalUID is taken."""
        url = f"{API_URL}/calendars/{_segment(calendar_id)}/events"
        result = await self._call("POST", url, body=body)
        if result.status == 409:
            raise EventExists
        if not result.ok:
            raise self._failure(result, "write")
        return _reply(result)

    async def update_event(
        self, calendar_id: str, event_id: str, body: Mapping[str, Any], etag: str | None
    ) -> dict[str, Any]:
        """Replace the event (PUT: what ``body`` leaves out is cleared), If-Match ``etag``. A
        412 raises SyncError(CONFLICT)."""
        headers = {"If-Match": etag} if etag else {}
        result = await self._call(
            "PUT", _event_url(calendar_id, event_id), body=body, headers=headers
        )
        if not result.ok:
            raise self._failure(result, "write")
        return _reply(result)

    async def delete_event(self, calendar_id: str, event_id: str, etag: str | None) -> None:
        """Delete the event (a master takes its series with it), If-Match ``etag``. Already gone
        counts as done."""
        headers = {"If-Match": etag} if etag else {}
        result = await self._call("DELETE", _event_url(calendar_id, event_id), headers=headers)
        if not result.ok and result.status not in (404, 410):
            raise self._failure(result, "write")

    async def _listing(
        self, calendar_id: str, query: Mapping[str, str], *, with_token: bool
    ) -> EventsPage:
        url = f"{API_URL}/calendars/{_segment(calendar_id)}/events"
        items: list[dict[str, Any]] = []
        zone: str | None = None
        page: str | None = None
        for _page in range(MAX_PAGES):
            asked = {**query, "pageToken": page} if page else dict(query)
            result = await self._call("GET", f"{url}?{urlencode(asked)}")
            if with_token and result.status in (400, 410):
                raise SyncTokenExpired  # 410; a token Google can't read at all is a 400
            if not result.ok:
                raise self._failure(result, "read")
            data = _reply(result)
            items.extend(_objects(data.get("items")))
            zone = zone or _text(data.get("timeZone")) or None
            page = _text(data.get("nextPageToken")) or None
            if page is None:
                return EventsPage(items, _text(data.get("nextSyncToken")) or None, zone)
        raise SyncError(ErrorKind.BAD_DATA, TOO_MANY)

    # ---- HTTP -------------------------------------------------------------------------------

    async def _call(
        self,
        method: str,
        url: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        """One request with a bearer token. A 401 gets a fresh token and one more try; a second
        401 means Google stopped taking these credentials."""
        content = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        token = await self._auth.access_token()
        result = await self._send(method, url, token, content, headers)
        if result.status == 401:
            token = await self._auth.access_token(stale=token)
            result = await self._send(method, url, token, content, headers)
            if result.status == 401:
                raise SyncError(ErrorKind.AUTH, KEY_REFUSED if self._auth.helper else SIGNED_OUT)
        return result

    async def _send(
        self,
        method: str,
        url: str,
        token: str,
        content: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> FetchResult:
        send = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if content is not None:
            send["Content-Type"] = "application/json; charset=utf-8"
        send.update(headers or {})
        try:
            return await self._http.request(
                method,
                url,
                headers=send,
                content=content,
                max_bytes=GOOGLE_MAX_BYTES,
                follow_redirects=False,
            )
        except OutboundError as error:
            if error.code == "too_large":
                raise SyncError(ErrorKind.BAD_DATA, TOO_BIG) from None
            raise SyncError(ErrorKind.UNREACHABLE, NO_ANSWER) from None

    def _failure(self, result: FetchResult, doing: _Doing) -> SyncError:
        status = result.status
        reasons = _reasons(result.content)
        if status == 429 or (status == 403 and reasons & _SLOW_DOWN):
            return SyncError(
                ErrorKind.RATE_LIMITED, SLOW_DOWN, retry_after=_retry_after(result.headers)
            )
        if status == 403 and reasons & _API_OFF:
            return SyncError(ErrorKind.REFUSED, API_OFF)
        if status == 401:
            return SyncError(ErrorKind.AUTH, KEY_REFUSED if self._auth.helper else SIGNED_OUT)
        if status == 403:
            if doing == "read":
                return SyncError(ErrorKind.REFUSED, CANT_SEE)
            return SyncError(
                ErrorKind.REFUSED, HELPER_REFUSED if self._auth.helper else ACCOUNT_REFUSED
            )
        if status in (404, 410):
            return SyncError(ErrorKind.NOT_FOUND, EVENT_GONE if doing == "write" else CALENDAR_GONE)
        if status == 412:
            return SyncError(ErrorKind.CONFLICT, CHANGED)
        if status >= 500:
            return SyncError(
                ErrorKind.UNREACHABLE, NO_ANSWER, retry_after=_retry_after(result.headers)
            )
        if doing == "write":
            return SyncError(ErrorKind.REFUSED, REJECTED)
        return SyncError(ErrorKind.BAD_DATA, UNREADABLE)


def _event_url(calendar_id: str, event_id: str) -> str:
    return f"{API_URL}/calendars/{_segment(calendar_id)}/events/{_segment(event_id)}"


def _segment(value: str) -> str:
    """One path segment: calendar ids hold "@" and "#"."""
    return quote(value, safe="")


def _reply(result: FetchResult) -> dict[str, Any]:
    try:
        value: Any = json.loads(result.content)
    except ValueError:
        raise SyncError(ErrorKind.BAD_DATA, UNREADABLE) from None
    if not isinstance(value, dict):
        raise SyncError(ErrorKind.BAD_DATA, UNREADABLE)
    return cast(dict[str, Any], value)


def _reasons(content: bytes) -> set[str]:
    """The reasons an error reply gives, folded: rateLimitExceeded (the classic ``errors``
    list) and RATE_LIMIT_EXCEEDED (the newer ``details``) are both ``ratelimitexceeded``."""
    error = _object(_json_object(content).get("error"))
    found = [_text(entry.get("reason")) for entry in _objects(error.get("errors"))]
    found += [_text(entry.get("reason")) for entry in _objects(error.get("details"))]
    return {reason.replace("_", "").lower() for reason in found if reason}


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


_COLOR = re.compile(r"#?([0-9A-Fa-f]{6})")


def _color(value: str) -> str | None:
    match = _COLOR.fullmatch(value.strip())
    return f"#{match.group(1).upper()}" if match else None


# ---- the provider ------------------------------------------------------------------------------


class GoogleProvider:
    """A Google account (the helper or a signed-in one) as a CalendarProvider (base.py).

    ``changes`` returns series in the core's shape; ``refused`` counts the series of the last
    ``changes`` that Sunroom can't show (a repeat it can't read, a time it can't place).
    ``push`` returns where the series now lives (the master's id and new etag); ``delete``
    returns nothing.
    """

    def __init__(
        self,
        client: GoogleClient,
        household: Callable[[], ZoneInfo],
        now_of: Callable[[], datetime],
    ) -> None:
        self._client = client
        self._household = household
        self._now_of = now_of  # the other providers' shape; Google stamps its own changes
        self.refused = 0

    async def calendars(self) -> list[RemoteCalendar]:
        return await self._client.calendar_list()

    async def changes(
        self, calendar: RemoteCalendar, cursor: str | None, known: Mapping[str, str | None]
    ) -> Changes:
        complete = cursor is None
        try:
            listing = await self._client.events(calendar.remote_id, cursor)
        except SyncTokenExpired:
            log.info("google.sync_token_expired")
            listing = await self._client.events(calendar.remote_id, None)
            complete = True
        household = self._household()
        zone = (
            _zone(listing.time_zone)
            or _zone(self._client.calendar_zones().get(calendar.remote_id))
            or household
        )
        reader = _Reader(self._client, calendar.remote_id, zone, household)
        series, removed = await reader.read(listing.items, complete=complete)
        self.refused = reader.refused
        return Changes(series=series, removed=removed, complete=complete, cursor=listing.sync_token)

    async def push(self, calendar: RemoteCalendar, pending: PendingSeries) -> Pushed:
        """Create the series (events.insert with its iCalUID) or replace Google's copy of it
        (If-Match its etag), then put each changed occurrence to its instance id."""
        series = pending.series
        master = series.master
        if master is None:
            raise SyncError(ErrorKind.BAD_DATA, REJECTED)  # a pending series always has one
        calendar_id = calendar.remote_id
        tzid = self._tzid(master)
        ours = _body(master, tzid)
        lines = _recurrence(series)
        if series.remote_id is None:
            saved = await self._create(calendar_id, series.uid, ours, lines)
        else:
            saved = await self._replace(calendar_id, series, ours, lines)
        event_id = _text(saved.get("id"))
        if not event_id:
            raise SyncError(ErrorKind.BAD_DATA, UNREADABLE)
        for override in series.overrides:
            if not override.event.cancelled:  # a cancelled one went out as an EXDATE
                await self._push_occurrence(
                    calendar_id, event_id, override, tzid, master.timing.all_day
                )
        return Pushed(
            uid=_text(saved.get("iCalUID")) or series.uid, remote_id=event_id, etag=_etag(saved)
        )

    async def delete(self, calendar: RemoteCalendar, pending: PendingSeries) -> None:
        series = pending.series
        if series.remote_id is not None:
            await self._client.delete_event(calendar.remote_id, series.remote_id, series.etag)

    async def _create(
        self, calendar_id: str, uid: str, ours: dict[str, Any], lines: list[str]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {**ours, "iCalUID": uid}
        if lines:
            body["recurrence"] = lines
        try:
            return await self._client.insert_event(calendar_id, body)
        except EventExists:
            # Google keeps a removed event's iCalUID, so one put back here is restored there. A
            # live one is an event Sunroom hasn't pulled yet: the engine pulls, then pushes again.
            for item in await self._client.events_by_uid(calendar_id, uid):
                event_id = _text(item.get("id"))
                if event_id and not item.get("recurringEventId") and _cancelled(item):
                    return await self._client.update_event(
                        calendar_id,
                        event_id,
                        _onto(item, {**ours, "recurrence": lines}),
                        _etag(item),
                    )
            raise

    async def _replace(
        self, calendar_id: str, series: SyncedSeries, ours: dict[str, Any], lines: list[str]
    ) -> dict[str, Any]:
        """Sunroom's version on top of Google's copy, If-Match the etag Sunroom last saw."""
        remote_id = series.remote_id
        assert remote_id is not None
        current = await self._client.get_event(calendar_id, remote_id)
        if current is None or _cancelled(current):
            raise SyncError(ErrorKind.CONFLICT, CHANGED)  # removed there: pull, then decide
        etag = _etag(current)
        if series.etag is not None and etag != series.etag:
            raise SyncError(ErrorKind.CONFLICT, CHANGED)
        wanted = {**ours, "recurrence": lines} if lines or current.get("recurrence") else ours
        return await self._client.update_event(
            calendar_id, remote_id, _onto(current, wanted), series.etag or etag
        )

    async def _push_occurrence(
        self,
        calendar_id: str,
        master_id: str,
        override: SyncedOverride,
        tzid: str,
        all_day: bool,
    ) -> None:
        """One changed occurrence, put to its instance id. An occurrence the rule no longer
        makes is left alone."""
        instance_id = _instance_id(master_id, override.recurrence_id, tzid, all_day)
        current = await self._client.get_event(calendar_id, instance_id)
        if current is None:
            return
        event = override.event
        ours = _body(event, tzid if event.timing.all_day else self._tzid(event))
        await self._client.update_event(
            calendar_id, instance_id, _onto(current, ours), _etag(current)
        )

    def _tzid(self, event: SyncedEvent) -> str:
        return (_zone(event.tzid) or self._household()).key


class _Reader:
    """One pull of one calendar: Google's events as series. A master is looked up at most once
    per pull."""

    def __init__(
        self, client: GoogleClient, calendar_id: str, zone: ZoneInfo, household: ZoneInfo
    ) -> None:
        self.client = client
        self.calendar_id = calendar_id
        self.zone = zone  # the calendar's own: for events that don't name one
        self.household = household
        self.masters: dict[str, dict[str, Any] | None] = {}
        self.refused = 0

    async def read(
        self, items: Sequence[dict[str, Any]], *, complete: bool
    ) -> tuple[list[SyncedSeries], list[str]]:
        masters: dict[str, dict[str, Any]] = {}
        exceptions: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            event_id = _text(item.get("id"))
            if not event_id or item.get("eventType") == "workingLocation":
                continue  # "Working from home" markers aren't events on a family's wall
            if parent := _text(item.get("recurringEventId")):
                exceptions[parent].append(item)
            else:
                masters[event_id] = item
        series: list[SyncedSeries] = []
        removed: list[str] = []
        for event_id, master in masters.items():
            family = exceptions.pop(event_id, [])
            if not complete and not _cancelled(master) and master.get("recurrence"):
                master, family = await self._whole(master, family)
            if _cancelled(master):
                if not complete:
                    removed.append(event_id)
                continue
            if (found := self.series(master, family)) is not None:
                series.append(found)
        for parent, family in exceptions.items():
            more, gone = await self._without_master(parent, family, complete=complete)
            series.extend(more)
            removed.extend(gone)
        return series, removed

    async def _whole(
        self, master: dict[str, Any], family: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """A recurring master that changed, read again with every exception: stored, a series is
        replaced whole, so the exceptions that didn't change belong in it too."""
        uid = _text(master.get("iCalUID"))
        event_id = _text(master.get("id"))
        if not uid:
            return master, family
        listed = await self.client.events_by_uid(self.calendar_id, uid)
        fresh = [item for item in listed if _text(item.get("id")) == event_id]
        if not fresh:
            return master, family
        kids = [item for item in listed if _text(item.get("recurringEventId")) == event_id]
        return fresh[0], kids

    async def _without_master(
        self, parent: str, family: list[dict[str, Any]], *, complete: bool
    ) -> tuple[list[SyncedSeries], list[str]]:
        """Exceptions whose master isn't in this listing: changed occurrences of a series that
        didn't change itself (a partial series), or occurrences of a series that lives in
        another calendar."""
        if parent not in self.masters:
            self.masters[parent] = await self.client.get_event(self.calendar_id, parent)
        master = self.masters[parent]
        if master is None:
            return self._orphans(family, complete=complete)
        if _cancelled(master):
            return [], []  # the series is gone; its removal comes on its own
        found = self.partial(master, family)
        return ([found] if found is not None else []), []

    def series(self, master: dict[str, Any], family: list[dict[str, Any]]) -> SyncedSeries | None:
        """A master and its exceptions as one series; None (and counted) when Sunroom can't
        show it."""
        read = self.event(master)
        uid = _text(master.get("iCalUID"))
        if read is None or not uid:
            self.refused += 1
            return None
        event, zone = read
        rrule: str | None = None
        rdates: tuple[str, ...] = ()
        exdates: tuple[str, ...] = ()
        overrides: tuple[SyncedOverride, ...] = ()
        if lines := _strings(master.get("recurrence")):
            try:
                rrule, rdates, exdates = parse_recurrence_lines(
                    lines, event.timing, event.tzid, self.household
                )
            except ValueError:  # RecurrenceError: a repeat Sunroom can't show
                self.refused += 1
                return None
            overrides = self._overrides(family, zone, all_day=event.timing.all_day)
        return SyncedSeries(
            uid=uid,
            master=event,
            rrule=rrule,
            rdates=rdates,
            exdates=exdates,
            overrides=overrides,
            remote_id=_text(master.get("id")),
            etag=_etag(master),
            updated_at=_instant(master.get("updated")),
            sequence=_sequence(master),
        )

    def partial(self, master: dict[str, Any], family: list[dict[str, Any]]) -> SyncedSeries | None:
        """Changed occurrences of a series whose master didn't change. The master's id, etag and
        sequence come along, so the stored series keeps them."""
        read = self.event(master)
        uid = _text(master.get("iCalUID"))
        if read is None or not uid or not master.get("recurrence"):
            return None
        event, zone = read
        overrides = self._overrides(family, zone, all_day=event.timing.all_day)
        if not overrides:
            return None
        stamps = [at for item in family if (at := _instant(item.get("updated"))) is not None]
        return SyncedSeries(
            uid=uid,
            master=None,
            overrides=overrides,
            remote_id=_text(master.get("id")),
            etag=_etag(master),
            updated_at=max(stamps, default=None),
            sequence=_sequence(master),
        )

    def _orphans(
        self, family: list[dict[str, Any]], *, complete: bool
    ) -> tuple[list[SyncedSeries], list[str]]:
        """Occurrences of a series that lives in another calendar: each one an event of its
        own, under its own id (its iCalUID is the whole series')."""
        series: list[SyncedSeries] = []
        removed: list[str] = []
        for item in family:
            event_id = _text(item.get("id"))
            if _cancelled(item):
                if not complete:
                    removed.append(event_id)
                continue
            read = self.event(item)
            if read is None:
                self.refused += 1
                continue
            series.append(
                SyncedSeries(
                    uid=event_id,
                    master=read[0],
                    remote_id=event_id,
                    etag=_etag(item),
                    updated_at=_instant(item.get("updated")),
                    sequence=_sequence(item),
                )
            )
        return series, removed

    def _overrides(
        self, family: list[dict[str, Any]], zone: ZoneInfo | None, *, all_day: bool
    ) -> tuple[SyncedOverride, ...]:
        found: dict[str, SyncedOverride] = {}
        for item in family:
            override = self.override(item, zone or self.zone, all_day=all_day)
            if override is not None:
                found[override.recurrence_id] = override
        return tuple(found[rid] for rid in sorted(found))

    def override(
        self, item: dict[str, Any], zone: ZoneInfo, *, all_day: bool
    ) -> SyncedOverride | None:
        """An exception by its original start, as a recurrence id in the series' zone."""
        rid = _rid(_object(item.get("originalStartTime")), zone, all_day=all_day)
        if rid is None:
            return None
        remote_id = _text(item.get("id")) or None
        if _cancelled(item):
            return SyncedOverride(rid, _cancelled_at(rid, zone), remote_id, _etag(item))
        read = self.event(item)
        if read is None:
            return None
        return SyncedOverride(rid, read[0], remote_id, _etag(item))

    def event(self, item: Mapping[str, Any]) -> tuple[SyncedEvent, ZoneInfo | None] | None:
        """An event's content and times, with the zone its times are in (None: all-day); None
        when Sunroom can't read its start."""
        start, end = _object(item.get("start")), _object(item.get("end"))
        title = _title(item.get("summary"))
        description = _description(item.get("description"))
        location = _location(item.get("location"))
        cancelled = _cancelled(item)
        first = _date(start.get("date"))
        if first is not None:  # all-day; Google's end date is exclusive, as the core's
            last = _date(end.get("date"))
            if last is None or last <= first:
                last = first + timedelta(days=1)
            timing = Timing(all_day=True, start_date=first, end_date=last)
            event = SyncedEvent(
                title=title,
                timing=timing,
                description=description,
                location=location,
                cancelled=cancelled,
            )
            return event, None
        zone = _zone(start.get("timeZone")) or self.zone
        begin = _instant(start.get("dateTime"), zone)
        if begin is None:
            return None
        finish = _instant(end.get("dateTime"), _zone(end.get("timeZone")) or zone)
        if finish is None or finish < begin:
            finish = begin
        event = SyncedEvent(
            title=title,
            timing=Timing(all_day=False, start_utc=begin, end_utc=finish),
            tzid=zone.key,
            description=description,
            location=location,
            cancelled=cancelled,
        )
        return event, zone


# ---- reading Google's events -------------------------------------------------------------------


def _rid(original: Mapping[str, Any], zone: ZoneInfo, *, all_day: bool) -> str | None:
    """``originalStartTime`` as a recurrence id: a date for an all-day series, else the wall
    time in the series' zone."""
    day = _date(original.get("date"))
    if day is not None:
        return rid_date(day)
    at = _instant(original.get("dateTime"), _zone(original.get("timeZone")) or zone)
    if at is None:
        return None
    local = to_local(at, zone)
    return rid_date(local.date()) if all_day else rid_timed(local)


def _cancelled_at(rid: str, zone: ZoneInfo) -> SyncedEvent:
    """A cancelled occurrence (Google sends only its id and original start): its slot."""
    value = parse_rid(rid)
    if isinstance(value, datetime):
        at = from_local(value, zone)
        timing = Timing(all_day=False, start_utc=at, end_utc=at)
        return SyncedEvent(title=NO_TITLE, timing=timing, tzid=zone.key, cancelled=True)
    timing = Timing(all_day=True, start_date=value, end_date=value + timedelta(days=1))
    return SyncedEvent(title=NO_TITLE, timing=timing, cancelled=True)


def _title(value: Any) -> str:
    return " ".join(_text(value).split())[:TITLE_MAX] or NO_TITLE


def _description(value: Any) -> str:
    return _plain(_text(value)).strip()[:DESCRIPTION_MAX]


def _location(value: Any) -> str:
    return _text(value).strip()[:LOCATION_MAX]


_HTML = re.compile(
    r"<(?:br|p|div|span|a|b|i|u|ol|ul|li|strong|em|html|body)\b[^>]*>"
    r"|&(?:[a-z]+|#[0-9]+|#x[0-9a-f]+);",
    re.IGNORECASE,
)
_BREAK = re.compile(r"<br\s*/?>|</(?:p|div|li|ol|ul)\s*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
_BLANK_LINES = re.compile(r"\n{3,}")


def _plain(text: str) -> str:
    """A description as text. Google's own apps write HTML (line breaks as <br>, links,
    &amp;); text that isn't HTML stays as it is."""
    if not _HTML.search(text):
        return text
    text = unescape(_TAG.sub("", _BREAK.sub("\n", text))).replace("\xa0", " ")
    return _BLANK_LINES.sub("\n\n", "\n".join(line.rstrip() for line in text.splitlines()))


def _cancelled(item: Mapping[str, Any]) -> bool:
    return item.get("status") == "cancelled"


def _etag(item: Mapping[str, Any]) -> str | None:
    return _text(item.get("etag")) or None


def _sequence(item: Mapping[str, Any]) -> int | None:
    value = item.get("sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _zone(name: Any) -> ZoneInfo | None:
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        return ZoneInfo(name.strip())
    except ZoneInfoNotFoundError, ValueError:
        return None


def _instant(value: Any, zone: ZoneInfo | None = None) -> datetime | None:
    """An RFC 3339 time as an aware UTC instant. One without an offset is wall time in
    ``zone``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return from_local(moment, zone) if zone is not None else None
    return moment.astimezone(UTC)


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[Any], value) if isinstance(item, str) and item.strip()]


def _object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_object(item) for item in cast(list[Any], value) if isinstance(item, dict)]


def _json_object(content: bytes) -> dict[str, Any]:
    try:
        return _object(json.loads(content))
    except ValueError:
        return {}


# ---- writing Google's events -------------------------------------------------------------------


def _body(event: SyncedEvent, tzid: str) -> dict[str, Any]:
    """What Sunroom keeps of an event, as Google writes it. Timed events carry their zone, which
    a repeating one needs (its rule runs in it)."""
    timing = event.timing
    if timing.all_day:
        assert timing.start_date is not None and timing.end_date is not None
        start: dict[str, str] = {"date": timing.start_date.isoformat()}
        end: dict[str, str] = {"date": timing.end_date.isoformat()}
    else:
        assert timing.start_utc is not None and timing.end_utc is not None
        zone = ZoneInfo(tzid)
        start = {"dateTime": _rfc3339(timing.start_utc, zone), "timeZone": tzid}
        end = {"dateTime": _rfc3339(timing.end_utc, zone), "timeZone": tzid}
    return {
        "summary": event.title,
        "description": event.description,
        "location": event.location,
        "start": start,
        "end": end,
    }


def _rfc3339(instant: datetime, zone: ZoneInfo) -> str:
    return instant.astimezone(zone).isoformat(timespec="seconds")


def _recurrence(series: SyncedSeries) -> list[str]:
    """The series' RRULE, EXDATE and RDATE lines; its cancelled occurrences are EXDATEs."""
    if not series.rrule and not series.rdates:
        return []
    cancelled = {o.recurrence_id for o in series.overrides if o.event.cancelled}
    return recurrence_lines(replace(series, exdates=tuple(sorted({*series.exdates, *cancelled}))))


def _onto(current: Mapping[str, Any], ours: Mapping[str, Any]) -> dict[str, Any]:
    """Sunroom's fields on Google's own copy, so what Sunroom doesn't keep (guests, reminders,
    colors, video links, attachments) stays. Text Sunroom read but didn't change keeps Google's
    spelling of it (HTML, or more than Sunroom stores)."""
    merged = {**current, **ours}
    reads: tuple[tuple[str, Callable[[Any], str]], ...] = (
        ("summary", _title),
        ("description", _description),
        ("location", _location),
    )
    for name, read in reads:
        if name in ours and read(current.get(name)) == ours[name]:
            if name in current:
                merged[name] = current[name]
            else:
                merged.pop(name)
    if merged.get("status") == "cancelled":
        merged["status"] = "confirmed"  # put back
    if current.get("recurringEventId"):
        merged.pop("recurrence", None)  # an occurrence repeats only as part of its series
    return merged


def _instance_id(master_id: str, rid: str, tzid: str, all_day: bool) -> str:
    """Google's id for one occurrence: the master's id, "_", then the original start in UTC
    (20261014T200000Z), or the date (20261014) in an all-day series."""
    value = parse_rid(rid)
    if isinstance(value, datetime) and not all_day:
        start = from_local(value, ZoneInfo(tzid))
        return f"{master_id}_{start:%Y%m%dT%H%M%SZ}"
    day = value.date() if isinstance(value, datetime) else value
    return f"{master_id}_{day:%Y%m%d}"
