"""The Google Calendar client and provider (PLAN §8.1, ADR 0004, ADR 0024) against a scripted
Google: its token endpoint (the helper's signed JWT, a refresh token, a sign-in code) and enough
of Calendar v3 to list calendars, sync events with tokens, and write them with etags.

Every request goes through the real guarded client and PluginHttp. A fake resolver and httpx's
MockTransport stand in for the network, so no socket is opened. The helper's RSA key is made for
the run and never written down. The clock reads Wednesday 2026-10-07, 10:00 in New York.
Synthetic data only: the Sample Family's calendars on example.com addresses.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import string
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from functools import cache
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sunroom.calendar.synced import PendingSeries, SyncedEvent, SyncedOverride, SyncedSeries
from sunroom.core.clock import FakeClock
from sunroom.core.http import GuardedHttp
from sunroom.core.lang import t_en
from sunroom.core.netguard import NetGuard
from sunroom.domain.recurrence import Override, Series, Timing, Window, expand
from sunroom.plugins.calendar_sync.ical import NO_TITLE
from sunroom.plugins.calendar_sync.providers.base import ErrorKind, RemoteCalendar, SyncError
from sunroom.plugins.calendar_sync.providers.google import (
    ACCOUNT_REFUSED,
    API_OFF,
    CALENDAR_GONE,
    CANT_SEE,
    CHANGED,
    CLIENT_REFUSED,
    CLOCK_WRONG,
    EVENT_GONE,
    HELPER_REFUSED,
    JWT_BEARER,
    KEY_AGAIN,
    KEY_REFUSED,
    NO_ANSWER,
    NOT_A_KEY,
    NOT_SHARED,
    REJECTED,
    SCOPE,
    SIGN_IN_FAILED,
    SIGNED_OUT,
    SLOW_DOWN,
    TOKEN_URL,
    UNREADABLE,
    GoogleClient,
    GoogleProvider,
    OAuthAuth,
    ServiceAccountAuth,
    SyncTokenExpired,
    authorize_url,
    exchange_code,
    new_pkce,
    parse_service_account_key,
)
from sunroom.plugins.context import PluginHttp

PUBLIC = "93.184.216.34"  # every host resolves here: a public address, so the guard lets it by
TOKEN_HOST = "oauth2.googleapis.com"
API_HOST = "www.googleapis.com"
HELPER = "sunroom-helper@sample-family.iam.gserviceaccount.com"
KEY_ID = "test-key-1"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
REFRESH = "test-refresh-token"
REDIRECT = "https://calendar.example.com/api/calendar-sync/google/callback"
NEW_YORK = "America/New_York"
LOS_ANGELES = "America/Los_Angeles"
FAMILY = "family#shared@example.com"  # a calendar id with characters a path has to escape
SCHOOL = "school@example.com"
FAMILY_CALENDAR = RemoteCalendar(FAMILY, "Family")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


# ---- the helper's key ---------------------------------------------------------------------------


@cache
def rsa_key() -> rsa.RSAPrivateKey:
    """The helper's key, made for this run."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(key: rsa.RSAPrivateKey | None = None) -> str:
    return (
        (key or rsa_key())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def key_file(**changes: Any) -> dict[str, Any]:
    """A service account's JSON key, shaped as Google's console downloads it."""
    key: dict[str, Any] = {
        "type": "service_account",
        "project_id": "sample-family",
        "private_key_id": KEY_ID,
        "private_key": pem(),
        "client_email": HELPER,
        "client_id": "100000000000000000001",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URL,
    }
    key.update(changes)
    return key


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---- a scripted Google --------------------------------------------------------------------------


def google_error(
    status: int, reason: str, message: str = "Error", headers: dict[str, str] | None = None
) -> httpx.Response:
    body = {
        "error": {
            "errors": [{"domain": "global", "reason": reason, "message": message}],
            "code": status,
            "message": message,
        }
    }
    return httpx.Response(status, json=body, headers=headers)


def oauth_error(error: str, description: str, status: int = 400) -> httpx.Response:
    return httpx.Response(status, json={"error": error, "error_description": description})


async def resolve_public(host: str, port: int) -> list[str]:
    await asyncio.sleep(0)  # a real wait, so calls made together interleave
    return [PUBLIC]


@dataclass
class Stored:
    body: dict[str, Any]  # as Google shows it
    uid: str  # the iCalUID, kept when the body is cut down to a deleted event's
    revision: int


class FakeGoogle:
    """Google's token endpoint and Calendar v3, as far as Sunroom uses them: tokens that expire
    and can be revoked, calendar lists, events with etags and a change log behind sync tokens,
    occurrences by instance id, and failures on demand."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.page_size = 2500
        self.calendars: dict[str, dict[str, Any]] = {}  # the account's calendar list
        self.shared: dict[str, dict[str, Any]] = {}  # shared with the helper, not listed yet
        self.events: dict[str, dict[str, Stored]] = {}
        self.revision = 0
        self.created = 0
        self.forgotten: set[str] = set()  # sync tokens answered with 410
        self.tokens: set[str] = set()  # access tokens that work
        self.issued: list[str] = []
        self.grants: list[dict[str, str]] = []  # each token request's form
        self.jwt_headers: list[dict[str, Any]] = []
        self.jwt_claims: list[dict[str, Any]] = []
        self.refresh_tokens = {REFRESH}
        self.codes: dict[str, str] = {}  # a sign-in code -> its PKCE challenge
        self.redirect = REDIRECT  # the redirect address the OAuth client was registered with
        self.fail: list[tuple[str, httpx.Response]] = []  # (method or "*", reply), API only
        self.token_fail: list[httpx.Response] = []
        self.down = False
        self.revoked = False  # Google takes no token at all
        self.seen: list[httpx.Request] = []
        self.sent: list[tuple[str, str, dict[str, Any]]] = []  # (method, event id, body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Every request Sunroom sends, as Google would answer it (also served to a test app)."""
        self.seen.append(request)
        host = request.headers["host"]
        if host == TOKEN_HOST:
            return self.token(request)
        if host == API_HOST and not self.down:
            return self.api(request)
        raise httpx.ConnectError("no route to host", request=request)

    def http(self) -> PluginHttp:
        guarded = GuardedHttp(
            NetGuard(resolver=resolve_public),
            transport_factory=lambda: httpx.MockTransport(self.handle),
        )
        return PluginHttp(guarded, allow_private=False)

    # ---- scripting ----------------------------------------------------------------------------

    def add_calendar(
        self,
        calendar_id: str,
        summary: str,
        *,
        role: str = "owner",
        color: str = "#9fe1e7",
        zone: str = NEW_YORK,
        listed: bool = True,
        **extra: Any,
    ) -> None:
        entry = {
            "kind": "calendar#calendarListEntry",
            "id": calendar_id,
            "summary": summary,
            "timeZone": zone,
            "backgroundColor": color,
            "accessRole": role,
            **extra,
        }
        (self.calendars if listed else self.shared)[calendar_id] = entry
        self.events.setdefault(calendar_id, {})

    def put(self, calendar_id: str, body: dict[str, Any], *, uid: str | None = None) -> None:
        """Store an event as Google would: a new etag, ``updated``, a place in the change log."""
        self.save(calendar_id, body, uid=uid)

    def cancel(self, calendar_id: str, event_id: str) -> None:
        stored = self.events[calendar_id][event_id]
        self.save(calendar_id, {**stored.body, "status": "cancelled"}, uid=stored.uid)

    def body(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        return self.events[calendar_id][event_id].body

    def save(
        self, calendar_id: str, body: dict[str, Any], *, uid: str | None = None
    ) -> dict[str, Any]:
        store = self.events[calendar_id]
        event_id = str(body["id"])
        before = store.get(event_id)
        master = store.get(str(body.get("recurringEventId", "")))
        uid = (
            uid
            or (before.uid if before else None)
            or (master.uid if master else None)
            or f"{event_id}@example.com"
        )
        self.revision += 1
        full: dict[str, Any] = {
            "kind": "calendar#event",
            **body,
            "etag": f'"{self.revision}"',
            "updated": self.clock.now().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        if full.get("status") == "cancelled":  # Google shows little of a deleted event
            shown = ("kind", "etag", "id", "status", "recurringEventId", "originalStartTime")
            full = {name: full[name] for name in shown if name in full}
        else:
            full.setdefault("status", "confirmed")
            full["iCalUID"] = uid
        store[event_id] = Stored(full, uid, self.revision)
        return full

    def sync_token(self) -> str:
        return f"sync-{self.revision}"

    # ---- the token endpoint -------------------------------------------------------------------

    def token(self, request: httpx.Request) -> httpx.Response:
        if self.token_fail:
            return self.token_fail.pop(0)
        form = dict(parse_qsl(request.content.decode()))
        self.grants.append(form)
        grant = form.get("grant_type")
        if grant == JWT_BEARER:
            if not self.verify(form.get("assertion", "")):
                return oauth_error("invalid_grant", "Invalid JWT Signature.")
            return self.issue()
        if (form.get("client_id"), form.get("client_secret")) != (CLIENT_ID, CLIENT_SECRET):
            return oauth_error("invalid_client", "Unauthorized", status=401)
        if grant == "refresh_token":
            if form.get("refresh_token") not in self.refresh_tokens:
                return oauth_error("invalid_grant", "Token has been expired or revoked.")
            return self.issue()
        if grant == "authorization_code":
            challenge = self.codes.pop(form.get("code", ""), None)
            verifier = form.get("code_verifier", "").encode()
            if challenge != b64(hashlib.sha256(verifier).digest()) or (
                form.get("redirect_uri") != self.redirect
            ):
                return oauth_error("invalid_grant", "Bad Request")
            return self.issue(refresh_token=REFRESH, scope=SCOPE)
        return oauth_error("unsupported_grant_type", "Invalid grant_type")

    def issue(self, **extra: str) -> httpx.Response:
        token = f"test-access-{len(self.issued) + 1}"
        self.issued.append(token)
        self.tokens.add(token)
        body = {"access_token": token, "expires_in": 3599, "token_type": "Bearer", **extra}
        return httpx.Response(200, json=body)

    def verify(self, assertion: str) -> bool:
        """The JWT is signed by the helper's key; its header and claims are kept to check."""
        try:
            head, claims, signature = assertion.split(".")
            rsa_key().public_key().verify(
                unb64(signature), f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
            )
        except ValueError, InvalidSignature:
            return False
        self.jwt_headers.append(json.loads(unb64(head)))
        self.jwt_claims.append(json.loads(unb64(claims)))
        return True

    # ---- Calendar v3 --------------------------------------------------------------------------

    def api(self, request: httpx.Request) -> httpx.Response:
        for index, (method, reply) in enumerate(self.fail):
            if method in (request.method, "*"):
                del self.fail[index]
                return reply
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if self.revoked or token not in self.tokens:
            return google_error(401, "authError", "Invalid Credentials")
        path = request.url.raw_path.decode().partition("?")[0]
        parts = [unquote(part) for part in path.split("/")][3:]  # after /calendar/v3
        query = dict(request.url.params)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if_match = request.headers.get("if-match")
        match parts, request.method:
            case ["users", "me", "calendarList"], "GET":
                return self.list_calendars(query)
            case ["users", "me", "calendarList"], "POST":
                return self.add_to_list(str(body.get("id")))
            case ["users", "me", "calendarList", calendar_id], "GET":
                entry = self.calendars.get(calendar_id)
                return httpx.Response(200, json=entry) if entry else google_error(404, "notFound")
            case ["calendars", calendar_id, "events"], "GET":
                return self.list_events(calendar_id, query)
            case ["calendars", calendar_id, "events"], "POST":
                return self.insert(calendar_id, body)
            case ["calendars", calendar_id, "events", event_id], "GET":
                found = self.find(calendar_id, event_id)
                if found is None:
                    return google_error(404, "notFound", "Not Found")
                return httpx.Response(200, json=found.body)
            case ["calendars", calendar_id, "events", event_id], "PUT":
                return self.update(calendar_id, event_id, body, if_match)
            case ["calendars", calendar_id, "events", event_id], "DELETE":
                return self.delete(calendar_id, event_id, if_match)
            case _:
                return google_error(404, "notFound", "Not Found")

    def list_calendars(self, query: dict[str, str]) -> httpx.Response:
        items = list(self.calendars.values())
        offset = int(query.get("pageToken", "0"))
        size = int(query.get("maxResults", "100"))
        reply: dict[str, Any] = {"items": items[offset : offset + size]}
        if offset + size < len(items):
            reply["nextPageToken"] = str(offset + size)
        return httpx.Response(200, json=reply)

    def add_to_list(self, calendar_id: str) -> httpx.Response:
        if calendar_id in self.calendars:
            return google_error(409, "duplicate", "The requested identifier already exists.")
        entry = self.shared.pop(calendar_id, None)
        if entry is None:
            return google_error(404, "notFound", "Not Found")
        self.calendars[calendar_id] = entry
        return httpx.Response(200, json=entry)

    def list_events(self, calendar_id: str, query: dict[str, str]) -> httpx.Response:
        store = self.events.get(calendar_id)
        if store is None:
            return google_error(404, "notFound", "Not Found")
        items = sorted(store.values(), key=lambda stored: stored.revision)
        token = query.get("syncToken")
        if token is not None:
            if not token.startswith("sync-"):
                return google_error(400, "invalid", "Invalid sync token value.")
            if token in self.forgotten:
                return google_error(410, "fullSyncRequired", "Sync token is no longer valid.")
            since = int(token.removeprefix("sync-"))
            items = [stored for stored in items if stored.revision > since]
        if "iCalUID" in query:
            items = [stored for stored in items if stored.uid == query["iCalUID"]]
        offset = int(query.get("pageToken", "0"))
        page = items[offset : offset + self.page_size]
        entry = self.calendars.get(calendar_id) or self.shared.get(calendar_id) or {}
        reply: dict[str, Any] = {
            "kind": "calendar#events",
            "timeZone": entry.get("timeZone", NEW_YORK),
            "items": [stored.body for stored in page],
        }
        if offset + self.page_size < len(items):
            reply["nextPageToken"] = str(offset + self.page_size)
        else:
            reply["nextSyncToken"] = self.sync_token()
        return httpx.Response(200, json=reply)

    def find(self, calendar_id: str, event_id: str) -> Stored | None:
        """An event, or an occurrence of a series by its instance id."""
        store = self.events.get(calendar_id, {})
        if event_id in store:
            return store[event_id]
        master_id, _, suffix = event_id.rpartition("_")
        master = store.get(master_id)
        if master is None or "recurrence" not in master.body:
            return None
        return Stored(self.instance(master.body, event_id, suffix), master.uid, master.revision)

    def instance(self, master: dict[str, Any], event_id: str, suffix: str) -> dict[str, Any]:
        """An occurrence the rule makes, as Google shows one nobody changed."""
        start: dict[str, Any]
        end: dict[str, Any]
        if "date" in master["start"]:
            day = date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
            length = date.fromisoformat(master["end"]["date"]) - date.fromisoformat(
                master["start"]["date"]
            )
            start, end = {"date": day.isoformat()}, {"date": (day + length).isoformat()}
        else:
            zone = ZoneInfo(master["start"]["timeZone"])
            at = datetime(
                int(suffix[:4]),
                int(suffix[4:6]),
                int(suffix[6:8]),
                int(suffix[9:11]),
                int(suffix[11:13]),
                tzinfo=UTC,
            ).astimezone(zone)
            length = datetime.fromisoformat(master["end"]["dateTime"]) - datetime.fromisoformat(
                master["start"]["dateTime"]
            )
            start = {"dateTime": at.isoformat(), "timeZone": zone.key}
            end = {"dateTime": (at + length).isoformat(), "timeZone": zone.key}
        return {
            "kind": "calendar#event",
            "etag": master["etag"],
            "id": event_id,
            "status": "confirmed",
            "summary": master.get("summary", ""),
            "iCalUID": master["iCalUID"],
            "recurringEventId": master["id"],
            "originalStartTime": start,
            "start": start,
            "end": end,
        }

    def insert(self, calendar_id: str, body: dict[str, Any]) -> httpx.Response:
        store = self.events.get(calendar_id)
        if store is None:
            return google_error(404, "notFound", "Not Found")
        uid = body.get("iCalUID")
        taken = [s for s in store.values() if s.uid == uid and "recurringEventId" not in s.body]
        if uid and taken:  # Google keeps a deleted event's iCalUID too
            return google_error(409, "duplicate", "The requested identifier already exists.")
        self.created += 1
        event_id = f"new{self.created:04d}"
        self.sent.append(("POST", event_id, body))
        saved = self.save(calendar_id, {**body, "id": event_id}, uid=str(uid) if uid else None)
        return httpx.Response(200, json=saved)

    def update(
        self, calendar_id: str, event_id: str, body: dict[str, Any], if_match: str | None
    ) -> httpx.Response:
        current = self.find(calendar_id, event_id)
        if current is None:
            return google_error(404, "notFound", "Not Found")
        if if_match is not None and if_match != current.body.get("etag"):
            return google_error(412, "conditionNotMet", "Precondition Failed")
        self.sent.append(("PUT", event_id, body))
        kept = {
            name: current.body[name]
            for name in ("recurringEventId", "originalStartTime")
            if name in current.body
        }
        saved = self.save(calendar_id, {**body, **kept, "id": event_id}, uid=current.uid)
        return httpx.Response(200, json=saved)

    def delete(self, calendar_id: str, event_id: str, if_match: str | None) -> httpx.Response:
        current = self.events.get(calendar_id, {}).get(event_id)
        if current is None:
            return google_error(404, "notFound", "Not Found")
        if current.body.get("status") == "cancelled":
            return google_error(410, "deleted", "Resource has been deleted")
        if if_match is not None and if_match != current.body.get("etag"):
            return google_error(412, "conditionNotMet", "Precondition Failed")
        self.sent.append(("DELETE", event_id, {}))
        self.cancel(calendar_id, event_id)
        return httpx.Response(204)

    # ---- what Sunroom asked -------------------------------------------------------------------

    def api_requests(self) -> list[httpx.Request]:
        return [request for request in self.seen if request.headers["host"] == API_HOST]

    def asked(self) -> list[tuple[str, str]]:
        """(method, path after /calendar/v3) of each API request, with escapes undone."""
        return [
            (request.method, unquote(request.url.raw_path.decode().partition("?")[0])[12:])
            for request in self.api_requests()
        ]


# ---- events as Google writes them ---------------------------------------------------------------


def timed(
    event_id: str, title: str, start: str, end: str, zone: str = NEW_YORK, **extra: Any
) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start, "timeZone": zone},
        "end": {"dateTime": end, "timeZone": zone},
        **extra,
    }


def instance_id(master_id: str, original: str) -> str:
    return f"{master_id}_{utc(original):%Y%m%dT%H%M%SZ}"


def moved(
    master_id: str, original: str, title: str, start: str, end: str, zone: str = NEW_YORK
) -> dict[str, Any]:
    """An occurrence moved: its own times, and the start the rule gave it."""
    return {
        **timed(instance_id(master_id, original), title, start, end, zone),
        "recurringEventId": master_id,
        "originalStartTime": {"dateTime": original, "timeZone": zone},
    }


def cancelled(master_id: str, original: str, zone: str = NEW_YORK) -> dict[str, Any]:
    return {
        "id": instance_id(master_id, original),
        "status": "cancelled",
        "recurringEventId": master_id,
        "originalStartTime": {"dateTime": original, "timeZone": zone},
    }


def piano(google: FakeGoogle) -> None:
    """Piano on Wednesdays at 4 in New York: the second one moved to Thursday at 5, the third
    cancelled."""
    google.put(
        FAMILY,
        timed(
            "piano01",
            "Piano lesson",
            "2026-10-07T16:00:00-04:00",
            "2026-10-07T17:00:00-04:00",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=WE"],
        ),
        uid="piano@example.com",
    )
    google.put(
        FAMILY,
        moved(
            "piano01",
            "2026-10-14T16:00:00-04:00",
            "Piano lesson (Thursday)",
            "2026-10-15T17:00:00-04:00",
            "2026-10-15T18:00:00-04:00",
        ),
    )
    google.put(FAMILY, cancelled("piano01", "2026-10-21T16:00:00-04:00"))


def family(google: FakeGoogle) -> None:
    """Piano, plus a two-day school trip, a call set in Los Angeles' time, Saturday soccer in
    Los Angeles' time with one week skipped and one moved, a working-location marker, and an
    event someone deleted."""
    piano(google)
    google.put(
        FAMILY,
        {
            "id": "trip01",
            "summary": "School trip",
            "start": {"date": "2026-10-09"},
            "end": {"date": "2026-10-11"},
        },
        uid="trip@example.com",
    )
    google.put(
        FAMILY,
        timed(
            "call01",
            "Call with Leo",
            "2026-10-08T09:00:00-07:00",
            "2026-10-08T09:30:00-07:00",
            zone=LOS_ANGELES,
            description="Bring <b>the photos</b><br>and Mia's drawing &amp; card",
            location="  Kitchen  ",
        ),
        uid="call@example.com",
    )
    google.put(
        FAMILY,
        timed(
            "soccer01",
            "Soccer",
            "2026-10-10T09:00:00-07:00",
            "2026-10-10T10:30:00-07:00",
            zone=LOS_ANGELES,
            recurrence=[
                "RRULE:FREQ=WEEKLY;BYDAY=SA",
                "EXDATE;TZID=America/Los_Angeles:20261017T090000",
            ],
        ),
        uid="soccer@example.com",
    )
    # Moved, with its original start written in New York's time: still 9:00 in the series' zone.
    google.put(
        FAMILY,
        {
            **moved(
                "soccer01",
                "2026-10-24T12:00:00-04:00",
                "Soccer (away)",
                "2026-10-24T13:00:00-07:00",
                "2026-10-24T14:30:00-07:00",
                zone=LOS_ANGELES,
            ),
            "originalStartTime": {"dateTime": "2026-10-24T12:00:00-04:00", "timeZone": NEW_YORK},
        },
    )
    google.put(
        FAMILY,
        {
            "id": "where01",
            "eventType": "workingLocation",
            "summary": "Home",
            "start": {"date": "2026-10-08"},
            "end": {"date": "2026-10-09"},
        },
    )
    google.put(FAMILY, {"id": "gone01", "summary": "Old plan", "start": {"date": "2026-10-01"}})
    google.cancel(FAMILY, "gone01")


# ---- building the pieces ------------------------------------------------------------------------


@pytest.fixture
def google(clock: FakeClock) -> FakeGoogle:
    server = FakeGoogle(clock)
    server.add_calendar(FAMILY, "Family")
    return server


def helper_client(google: FakeGoogle, clock: FakeClock) -> GoogleClient:
    http = google.http()
    return GoogleClient(http, ServiceAccountAuth(key_file(), http, clock.now))


def account_client(google: FakeGoogle, clock: FakeClock) -> GoogleClient:
    http = google.http()
    return GoogleClient(http, OAuthAuth(CLIENT_ID, CLIENT_SECRET, REFRESH, http, clock.now))


def provider(google: FakeGoogle, clock: FakeClock) -> GoogleProvider:
    return GoogleProvider(helper_client(google, clock), lambda: ZoneInfo(NEW_YORK), clock.now)


def by_uid(series: list[SyncedSeries]) -> dict[str, SyncedSeries]:
    return {item.uid: item for item in series}


def pending(series: SyncedSeries, *, deleted: bool = False) -> PendingSeries:
    return PendingSeries(
        event_id="local-1", calendar_id="calendar-1", series=series, deleted=deleted, version=1
    )


def at(start: str, end: str) -> Timing:
    return Timing(all_day=False, start_utc=utc(start), end_utc=utc(end))


async def failure(call: Awaitable[object]) -> SyncError:
    with pytest.raises(SyncError) as caught:
        await call
    return caught.value


# ---- the helper's key and tokens ----------------------------------------------------------------


async def test_the_helper_signs_a_jwt_google_accepts(google: FakeGoogle, clock: FakeClock) -> None:
    http = google.http()
    auth = ServiceAccountAuth(key_file(), http, clock.now)
    assert auth.helper and auth.email == HELPER
    assert await auth.access_token() == "test-access-1"

    issued = int(clock.now().timestamp())
    assert google.grants[0]["grant_type"] == JWT_BEARER
    assert google.jwt_headers == [{"alg": "RS256", "typ": "JWT", "kid": KEY_ID}]
    assert google.jwt_claims == [
        {"iss": HELPER, "scope": SCOPE, "aud": TOKEN_URL, "iat": issued, "exp": issued + 3600}
    ]
    # The signature checks out with the key's public half, here as well as at "Google".
    head, claims, signature = auth.assertion().split(".")
    rsa_key().public_key().verify(
        unb64(signature), f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    # The token went to Google's token host, by POST, as a form.
    request = google.seen[0]
    assert (request.method, request.headers["host"], request.url.path) == (
        "POST",
        TOKEN_HOST,
        "/token",
    )
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"


async def test_tokens_are_kept_and_fetched_one_at_a_time(
    google: FakeGoogle, clock: FakeClock
) -> None:
    auth = ServiceAccountAuth(key_file(), google.http(), clock.now)
    first, second = await asyncio.gather(auth.access_token(), auth.access_token())
    assert first == second == "test-access-1"
    assert len(google.grants) == 1  # one fetch; the other caller waited for it

    clock.advance(minutes=30)
    assert await auth.access_token() == "test-access-1"
    clock.advance(seconds=3539 - 1800)  # a minute before it runs out (it lasts 3599 s)
    assert await auth.access_token() == "test-access-2"
    assert len(google.grants) == 2

    # A token Google refused is replaced, once, however many callers saw it refused.
    fresh = await asyncio.gather(
        auth.access_token(stale="test-access-2"), auth.access_token(stale="test-access-2")
    )
    assert fresh == ["test-access-3", "test-access-3"]
    assert await auth.access_token(stale="test-access-1") == "test-access-3"
    assert len(google.grants) == 3


async def test_a_key_google_turns_down_asks_for_a_new_one(
    google: FakeGoogle, clock: FakeClock
) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = ServiceAccountAuth(key_file(private_key=pem(other)), google.http(), clock.now)
    error = await failure(auth.access_token())
    assert (error.kind, error.key) == (ErrorKind.AUTH, KEY_REFUSED)

    # A clock that's off is said plainly, and doesn't ask for a new key.
    google.token_fail.append(
        oauth_error(
            "invalid_grant",
            "Invalid JWT: Token must be a short-lived token (60 minutes) and in a reasonable "
            "timeframe. Check your iat and exp values in the JWT claim.",
        )
    )
    error = await failure(ServiceAccountAuth(key_file(), google.http(), clock.now).access_token())
    assert (error.kind, error.key) == (ErrorKind.REFUSED, CLOCK_WRONG)

    with pytest.raises(SyncError) as caught:
        ServiceAccountAuth(key_file(private_key="not a key"), google.http(), clock.now)
    assert (caught.value.kind, caught.value.key) == (ErrorKind.AUTH, KEY_AGAIN)


async def test_the_token_endpoint_failing_says_so(google: FakeGoogle, clock: FakeClock) -> None:
    auth = OAuthAuth(CLIENT_ID, CLIENT_SECRET, REFRESH, google.http(), clock.now)
    google.token_fail.append(httpx.Response(503))
    error = await failure(auth.access_token())
    assert (error.kind, error.key) == (ErrorKind.UNREACHABLE, NO_ANSWER)
    google.token_fail.append(httpx.Response(429, headers={"Retry-After": "120"}))
    error = await failure(auth.access_token())
    assert (error.kind, error.key, error.retry_after) == (
        ErrorKind.RATE_LIMITED,
        SLOW_DOWN,
        120.0,
    )
    google.token_fail.append(httpx.Response(200, text="<html>not json</html>"))
    error = await failure(auth.access_token())
    assert (error.kind, error.key) == (ErrorKind.BAD_DATA, UNREADABLE)


def test_an_uploaded_key_is_checked() -> None:
    key = parse_service_account_key(json.dumps(key_file()))
    assert key == {
        "type": "service_account",
        "client_email": HELPER,
        "private_key": pem(),
        "token_uri": TOKEN_URL,
        "private_key_id": KEY_ID,
        "project_id": "sample-family",
    }
    without_token_uri = {k: v for k, v in key_file().items() if k != "token_uri"}
    assert parse_service_account_key(json.dumps(without_token_uri))["token_uri"] == TOKEN_URL


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "[]",
        json.dumps(key_file(type="authorized_user")),
        json.dumps({k: v for k, v in key_file().items() if k != "client_email"}),
        json.dumps(key_file(client_email="not-an-address")),
        json.dumps(key_file(private_key="not a key")),
        json.dumps(key_file(private_key=pem()[:200])),
        json.dumps(key_file(token_uri="https://token.example.com/token")),
        json.dumps(key_file(token_uri=["https://oauth2.googleapis.com/token"])),
        json.dumps({"web": {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}}),
        json.dumps(key_file(padding="x" * 70_000)),
    ],
)
def test_anything_else_is_not_a_key(text: str) -> None:
    with pytest.raises(ValueError, match=r"^That isn't a Google key file\.") as caught:
        parse_service_account_key(text)
    assert str(caught.value) == t_en(NOT_A_KEY)


# ---- signing in ---------------------------------------------------------------------------------


def test_pkce_and_the_sign_in_address() -> None:
    verifier, challenge = new_pkce()
    assert 43 <= len(verifier) <= 128
    assert set(verifier) <= set(string.ascii_letters + string.digits + "-._~")
    assert challenge == b64(hashlib.sha256(verifier.encode()).digest())
    assert "=" not in challenge
    assert new_pkce()[0] != verifier

    address = urlsplit(authorize_url(CLIENT_ID, REDIRECT, "state-1", challenge))
    assert (address.scheme, address.hostname, address.path) == (
        "https",
        "accounts.google.com",
        "/o/oauth2/v2/auth",
    )
    assert dict(parse_qsl(address.query)) == {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": "state-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


async def test_a_sign_in_code_is_traded_for_tokens(google: FakeGoogle) -> None:
    http = google.http()
    verifier, challenge = new_pkce()
    google.codes["code-1"] = challenge
    tokens = await exchange_code(http, CLIENT_ID, CLIENT_SECRET, "code-1", verifier, REDIRECT)
    assert tokens == {"refresh_token": REFRESH, "access_token": "test-access-1", "expires_in": 3599}
    assert google.grants[0] == {
        "grant_type": "authorization_code",
        "code": "code-1",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT,
        "code_verifier": verifier,
    }
    # A code works once; a wrong verifier never; a wrong secret says which part is wrong.
    error = await failure(
        exchange_code(http, CLIENT_ID, CLIENT_SECRET, "code-1", verifier, REDIRECT)
    )
    assert (error.kind, error.key) == (ErrorKind.AUTH, SIGN_IN_FAILED)
    google.codes["code-2"] = challenge
    error = await failure(
        exchange_code(http, CLIENT_ID, CLIENT_SECRET, "code-2", new_pkce()[0], REDIRECT)
    )
    assert (error.kind, error.key) == (ErrorKind.AUTH, SIGN_IN_FAILED)
    error = await failure(exchange_code(http, CLIENT_ID, "wrong", "code-3", verifier, REDIRECT))
    assert (error.kind, error.key) == (ErrorKind.AUTH, CLIENT_REFUSED)


async def test_a_signed_in_account_refreshes_until_google_signs_it_out(
    google: FakeGoogle, clock: FakeClock
) -> None:
    auth = OAuthAuth(CLIENT_ID, CLIENT_SECRET, REFRESH, google.http(), clock.now)
    assert not auth.helper
    assert await auth.access_token() == "test-access-1"
    assert google.grants[0] == {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH,
    }
    google.refresh_tokens.clear()  # revoked, or the app was left in Testing for 7 days
    clock.advance(hours=1)
    error = await failure(auth.access_token())
    assert (error.kind, error.key) == (ErrorKind.AUTH, SIGNED_OUT)
    wrong = OAuthAuth(CLIENT_ID, "wrong", REFRESH, google.http(), clock.now)
    error = await failure(wrong.access_token())
    assert (error.kind, error.key) == (ErrorKind.AUTH, CLIENT_REFUSED)


# ---- calendars ----------------------------------------------------------------------------------


async def test_calendars_are_listed_with_their_colors_rights_and_zones(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.add_calendar(SCHOOL, "Sample School", role="reader", color="#A47AE2", zone=LOS_ANGELES)
    google.add_calendar("ana@example.com", "ana@example.com", summaryOverride="Ana", role="writer")
    google.add_calendar(HELPER, HELPER, primary=True)  # the helper's own, empty calendar
    client = helper_client(google, clock)
    assert await client.calendar_list() == [
        RemoteCalendar(FAMILY, "Family", "#9FE1E7", read_only=False),
        RemoteCalendar(SCHOOL, "Sample School", "#A47AE2", read_only=True),
        RemoteCalendar("ana@example.com", "Ana", "#9FE1E7", read_only=False),
    ]
    assert client.calendar_zones() == {
        FAMILY: NEW_YORK,
        SCHOOL: LOS_ANGELES,
        "ana@example.com": NEW_YORK,
    }
    # A signed-in account's own calendar is one of its calendars.
    signed_in = await account_client(google, clock).calendar_list()
    assert [calendar.remote_id for calendar in signed_in][-1] == HELPER


async def test_a_long_calendar_list_is_read_page_by_page(
    google: FakeGoogle, clock: FakeClock
) -> None:
    for number in range(260):
        google.add_calendar(f"team-{number}@example.com", f"Team {number}", role="reader")
    found = await helper_client(google, clock).calendar_list()
    assert len(found) == 261
    pages = [request for request in google.api_requests() if "calendarList" in str(request.url)]
    assert [request.url.params.get("pageToken") for request in pages] == [None, "250"]


async def test_a_calendar_shared_with_the_helper_is_added_by_its_address(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.add_calendar(SCHOOL, "Sample School", role="writer", listed=False)
    client = helper_client(google, clock)
    added = await client.insert_calendar(SCHOOL)
    assert added == RemoteCalendar(SCHOOL, "Sample School", "#9FE1E7", read_only=False)
    assert ("POST", "/users/me/calendarList") in google.asked()
    # Already in the list counts as done.
    assert await client.insert_calendar(SCHOOL) == added
    # Not shared (yet), or shared without the right: say so plainly.
    error = await failure(client.insert_calendar("nobody@example.com"))
    assert (error.kind, error.key) == (ErrorKind.NOT_FOUND, NOT_SHARED)
    google.fail.append(("POST", google_error(403, "forbidden", "Forbidden")))
    error = await failure(client.insert_calendar("private@example.com"))
    assert (error.kind, error.key) == (ErrorKind.NOT_FOUND, NOT_SHARED)
    # Slowing down is not "not shared".
    google.fail.append(("POST", google_error(403, "rateLimitExceeded", "Rate Limit Exceeded")))
    error = await failure(client.insert_calendar("private@example.com"))
    assert error.kind == ErrorKind.RATE_LIMITED


# ---- pulling ------------------------------------------------------------------------------------


async def test_a_full_listing(google: FakeGoogle, clock: FakeClock) -> None:
    family(google)
    google.page_size = 2  # five pages: every one is read
    google_provider = provider(google, clock)
    changes = await google_provider.changes(FAMILY_CALENDAR, None, {})
    assert changes.complete and changes.removed == []
    assert changes.cursor == google.sync_token()
    found = by_uid(changes.series)
    # The working-location marker and the deleted event aren't there.
    assert sorted(found) == [
        "call@example.com",
        "piano@example.com",
        "soccer@example.com",
        "trip@example.com",
    ]
    assert google_provider.refused == 0

    lesson = found["piano@example.com"]
    assert lesson.master == SyncedEvent(
        title="Piano lesson",
        timing=at("2026-10-07T16:00:00-04:00", "2026-10-07T17:00:00-04:00"),
        tzid=NEW_YORK,
    )
    assert (lesson.rrule, lesson.rdates, lesson.exdates) == ("FREQ=WEEKLY;BYDAY=WE", (), ())
    master = google.body(FAMILY, "piano01")
    assert (lesson.remote_id, lesson.etag) == ("piano01", master["etag"])
    assert (lesson.updated_at, lesson.sequence) == (clock.now(), None)
    assert lesson.overrides == (
        SyncedOverride(
            recurrence_id="2026-10-14T16:00:00",
            event=SyncedEvent(
                title="Piano lesson (Thursday)",
                timing=at("2026-10-15T17:00:00-04:00", "2026-10-15T18:00:00-04:00"),
                tzid=NEW_YORK,
            ),
            remote_id="piano01_20261014T200000Z",
            etag=google.body(FAMILY, "piano01_20261014T200000Z")["etag"],
        ),
        SyncedOverride(
            recurrence_id="2026-10-21T16:00:00",
            event=SyncedEvent(
                title=NO_TITLE,
                timing=at("2026-10-21T16:00:00-04:00", "2026-10-21T16:00:00-04:00"),
                tzid=NEW_YORK,
                cancelled=True,
            ),
            remote_id="piano01_20261021T200000Z",
            etag=google.body(FAMILY, "piano01_20261021T200000Z")["etag"],
        ),
    )

    trip = found["trip@example.com"]
    assert trip.master == SyncedEvent(
        title="School trip",
        timing=Timing(all_day=True, start_date=date(2026, 10, 9), end_date=date(2026, 10, 11)),
    )
    assert (trip.rrule, trip.overrides) == (None, ())

    call = found["call@example.com"]
    assert call.master == SyncedEvent(
        title="Call with Leo",
        timing=at("2026-10-08T09:00:00-07:00", "2026-10-08T09:30:00-07:00"),
        tzid=LOS_ANGELES,
        description="Bring the photos\nand Mia's drawing & card",  # Google's HTML, as text
        location="Kitchen",
    )

    # Soccer's rule runs in Los Angeles' time: its EXDATE and its moved Saturday are 9:00 there,
    # though the calendar is New York's and the original start came written in New York's time.
    soccer = found["soccer@example.com"]
    assert soccer.master is not None and soccer.master.tzid == LOS_ANGELES
    assert (soccer.rrule, soccer.exdates) == ("FREQ=WEEKLY;BYDAY=SA", ("2026-10-17T09:00:00",))
    assert [(o.recurrence_id, o.event.title) for o in soccer.overrides] == [
        ("2026-10-24T09:00:00", "Soccer (away)")
    ]

    # Every page asked for deleted events and unexpanded series, as many per page as allowed.
    listings = [r for r in google.api_requests() if r.url.path.endswith("/events")]
    assert len(listings) == 5
    for request in listings:
        params = request.url.params
        assert (params["showDeleted"], params["singleEvents"], params["maxResults"]) == (
            "true",
            "false",
            "2500",
        )
        assert "syncToken" not in params
    assert [r.url.params.get("pageToken") for r in listings] == [None, "2", "4", "6", "8"]
    # The calendar's address is escaped in the path ("#" and "@").
    assert b"/calendars/family%23shared%40example.com/events" in listings[0].url.raw_path
    assert {r.headers["authorization"] for r in listings} == {"Bearer test-access-1"}


async def test_what_is_pulled_expands_to_what_google_shows(
    google: FakeGoogle, clock: FakeClock
) -> None:
    """The recurrence ids line up with the core's own expansion: a moved occurrence replaces
    the one it came from, a cancelled one and an EXDATE are gone, and Los Angeles' Saturday
    9:00 stays 9:00 there."""
    family(google)
    found = by_uid((await provider(google, clock).changes(FAMILY_CALENDAR, None, {})).series)
    window = Window(
        utc("2026-10-05T00:00:00-04:00"),
        utc("2026-11-01T00:00:00-04:00"),
        date(2026, 10, 5),
        date(2026, 11, 1),
    )

    def shown(uid: str) -> list[tuple[str, bool]]:
        item = found[uid]
        assert item.master is not None and item.master.tzid is not None
        gone = {o.recurrence_id for o in item.overrides if o.event.cancelled}
        series = Series(
            timing=item.master.timing,
            tzid=item.master.tzid,
            rrule=item.rrule,
            rdates=item.rdates,
            exdates=frozenset({*item.exdates, *gone}),
        )
        moves = [Override(o.recurrence_id, o.event.timing) for o in item.overrides]
        zone = ZoneInfo(item.master.tzid)
        return [
            (o.timing.start_utc.astimezone(zone).isoformat(), o.is_override)
            for o in expand(series, moves, window)
            if o.timing.start_utc is not None
        ]

    assert shown("piano@example.com") == [
        ("2026-10-07T16:00:00-04:00", False),
        ("2026-10-15T17:00:00-04:00", True),
        ("2026-10-28T16:00:00-04:00", False),
    ]
    assert shown("soccer@example.com") == [
        ("2026-10-10T09:00:00-07:00", False),
        ("2026-10-24T13:00:00-07:00", True),
        ("2026-10-31T09:00:00-07:00", False),
    ]


async def test_an_occurrence_that_changed_on_its_own_is_a_partial_series(
    google: FakeGoogle, clock: FakeClock
) -> None:
    piano(google)
    google_provider = provider(google, clock)
    first = await google_provider.changes(FAMILY_CALENDAR, None, {})
    clock.advance(hours=1)
    google.put(
        FAMILY,
        moved(
            "piano01",
            "2026-10-28T16:00:00-04:00",
            "Piano lesson (recital)",
            "2026-10-28T18:00:00-04:00",
            "2026-10-28T19:30:00-04:00",
        ),
    )
    google.put(FAMILY, cancelled("piano01", "2026-11-04T16:00:00-05:00"))  # after the clocks change
    google.seen.clear()

    changes = await google_provider.changes(FAMILY_CALENDAR, first.cursor, {})
    assert not changes.complete and changes.removed == []
    assert changes.cursor == google.sync_token()
    master = google.body(FAMILY, "piano01")
    assert changes.series == [
        SyncedSeries(
            uid="piano@example.com",
            master=None,
            overrides=(
                SyncedOverride(
                    recurrence_id="2026-10-28T16:00:00",
                    event=SyncedEvent(
                        title="Piano lesson (recital)",
                        timing=at("2026-10-28T18:00:00-04:00", "2026-10-28T19:30:00-04:00"),
                        tzid=NEW_YORK,
                    ),
                    remote_id="piano01_20261028T200000Z",
                    etag=google.body(FAMILY, "piano01_20261028T200000Z")["etag"],
                ),
                SyncedOverride(
                    recurrence_id="2026-11-04T16:00:00",
                    event=SyncedEvent(
                        title=NO_TITLE,
                        timing=at("2026-11-04T16:00:00-05:00", "2026-11-04T16:00:00-05:00"),
                        tzid=NEW_YORK,
                        cancelled=True,
                    ),
                    remote_id="piano01_20261104T210000Z",
                    etag=google.body(FAMILY, "piano01_20261104T210000Z")["etag"],
                ),
            ),
            remote_id="piano01",  # the stored series keeps its master's id and etag
            etag=master["etag"],
            updated_at=clock.now(),
        )
    ]
    # The listing from the token, then one look at the master (for its iCalUID and zone).
    assert google.asked() == [
        ("GET", f"/calendars/{FAMILY}/events"),
        ("GET", f"/calendars/{FAMILY}/events/piano01"),
    ]
    assert google.api_requests()[0].url.params["syncToken"] == first.cursor


async def test_a_series_that_changed_comes_whole(google: FakeGoogle, clock: FakeClock) -> None:
    piano(google)
    google_provider = provider(google, clock)
    first = await google_provider.changes(FAMILY_CALENDAR, None, {})
    google.put(FAMILY, {**google.body(FAMILY, "piano01"), "summary": "Piano"})
    google.seen.clear()

    changes = await google_provider.changes(FAMILY_CALENDAR, first.cursor, {})
    (lesson,) = changes.series
    assert lesson.master is not None and lesson.master.title == "Piano"
    # Stored, a series is replaced whole: the exceptions that didn't change come along.
    assert [(o.recurrence_id, o.event.cancelled) for o in lesson.overrides] == [
        ("2026-10-14T16:00:00", False),
        ("2026-10-21T16:00:00", True),
    ]
    listing_by_uid = google.api_requests()[1]
    assert listing_by_uid.url.params["iCalUID"] == "piano@example.com"
    assert listing_by_uid.url.params["showDeleted"] == "true"
    assert "syncToken" not in listing_by_uid.url.params


async def test_a_deleted_series_is_removed(google: FakeGoogle, clock: FakeClock) -> None:
    piano(google)
    google_provider = provider(google, clock)
    first = await google_provider.changes(FAMILY_CALENDAR, None, {})
    google.cancel(FAMILY, "piano01")
    google.cancel(FAMILY, "piano01_20261014T200000Z")
    changes = await google_provider.changes(FAMILY_CALENDAR, first.cursor, {})
    assert (changes.series, changes.removed, changes.complete) == ([], ["piano01"], False)

    # Read again from the start, a deleted series is simply not there.
    again = await google_provider.changes(FAMILY_CALENDAR, None, {})
    assert (again.series, again.removed, again.complete) == ([], [], True)


async def test_a_forgotten_sync_token_reads_everything_again(
    google: FakeGoogle, clock: FakeClock
) -> None:
    family(google)
    google_provider = provider(google, clock)
    first = await google_provider.changes(FAMILY_CALENDAR, None, {})
    assert first.cursor is not None
    google.forgotten.add(first.cursor)
    changes = await google_provider.changes(FAMILY_CALENDAR, first.cursor, {})
    assert changes.complete and changes.cursor == google.sync_token()
    assert sorted(by_uid(changes.series)) == sorted(by_uid(first.series))
    # A token Google can't read at all is treated the same.
    with pytest.raises(SyncTokenExpired):
        await helper_client(google, clock).events(FAMILY, "garbled")


async def test_occurrences_of_a_series_from_another_calendar_stand_alone(
    google: FakeGoogle, clock: FakeClock
) -> None:
    """An invitation to one occurrence of someone else's series: its master isn't here."""
    google.put(
        FAMILY,
        moved(
            "work01",
            "2026-10-13T10:00:00-04:00",
            "Sample planning day",
            "2026-10-13T10:00:00-04:00",
            "2026-10-13T12:00:00-04:00",
        ),
        uid="work@example.com",
    )
    google_provider = provider(google, clock)
    changes = await google_provider.changes(FAMILY_CALENDAR, None, {})
    (alone,) = changes.series
    assert (alone.uid, alone.remote_id, alone.rrule) == (
        "work01_20261013T140000Z",
        "work01_20261013T140000Z",
        None,
    )
    assert alone.master is not None and alone.master.title == "Sample planning day"
    google.cancel(FAMILY, "work01_20261013T140000Z")
    later = await google_provider.changes(FAMILY_CALENDAR, changes.cursor, {})
    assert (later.series, later.removed) == ([], ["work01_20261013T140000Z"])


async def test_a_repeat_sunroom_cannot_show_is_counted(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.put(
        FAMILY,
        timed(
            "meds01",
            "Medicine",
            "2026-10-07T08:00:00-04:00",
            "2026-10-07T08:05:00-04:00",
            recurrence=["RRULE:FREQ=HOURLY;INTERVAL=8"],
        ),
    )
    piano(google)
    google_provider = provider(google, clock)
    changes = await google_provider.changes(FAMILY_CALENDAR, None, {})
    assert [item.uid for item in changes.series] == ["piano@example.com"]
    assert google_provider.refused == 1


# ---- pushing ------------------------------------------------------------------------------------


async def test_a_new_series_is_created_with_its_rule_and_changed_occurrences(
    google: FakeGoogle, clock: FakeClock
) -> None:
    master = SyncedEvent(
        title="Swim club",
        timing=at("2026-10-13T08:00:00-04:00", "2026-10-13T09:00:00-04:00"),
        tzid=NEW_YORK,
    )
    series = SyncedSeries(
        uid="swim-club@sunroom",
        master=master,
        rrule="FREQ=WEEKLY;BYDAY=TU",
        exdates=("2026-10-20T08:00:00",),
        overrides=(
            SyncedOverride(
                recurrence_id="2026-10-27T08:00:00",
                event=replace(master, cancelled=True),
            ),
            SyncedOverride(  # after the clocks go back: 8:00 is 13:00 UTC now
                recurrence_id="2026-11-03T08:00:00",
                event=replace(
                    master,
                    title="Swim club (gala)",
                    timing=at("2026-11-03T10:00:00-05:00", "2026-11-03T12:00:00-05:00"),
                ),
            ),
        ),
    )
    pushed = await provider(google, clock).push(FAMILY_CALENDAR, pending(series))
    created = google.body(FAMILY, "new0001")
    assert (pushed.uid, pushed.remote_id, pushed.etag) == ("swim-club@sunroom", "new0001", '"1"')

    method, event_id, body = google.sent[0]
    assert (method, event_id) == ("POST", "new0001")
    assert body == {
        "summary": "Swim club",
        "description": "",
        "location": "",
        "start": {"dateTime": "2026-10-13T08:00:00-04:00", "timeZone": NEW_YORK},
        "end": {"dateTime": "2026-10-13T09:00:00-04:00", "timeZone": NEW_YORK},
        "iCalUID": "swim-club@sunroom",
        # The cancelled occurrence went out as an EXDATE, not as a call of its own.
        "recurrence": [
            "RRULE:FREQ=WEEKLY;BYDAY=TU",
            "EXDATE;TZID=America/New_York:20261020T080000,20261027T080000",
        ],
    }
    # The changed occurrence went to its instance id: the original start, in UTC.
    assert [(m, i) for m, i, _ in google.sent[1:]] == [("PUT", "new0001_20261103T130000Z")]
    occurrence = google.body(FAMILY, "new0001_20261103T130000Z")
    assert occurrence["recurringEventId"] == "new0001"
    assert occurrence["summary"] == "Swim club (gala)"
    assert occurrence["start"] == {"dateTime": "2026-11-03T10:00:00-05:00", "timeZone": NEW_YORK}
    assert pushed.etag == created["etag"]  # the master's own etag


async def test_a_change_replaces_googles_copy_if_it_is_still_the_one_seen(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.put(
        FAMILY,
        timed(
            "dentist01",
            "Dentist",
            "2026-10-08T14:30:00-04:00",
            "2026-10-08T15:30:00-04:00",
            description="Room 4<br>Bring the <b>form</b>",
            attendees=[{"email": "ana@example.com", "responseStatus": "accepted"}],
            reminders={"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
            colorId="5",
            conferenceData={"conferenceId": "sample-meet"},
        ),
        uid="dentist@example.com",
    )
    google_provider = provider(google, clock)
    pulled = by_uid((await google_provider.changes(FAMILY_CALENDAR, None, {})).series)
    seen = pulled["dentist@example.com"]
    dentist = seen.master
    assert dentist is not None and dentist.description == "Room 4\nBring the form"
    dentist = replace(
        dentist,
        title="Dentist (Mia)",
        timing=at("2026-10-08T15:00:00-04:00", "2026-10-08T16:00:00-04:00"),
    )
    changed = replace(seen, master=dentist)
    google.seen.clear()
    pushed = await google_provider.push(FAMILY_CALENDAR, pending(changed))
    assert google.asked() == [
        ("GET", f"/calendars/{FAMILY}/events/dentist01"),
        ("PUT", f"/calendars/{FAMILY}/events/dentist01"),
    ]
    put = google.api_requests()[1]
    assert put.headers["if-match"] == seen.etag
    stored = google.body(FAMILY, "dentist01")
    assert (pushed.remote_id, pushed.etag) == ("dentist01", stored["etag"])
    assert stored["summary"] == "Dentist (Mia)"
    assert stored["start"] == {"dateTime": "2026-10-08T15:00:00-04:00", "timeZone": NEW_YORK}
    # What Sunroom doesn't keep stays, and the notes it didn't change keep Google's own HTML.
    assert stored["attendees"] == [{"email": "ana@example.com", "responseStatus": "accepted"}]
    assert stored["reminders"]["overrides"] == [{"method": "popup", "minutes": 30}]
    assert (stored["colorId"], stored["conferenceData"]) == ("5", {"conferenceId": "sample-meet"})
    assert stored["description"] == "Room 4<br>Bring the <b>form</b>"
    assert "recurrence" not in stored

    # Notes changed here replace Google's.
    rewritten = replace(changed, etag=pushed.etag, master=replace(dentist, description="Room 5"))
    await google_provider.push(FAMILY_CALENDAR, pending(rewritten))
    assert google.body(FAMILY, "dentist01")["description"] == "Room 5"

    # The etag Sunroom holds is old: someone changed it on Google meanwhile. Nothing is sent.
    google.seen.clear()
    error = await failure(google_provider.push(FAMILY_CALENDAR, pending(changed)))
    assert (error.kind, error.key) == (ErrorKind.CONFLICT, CHANGED)
    assert [method for method, _ in google.asked()] == ["GET"]


async def test_a_412_is_a_conflict(google: FakeGoogle, clock: FakeClock) -> None:
    google.put(
        FAMILY,
        timed("vet01", "Vet", "2026-10-09T09:00:00-04:00", "2026-10-09T10:00:00-04:00"),
        uid="vet@example.com",
    )
    google_provider = provider(google, clock)
    (seen,) = (await google_provider.changes(FAMILY_CALENDAR, None, {})).series
    google.fail.append(("PUT", google_error(412, "conditionNotMet", "Precondition Failed")))
    error = await failure(google_provider.push(FAMILY_CALENDAR, pending(seen)))
    assert (error.kind, error.key) == (ErrorKind.CONFLICT, CHANGED)
    # Deleted on Google meanwhile: also pull first, then decide.
    google.cancel(FAMILY, "vet01")
    error = await failure(google_provider.push(FAMILY_CALENDAR, pending(seen)))
    assert error.kind == ErrorKind.CONFLICT


async def test_changed_occurrences_go_to_their_instance_ids(
    google: FakeGoogle, clock: FakeClock
) -> None:
    piano(google)
    google.put(
        FAMILY,
        {
            "id": "bins01",
            "summary": "Bins out",
            "start": {"date": "2026-10-09"},
            "end": {"date": "2026-10-10"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=FR"],
        },
        uid="bins@example.com",
    )
    google_provider = provider(google, clock)
    found = by_uid((await google_provider.changes(FAMILY_CALENDAR, None, {})).series)

    lesson = found["piano@example.com"]
    assert lesson.master is not None
    later = SyncedOverride(
        recurrence_id="2026-10-28T16:00:00",
        event=replace(
            lesson.master,
            title="Piano lesson (Mia's recital)",
            timing=at("2026-10-28T18:00:00-04:00", "2026-10-28T19:00:00-04:00"),
        ),
    )
    google.sent.clear()
    await google_provider.push(
        FAMILY_CALENDAR, pending(replace(lesson, overrides=(*lesson.overrides, later)))
    )
    assert [(method, event_id) for method, event_id, _ in google.sent] == [
        ("PUT", "piano01"),
        ("PUT", "piano01_20261014T200000Z"),  # the one moved before, sent as it is here
        ("PUT", "piano01_20261028T200000Z"),  # the new one
    ]
    _, _, master_body = google.sent[0]
    assert master_body["recurrence"] == [
        "RRULE:FREQ=WEEKLY;BYDAY=WE",
        "EXDATE;TZID=America/New_York:20261021T160000",
    ]
    recital = google.body(FAMILY, "piano01_20261028T200000Z")
    assert (recital["summary"], recital["recurringEventId"]) == (
        "Piano lesson (Mia's recital)",
        "piano01",
    )
    assert "recurrence" not in recital

    # An all-day series' occurrence is named by its date.
    bins = found["bins@example.com"]
    assert bins.master is not None
    holiday = SyncedOverride(
        recurrence_id="2026-10-16",
        event=replace(
            bins.master,
            timing=Timing(all_day=True, start_date=date(2026, 10, 17), end_date=date(2026, 10, 18)),
        ),
    )
    google.sent.clear()
    await google_provider.push(FAMILY_CALENDAR, pending(replace(bins, overrides=(holiday,))))
    assert [(method, event_id) for method, event_id, _ in google.sent] == [
        ("PUT", "bins01"),
        ("PUT", "bins01_20261016"),
    ]
    assert google.body(FAMILY, "bins01_20261016")["start"] == {"date": "2026-10-17"}


async def test_an_event_put_back_here_is_restored_on_google(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.put(
        FAMILY,
        timed(
            "lunch01", "Lunch with Sam", "2026-10-10T12:00:00-04:00", "2026-10-10T13:00:00-04:00"
        ),
        uid="lunch@example.com",
    )
    google.cancel(FAMILY, "lunch01")
    series = SyncedSeries(
        uid="lunch@example.com",
        master=SyncedEvent(
            title="Lunch with Sam",
            timing=at("2026-10-10T12:00:00-04:00", "2026-10-10T13:00:00-04:00"),
            tzid=NEW_YORK,
        ),
    )
    pushed = await provider(google, clock).push(FAMILY_CALENDAR, pending(series))
    assert pushed.remote_id == "lunch01"
    restored = google.body(FAMILY, "lunch01")
    assert (restored["status"], restored["summary"]) == ("confirmed", "Lunch with Sam")

    # A live event with that iCalUID is one Sunroom hasn't pulled yet: pull, then push.
    error = await failure(provider(google, clock).push(FAMILY_CALENDAR, pending(series)))
    assert error.kind == ErrorKind.CONFLICT


async def test_delete(google: FakeGoogle, clock: FakeClock) -> None:
    piano(google)
    google_provider = provider(google, clock)
    (lesson,) = (await google_provider.changes(FAMILY_CALENDAR, None, {})).series
    stale = replace(lesson, etag='"0"')
    error = await failure(google_provider.delete(FAMILY_CALENDAR, pending(stale, deleted=True)))
    assert (error.kind, error.key) == (ErrorKind.CONFLICT, CHANGED)

    google.seen.clear()
    await google_provider.delete(FAMILY_CALENDAR, pending(lesson, deleted=True))
    assert google.asked() == [("DELETE", f"/calendars/{FAMILY}/events/piano01")]
    assert google.api_requests()[0].headers["if-match"] == lesson.etag
    assert google.body(FAMILY, "piano01")["status"] == "cancelled"
    # Already gone counts as done (410 here, 404 for one Google never had).
    await google_provider.delete(FAMILY_CALENDAR, pending(lesson, deleted=True))
    never = replace(lesson, remote_id="nothing01")
    await google_provider.delete(FAMILY_CALENDAR, pending(never, deleted=True))
    # Never reached Google: nothing to send.
    google.seen.clear()
    local = replace(lesson, remote_id=None, etag=None)
    await google_provider.delete(FAMILY_CALENDAR, pending(local, deleted=True))
    assert google.seen == []


# ---- errors -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "kind", "message", "retry_after"),
    [
        (google_error(403, "rateLimitExceeded"), ErrorKind.RATE_LIMITED, SLOW_DOWN, None),
        (google_error(403, "userRateLimitExceeded"), ErrorKind.RATE_LIMITED, SLOW_DOWN, None),
        (
            google_error(429, "rateLimitExceeded", headers={"Retry-After": "30"}),
            ErrorKind.RATE_LIMITED,
            SLOW_DOWN,
            30.0,
        ),
        (
            httpx.Response(
                429,
                headers={
                    "Retry-After": "Wed, 07 Oct 2026 14:02:00 GMT",
                    "Date": "Wed, 07 Oct 2026 14:00:00 GMT",
                },
            ),
            ErrorKind.RATE_LIMITED,
            SLOW_DOWN,
            120.0,
        ),
        (google_error(403, "accessNotConfigured"), ErrorKind.REFUSED, API_OFF, None),
        (google_error(403, "forbidden"), ErrorKind.REFUSED, CANT_SEE, None),
        (google_error(404, "notFound"), ErrorKind.NOT_FOUND, CALENDAR_GONE, None),
        (google_error(500, "backendError"), ErrorKind.UNREACHABLE, NO_ANSWER, None),
        (
            google_error(503, "backendError", headers={"Retry-After": "5"}),
            ErrorKind.UNREACHABLE,
            NO_ANSWER,
            5.0,
        ),
        (httpx.Response(200, text="<html>a portal</html>"), ErrorKind.BAD_DATA, UNREADABLE, None),
        (
            httpx.Response(302, headers={"Location": "https://elsewhere.example.com/"}),
            ErrorKind.BAD_DATA,
            UNREADABLE,
            None,
        ),
    ],
)
async def test_failures_reading_map_to_plain_kinds(
    google: FakeGoogle,
    clock: FakeClock,
    reply: httpx.Response,
    kind: ErrorKind,
    message: str,
    retry_after: float | None,
) -> None:
    google.fail.append(("GET", reply))
    error = await failure(helper_client(google, clock).events(FAMILY, None))
    assert (error.kind, error.key, error.retry_after) == (kind, message, retry_after)
    # Redirects are never followed: a bearer token goes to Google's host only.
    assert {request.headers["host"] for request in google.seen} <= {TOKEN_HOST, API_HOST}


@pytest.mark.parametrize(
    ("reply", "kind", "message"),
    [
        (google_error(403, "forbidden"), ErrorKind.REFUSED, HELPER_REFUSED),
        (google_error(403, "forbiddenForNonOrganizer"), ErrorKind.REFUSED, HELPER_REFUSED),
        (google_error(400, "invalid", "Invalid value"), ErrorKind.REFUSED, REJECTED),
        (google_error(404, "notFound"), ErrorKind.NOT_FOUND, EVENT_GONE),
        (google_error(412, "conditionNotMet"), ErrorKind.CONFLICT, CHANGED),
    ],
)
async def test_failures_writing_map_to_plain_kinds(
    google: FakeGoogle, clock: FakeClock, reply: httpx.Response, kind: ErrorKind, message: str
) -> None:
    google.fail.append(("PUT", reply))
    client = helper_client(google, clock)
    error = await failure(client.update_event(FAMILY, "dentist01", {"summary": "Dentist"}, '"1"'))
    assert (error.kind, error.key) == (kind, message)


async def test_a_signed_in_account_is_told_whose_permission_to_ask(
    google: FakeGoogle, clock: FakeClock
) -> None:
    google.fail.append(("POST", google_error(403, "forbidden")))
    error = await failure(account_client(google, clock).insert_event(FAMILY, {"summary": "Tea"}))
    assert (error.kind, error.key) == (ErrorKind.REFUSED, ACCOUNT_REFUSED)


async def test_a_401_gets_one_fresh_token_then_asks_to_reconnect(
    google: FakeGoogle, clock: FakeClock
) -> None:
    client = helper_client(google, clock)
    google.fail.append(("GET", google_error(401, "authError", "Invalid Credentials")))
    page = await client.events(FAMILY, None)  # refreshed once, then it worked
    assert page.items == [] and google.issued == ["test-access-1", "test-access-2"]
    used = [r.headers["authorization"] for r in google.api_requests()]
    assert used == ["Bearer test-access-1", "Bearer test-access-2"]

    google.revoked = True  # Google takes no token any more, however fresh
    error = await failure(client.events(FAMILY, None))
    assert (error.kind, error.key) == (ErrorKind.AUTH, KEY_REFUSED)
    assert len(google.issued) == 3  # one more try, not a loop

    google.revoked = False
    signed_in = account_client(google, clock)
    google.fail.extend([("GET", google_error(401, "authError"))] * 2)
    error = await failure(signed_in.events(FAMILY, None))
    assert (error.kind, error.key) == (ErrorKind.AUTH, SIGNED_OUT)


async def test_an_unreachable_google_says_so(google: FakeGoogle, clock: FakeClock) -> None:
    client = helper_client(google, clock)
    await client.calendar_list()  # a token first, so only the API is down
    google.down = True
    error = await failure(client.events(FAMILY, None))
    assert (error.kind, error.key) == (ErrorKind.UNREACHABLE, NO_ANSWER)
    error = await failure(provider(google, clock).changes(FAMILY_CALENDAR, None, {}))
    assert (error.kind, error.key) == (ErrorKind.UNREACHABLE, NO_ANSWER)


async def test_no_token_or_key_reaches_an_error_or_a_log(
    google: FakeGoogle,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    family(google)
    google_provider = provider(google, clock)
    client = helper_client(google, clock)
    signed_in = account_client(google, clock)
    errors: list[Exception] = []

    async def attempt(call: Awaitable[object]) -> None:
        try:
            await call
        except SyncError as error:
            errors.append(error)

    first = await google_provider.changes(FAMILY_CALENDAR, None, {})
    assert first.cursor is not None
    google.forgotten.add(first.cursor)
    await google_provider.changes(FAMILY_CALENDAR, first.cursor, {})  # logs the full resync
    google.fail.append(("GET", google_error(401, "authError")))
    await client.events(FAMILY, None)
    google.fail.extend([("GET", google_error(401, "authError"))] * 2)
    await attempt(client.events(FAMILY, None))
    google.fail.append(("PUT", google_error(403, "forbidden")))
    await attempt(client.update_event(FAMILY, "piano01", {"summary": "Piano"}, None))
    await attempt(client.update_event(FAMILY, "piano01", {"summary": "Piano"}, '"stale"'))
    google.fail.append(("GET", google_error(429, "rateLimitExceeded")))
    await attempt(client.calendar_list())
    google.token_fail.append(oauth_error("invalid_grant", "Invalid JWT Signature."))
    await attempt(ServiceAccountAuth(key_file(), google.http(), clock.now).access_token())
    await attempt(signed_in.calendar_list())
    google.refresh_tokens.clear()
    await attempt(
        OAuthAuth(CLIENT_ID, CLIENT_SECRET, REFRESH, google.http(), clock.now).access_token()
    )
    await attempt(
        exchange_code(google.http(), CLIENT_ID, CLIENT_SECRET, "used", "v" * 43, REDIRECT)
    )
    google.down = True
    await attempt(client.events(FAMILY, None))
    assert len(errors) == 8

    captured = capsys.readouterr()
    logged = caplog.text + captured.out + captured.err
    logged += "".join(repr(record.__dict__) for record in caplog.records)
    assert "google.sync_token_expired" in logged  # the capture sees the module's own log
    said = [part for error in errors for part in (str(error), repr(error), repr(error.args))]
    said += [repr(client), repr(google_provider), repr(signed_in)]
    said += [repr(ServiceAccountAuth(key_file(), google.http(), clock.now))]
    assertions = [grant["assertion"] for grant in google.grants if "assertion" in grant]
    key_lines = [line for line in pem().splitlines() if "PRIVATE" not in line]
    secrets = [*google.issued, REFRESH, CLIENT_SECRET, *assertions, *key_lines[:3], pem()]
    assert assertions and google.issued
    for secret in secrets:
        assert secret not in logged
        assert not [text for text in said if secret in text]
    assert not [text for text in said if FAMILY in text or "family%23" in text]
