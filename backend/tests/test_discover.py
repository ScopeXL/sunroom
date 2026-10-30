"""``GET /api/discover`` (ADR 0035, docs/M7.md T1): what a Sunroom screen reads to find this
server. Its shape; the household's name only to a local address; an id that lasts through a
restart and travels with a restore, and that boot fills in when a row lacks one. Synthetic
data only."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sunroom.app import create_app
from sunroom.boot import reconcile_app_meta
from sunroom.core.version import build_info
from tests.support import BASE_URL, make_settings, run_setup, state_of

SECRET = "discover-test-secret-key-0123456789abcdef"


def instance_id(db: Path) -> str | None:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT instance_id FROM app_meta").fetchone()[0]
    finally:
        conn.close()


async def discover(app: FastAPI, host: str | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    headers = {"Host": host} if host else {}
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as screen:
        return await screen.get("/api/discover", headers=headers)


async def test_a_screen_learns_what_this_sunroom_is(
    parent: httpx.AsyncClient, app: FastAPI
) -> None:
    response = await discover(app, "192.168.1.20:8080")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"sunroom", "id", "version", "setup_complete", "name", "url", "language"}
    assert body["sunroom"] is True
    assert uuid.UUID(body["id"]).version == 7
    assert body["version"] == build_info().version
    assert body["setup_complete"] is True
    assert body["name"] == "Sample Family"
    assert body["url"] is None  # no SUNROOM_ADVERTISED_URL here: the screen keeps what it found
    assert body["language"] == "en"  # the screen's own pages speak it (ADR 0043)


@pytest.mark.parametrize(
    ("host", "named"),
    [
        ("192.168.1.20:8080", True),
        ("[fd00::20]:8080", True),
        ("sunroom.local", True),
        ("sunroom.local:8080", True),
        ("nas", True),
        ("localhost:8080", True),
        ("kitchen.home.arpa", True),
        ("calendar.example.com", False),
        ("evil.example:8080", False),
    ],
)
async def test_the_household_name_goes_only_to_a_local_address(
    parent: httpx.AsyncClient, app: FastAPI, host: str, named: bool
) -> None:
    """A page on the internet rebound to the server's address still sends its own public name."""
    body = (await discover(app, host)).json()
    assert body["name"] == ("Sample Family" if named else None)
    assert body["id"]  # everything else is the same for every caller


async def test_before_setup_it_says_so_and_names_nobody(app: FastAPI) -> None:
    body = (await discover(app, "192.168.1.20:8080")).json()
    assert body["setup_complete"] is False
    assert body["name"] is None
    assert body["language"] is None  # no household has chosen yet: the screen keeps its own


async def test_the_advertised_address_is_handed_on(data_dir: Path) -> None:
    settings = make_settings(data_dir, sunroom_advertised_url="http://sunroom.local:8080")
    app = create_app(settings, secret=SECRET)
    async with app.router.lifespan_context(app):
        assert (await discover(app)).json()["url"] == "http://sunroom.local:8080"


async def test_it_needs_no_sign_in_and_is_not_a_recent_address(app: FastAPI) -> None:
    response = await discover(app, "192.168.1.20:8080")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert "192.168.1.20:8080" not in state_of(app).recent_hosts


def test_the_route_is_in_the_schema_as_a_get(data_dir: Path) -> None:
    """The gotcha: ``app.routes`` holds included routers, so walk the schema's paths."""
    paths = create_app(make_settings(data_dir), secret=SECRET).openapi()["paths"]
    assert set(paths["/api/discover"]) == {"get"}
    assert paths["/api/discover"]["get"]["responses"]["200"]["content"]["application/json"]


async def test_the_id_lasts_through_a_restart(data_dir: Path) -> None:
    seen: list[str] = []
    for _ in range(2):
        app = create_app(make_settings(data_dir), secret=SECRET)
        async with app.router.lifespan_context(app):
            seen.append((await discover(app)).json()["id"])
    assert seen[0] == seen[1] == instance_id(data_dir / "sunroom.db")


def new_card_restored_from(copy: Path, card: Path, template: Path) -> None:
    """A new card with an id of its own, then the copy swapped in, as `sunroom restore` does
    with the server stopped."""
    card.mkdir()
    (card / "sunroom.db").write_bytes(template.read_bytes())
    conn = sqlite3.connect(card / "sunroom.db")
    conn.execute("UPDATE app_meta SET instance_id = ?", (str(uuid.uuid7()),))
    conn.commit()
    conn.close()
    assert instance_id(card / "sunroom.db") != instance_id(copy)
    (card / "sunroom.db").write_bytes(copy.read_bytes())


async def test_a_restored_copy_brings_its_id_with_it(tmp_path: Path, data_dir: Path) -> None:
    """The id travels with the data: a server restored onto a new card is found again."""
    first = create_app(make_settings(data_dir), secret=SECRET)
    async with first.router.lifespan_context(first):
        transport = httpx.ASGITransport(app=first)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as phone:
            assert (await run_setup(phone)).status_code == 201
        original = (await discover(first)).json()["id"]
        copy = Path((await state_of(first).backups.run_now()).path)
    other = tmp_path / "other"
    await asyncio.to_thread(new_card_restored_from, copy, other, data_dir / "sunroom.db")
    restored = create_app(make_settings(other), secret=SECRET)
    async with restored.router.lifespan_context(restored):
        assert (await discover(restored)).json()["id"] == original


def test_boot_gives_a_row_without_an_id_one(data_dir: Path) -> None:
    db = data_dir / "sunroom.db"
    conn = sqlite3.connect(db)
    conn.execute("UPDATE app_meta SET instance_id = NULL")
    conn.commit()
    conn.close()
    reconcile_app_meta(make_settings(data_dir), SECRET)
    made = instance_id(db)
    assert made is not None and uuid.UUID(made).version == 7
    reconcile_app_meta(make_settings(data_dir), SECRET)
    assert instance_id(db) == made  # once made, kept
