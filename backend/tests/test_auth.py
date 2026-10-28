"""Sessions, devices, the parent PIN and who counts as a parent (PLAN §12)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request, Response

from sunroom.app import create_app
from sunroom.auth.deps import Actor, current_actor
from sunroom.auth.password import device_form, device_label, hash_password, verify_password
from sunroom.core.clock import FakeClock
from tests.support import (
    BASE_URL,
    CSRF,
    PASSWORD,
    PIN,
    add_member,
    login,
    make_settings,
    run_setup,
    set_pin,
    state_of,
)


async def test_login_sets_a_400_day_http_only_cookie(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    response = await login(other)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("sunroom=v1.")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=34560000" in cookie
    assert "Secure" not in cookie  # plain HTTP on the LAN
    body = response.json()
    assert body["member"] is None
    assert body["household_name"] == "Sample Family"
    assert body["is_parent"] is True


async def test_https_uses_a_secure_host_cookie(data_dir: Path) -> None:
    """A proxy on the home network (the test transport's 127.0.0.1) is believed (ADR 0034)."""
    app = create_app(make_settings(data_dir))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://calendar.home.arpa",
            headers={"x-forwarded-proto": "https"},
        ) as client:
            response = await run_setup(client)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-sunroom=")
    assert "Secure" in cookie
    assert "Path=/" in cookie


async def test_wrong_password_says_exactly_what_happened(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    response = await login(other, "not the password")
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "wrong_password",
        "message": "That password didn't match. Try again.",
    }


async def test_five_failures_lock_out_that_address(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, clock: FakeClock
) -> None:
    for _ in range(5):
        assert (await login(other, "wrong")).status_code == 401
    blocked = await login(other)  # even the right password waits
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.json()["error"]["message"] == "Too many tries. Wait 15 minutes."
    clock.advance(minutes=16)
    assert (await login(other)).status_code == 200


async def test_protected_routes_need_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/session")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"


async def test_mutations_need_the_csrf_header_and_a_matching_origin(
    parent: httpx.AsyncClient,
) -> None:
    body = {"name": "Mia", "role": "kid"}
    assert (await parent.post("/api/members", json=body)).status_code == 403
    for origin in ("https://evil.example", "null", "https://localhost:8080"):
        response = await parent.post("/api/members", json=body, headers=CSRF | {"origin": origin})
        assert response.status_code == 403, origin
    cross_site = await parent.post(
        "/api/members", json=body, headers=CSRF | {"sec-fetch-site": "cross-site"}
    )
    assert cross_site.status_code == 403
    ok = await parent.post(
        "/api/members", json=body, headers=CSRF | {"origin": "http://localhost:8080"}
    )
    assert ok.status_code == 201


async def test_https_the_proxy_didnt_mention_gets_a_useful_message(
    app: FastAPI, parent: httpx.AsyncClient
) -> None:
    """The browser is on https but the request says http: a proxy at home that sent no
    X-Forwarded-Proto, or one out on the internet whose headers aren't believed (ADR 0034)."""
    at_home = await parent.post(
        "/api/members",
        json={"name": "Mia"},
        headers=CSRF | {"origin": "https://localhost:8080"},
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 4000))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as outside:
        far = await outside.post(
            "/api/members",
            json={"name": "Mia"},
            headers=CSRF | {"origin": "https://localhost:8080", "x-forwarded-proto": "https"},
        )
    for response in (at_home, far):
        error = response.json()["error"]
        assert error["code"] == "https_not_forwarded"
        assert "X-Forwarded-Proto" in error["message"]


async def test_choosing_who_is_using_this_phone(parent: httpx.AsyncClient) -> None:
    mia = await add_member(parent, "Mia", "kid")
    chosen = await parent.put("/api/auth/member", json={"member_id": mia["id"]}, headers=CSRF)
    assert chosen.json()["member"]["name"] == "Mia"
    session = (await parent.get("/api/auth/session")).json()
    assert session["member"]["id"] == mia["id"]
    cleared = await parent.put("/api/auth/member", json={"member_id": None}, headers=CSRF)
    assert cleared.json()["member"] is None
    unknown = await parent.put("/api/auth/member", json={"member_id": "nope"}, headers=CSRF)
    assert unknown.status_code == 404


async def test_sign_out_other_phones_keeps_screens_unless_asked(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await login(other)
    screen = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert screen.status_code == 200
    devices = (await parent.get("/api/auth/devices")).json()
    assert {d["kind"] for d in devices} == {"phone", "kiosk"}
    assert sum(d["is_current"] for d in devices) == 1
    assert (
        await parent.post("/api/auth/devices/sign-out-others", json={}, headers=CSRF)
    ).status_code == 204
    assert (await other.get("/api/auth/session")).status_code == 200  # the screen stayed
    await parent.post(
        "/api/auth/devices/sign-out-others", json={"include_kiosks": True}, headers=CSRF
    )
    assert (await other.get("/api/auth/session")).status_code == 401
    assert (await parent.get("/api/auth/session")).status_code == 200


async def test_logout_revokes_this_device(parent: httpx.AsyncClient) -> None:
    old_cookie = parent.cookies.get("sunroom")
    assert (await parent.post("/api/auth/logout", headers=CSRF)).status_code == 204
    parent.cookies.set("sunroom", old_cookie or "")
    assert (await parent.get("/api/auth/session")).status_code == 401


async def test_cookie_is_renewed_after_30_days(parent: httpx.AsyncClient, clock: FakeClock) -> None:
    clock.advance(days=31)
    response = await parent.get("/api/auth/session")
    assert response.status_code == 200
    assert "sunroom=v1." in response.headers.get("set-cookie", "")


async def test_epoch_change_signs_everyone_out(app: FastAPI, parent: httpx.AsyncClient) -> None:
    state_of(app).auth.epoch += 1
    assert (await parent.get("/api/auth/session")).status_code == 401


async def test_tampered_cookie_is_rejected(parent: httpx.AsyncClient) -> None:
    value = parent.cookies.get("sunroom") or ""
    parent.cookies.set("sunroom", value[:-2] + "xx")
    assert (await parent.get("/api/auth/session")).status_code == 401


def test_device_labels() -> None:
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Safari/604.1"
    android = "Mozilla/5.0 (Linux; Android 15; Pixel 8) Chrome/130.0 Mobile Safari/537.36"
    assert device_label(iphone) == "iPhone, Safari"
    assert device_label(android) == "Android phone, Chrome"
    assert device_label(None) == "Device"


def test_device_forms() -> None:
    """Settings → Devices draws each by what it is (ADR 0032): a paired screen, else the word
    device_label wrote at sign-in. A computer was listed as a phone before."""
    for label, form in [
        ("iPhone, Safari", "phone"),
        ("Android phone, Chrome", "phone"),
        ("iPad, Safari", "tablet"),
        ("Android tablet, Chrome", "tablet"),
        ("Chromebook, Chrome", "computer"),
        ("Mac, Safari", "computer"),
        ("Windows PC, Edge", "computer"),
        ("Linux computer, Firefox", "computer"),
        ("Device", "phone"),
    ]:
        assert device_form("phone", label) == form, label
    assert device_form("kiosk", "Wall screen") == "screen"
    assert device_form("kiosk", "Mac, Chrome") == "screen"


def test_password_hashes_verify_and_carry_their_parameters() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$32768$8$1$")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batter", stored)
    assert not verify_password("anything", "garbage")


# ---- kids' phones and the parent PIN -------------------------------------------------------


async def test_a_kids_phone_needs_a_pin_to_exist_first(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    kid_phone = (await login(other)).json()["device_id"]
    refused = await parent.patch(
        f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "pin_needed"
    await set_pin(parent)
    marked = await parent.patch(
        f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF
    )
    assert marked.json()["is_kid_device"] is True
    # The kid's phone sees everything but can't change settings.
    assert (await other.get("/api/settings")).status_code == 200
    blocked = await other.patch("/api/settings", json={"theme": "dark"}, headers=CSRF)
    assert blocked.status_code == 403
    assert blocked.json()["error"] == {
        "code": "parent_required",
        "message": "Only a parent can do that. Enter the parent PIN.",
        "pin": True,
    }


async def test_a_pin_grant_unlocks_parent_things_for_ten_minutes(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, clock: FakeClock
) -> None:
    await set_pin(parent)
    screen = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert screen.json()["is_parent"] is False  # a PIN exists: the screen asks for it
    assert (
        await other.patch("/api/settings", json={"theme": "dark"}, headers=CSRF)
    ).status_code == 403
    wrong = await other.post("/api/auth/pin/verify", json={"pin": "0000"}, headers=CSRF)
    assert wrong.status_code == 403
    assert wrong.json()["error"]["message"] == "That PIN didn't match. Try again."
    granted = await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    assert granted.status_code == 200
    cookie = granted.headers["set-cookie"]
    assert cookie.startswith("sunroom_parent=v1.") and "Max-Age=600" in cookie
    assert (
        await other.patch("/api/settings", json={"theme": "dark"}, headers=CSRF)
    ).status_code == 200
    assert (await other.get("/api/auth/session")).json()["is_parent"] is True
    clock.advance(minutes=11)  # the grant doesn't slide
    assert (
        await other.patch("/api/settings", json={"theme": "light"}, headers=CSRF)
    ).status_code == 403


async def test_lock_ends_the_grant_and_a_new_pin_ends_every_grant(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await set_pin(parent)
    await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    await other.post("/api/auth/pin/lock", headers=CSRF)
    assert (await other.get("/api/auth/session")).json()["is_parent"] is False
    await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    await set_pin(parent, "13579")  # a parent's phone changes it without the old one
    assert (await other.get("/api/auth/session")).json()["is_parent"] is False


async def test_changing_the_pin_on_the_screen_asks_for_the_old_one(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await set_pin(parent)
    await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    without = await other.put("/api/auth/pin", json={"pin": "1111"}, headers=CSRF)
    assert without.status_code == 403
    with_old = await other.put(
        "/api/auth/pin", json={"pin": "1111", "current_pin": PIN}, headers=CSRF
    )
    assert with_old.status_code == 204


async def test_pin_tries_are_limited_per_device(
    parent: httpx.AsyncClient, other: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await set_pin(parent)
    await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("sunroom.auth.router.asyncio.sleep", no_wait)
    for _ in range(5):
        await other.post("/api/auth/pin/verify", json={"pin": "9999"}, headers=CSRF)
    blocked = await other.post("/api/auth/pin/verify", json={"pin": PIN}, headers=CSRF)
    assert blocked.status_code == 429


async def test_without_a_pin_the_screen_is_a_parent(
    parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    screen = await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    assert screen.json()["is_parent"] is True
    assert (
        await other.patch("/api/settings", json={"theme": "dark"}, headers=CSRF)
    ).status_code == 200


async def test_a_screen_has_no_member_but_says_who_tapped(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    mia = await add_member(parent, "Mia", "kid")
    await other.post(
        "/api/auth/kiosk/pair-with-password", json={"password": PASSWORD}, headers=CSRF
    )
    refused = await other.put("/api/auth/member", json={"member_id": mia["id"]}, headers=CSRF)
    assert refused.status_code == 409
    state = state_of(app)

    async def actor_for(client: httpx.AsyncClient, tapped: str) -> Actor:
        cookie = client.cookies.get("sunroom") or ""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "query_string": b"",
                "headers": [
                    (b"cookie", f"sunroom={cookie}".encode()),
                    (b"x-sunroom-member", tapped.encode()),
                ],
            }
        )
        return await current_actor(request, Response(), state)

    # The header counts on the wall screen only, and only for someone in the household.
    assert (await actor_for(other, mia["id"])).member_id == mia["id"]
    assert (await actor_for(other, "someone-else")).member_id is None
    assert (await actor_for(parent, mia["id"])).member_id is None  # a phone ignores it


# ---- the household password, checked for This Screen's Uninstall (ADR 0042) ----------------


async def test_a_parent_checks_the_household_password(
    app: FastAPI, parent: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    check = "/api/admin/password/check"
    assert (await parent.post(check, json={"password": PASSWORD}, headers=CSRF)).status_code == 204
    wrong = await parent.post(check, json={"password": "not-the-password"}, headers=CSRF)
    assert wrong.status_code == 403
    assert wrong.json()["error"] == {
        "code": "wrong_password",
        "message": "That password didn't match. Try again.",
    }
    limiter = state_of(app).login_limiter
    assert sum(limiter.recent_failures(key) for key in ("127.0.0.1", "unknown")) == 1
    # Nobody signed in may ask; a kid's phone is refused as for any parent's action.
    assert (await other.post(check, json={"password": PASSWORD}, headers=CSRF)).status_code == 401
    kid_phone = (await login(other)).json()["device_id"]
    await set_pin(parent)
    await parent.patch(f"/api/auth/devices/{kid_phone}", json={"is_kid_device": True}, headers=CSRF)
    refused = await other.post(check, json={"password": PASSWORD}, headers=CSRF)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "parent_required"
