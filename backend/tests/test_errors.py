"""The error envelope (ADR 0043): every refusal says its English, and names its key in
lang/en.json and the values that fill it in, so the page can say it in the family's language."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from sunroom.core.errors import (
    _STATUS_CODES,  # pyright: ignore[reportPrivateUsage]
    AppError,
    envelope,
    install_error_handlers,
)
from sunroom.core.lang import Words, english, t_en
from tests.support import BASE_URL, CSRF


class Thing(BaseModel):
    name: str
    count: int


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/plain")
    async def plain() -> None:  # pyright: ignore[reportUnusedFunction]
        raise AppError(409, "no_pin", "api.auth.no_pin")

    @app.get("/valued")
    async def valued() -> None:  # pyright: ignore[reportUnusedFunction]
        raise AppError(
            409,
            "already_done",
            "api.tasks.already_done",
            params={"name": "Mia"},
            extra={"fields": ["due_date"]},
        )

    @app.get("/waited")
    async def waited() -> None:  # pyright: ignore[reportUnusedFunction]
        raise AppError.said(
            429,
            "rate_limited",
            Words("api.auth.wait_minutes", {"minutes": 15}),
            headers={"Retry-After": "900"},
        )

    @app.get("/reason")
    async def reason() -> None:  # pyright: ignore[reportUnusedFunction]
        raise AppError(
            500, "backup_failed", "api.backups.failed", params={"reason": OSError("full")}
        )

    @app.get("/gone")
    async def gone() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(404)

    @app.get("/teapot")
    async def teapot() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(418)

    @app.post("/things")
    async def things(thing: Thing) -> None:  # pyright: ignore[reportUnusedFunction]
        return None

    @app.get("/broken")
    async def broken() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("the test broke it")

    return app


@pytest.fixture
async def bare() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client


async def test_a_refusal_says_its_english_and_names_its_key(bare: httpx.AsyncClient) -> None:
    refused = await bare.get("/plain")
    assert refused.status_code == 409
    assert refused.json() == {
        "error": {
            "code": "no_pin",
            "message": "There's no parent PIN yet. Set one in Settings → Family.",
            "key": "api.auth.no_pin",
            "params": {},
        }
    }
    assert refused.json()["error"]["message"] == english()["api.auth.no_pin"]


async def test_a_sentence_built_from_values_carries_them(bare: httpx.AsyncClient) -> None:
    refused = await bare.get("/valued")
    assert refused.json()["error"] == {
        "code": "already_done",
        "message": "Mia did it already.",
        "key": "api.tasks.already_done",
        "params": {"name": "Mia"},
        "fields": ["due_date"],
    }
    assert refused.json()["error"]["message"] == t_en("api.tasks.already_done", name="Mia")
    waited = await bare.get("/waited")
    assert (waited.status_code, waited.headers["retry-after"]) == (429, "900")
    assert waited.json()["error"] == {
        "code": "rate_limited",
        "message": "Too many tries. Wait 15 minutes.",
        "key": "api.auth.wait_minutes",
        "params": {"minutes": 15},
    }
    # A value that isn't text or a number travels as its text.
    reason = (await bare.get("/reason")).json()["error"]
    assert (reason["message"], reason["params"]) == (
        "The backup didn't complete: full",
        {"reason": "full"},
    )


async def test_a_status_with_no_refusal_of_its_own_says_its_sentence(
    bare: httpx.AsyncClient,
) -> None:
    gone = await bare.get("/gone")
    assert (gone.status_code, gone.json()) == (
        404,
        {
            "error": {
                "code": "not_found",
                "message": "That couldn't be found.",
                "key": "api.http.404",
                "params": {},
            }
        },
    )
    wrong_method = await bare.delete("/plain")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["key"] == "api.http.405"
    # A status the table doesn't name falls back to one plain sentence.
    teapot = await bare.get("/teapot")
    assert (teapot.status_code, teapot.json()["error"]) == (
        418,
        {"code": "error", "message": "Something went wrong.", "key": "api.error", "params": {}},
    )


def test_every_status_has_its_sentence() -> None:
    for status, (code, key) in _STATUS_CODES.items():
        assert key == f"api.http.{status}", code
        assert key in english(), key
        assert envelope(code, key)["error"]["message"] == english()[key]


async def test_details_that_arent_valid_name_their_fields(bare: httpx.AsyncClient) -> None:
    refused = await bare.post("/things", json={"name": 3})
    assert refused.status_code == 422
    assert refused.json()["error"] == {
        "code": "invalid",
        "message": "Some of the details aren't valid.",
        "key": "api.invalid",
        "params": {},
        "fields": ["count", "name"],
    }


async def test_an_unexpected_failure_says_so_plainly(bare: httpx.AsyncClient) -> None:
    broken = await bare.get("/broken")
    assert broken.status_code == 500
    assert broken.json()["error"] == {
        "code": "server_error",
        "message": "Something went wrong on the server. Try again.",
        "key": "api.server_error",
        "params": {},
    }
    assert "broke" not in broken.text  # never what went wrong inside


async def test_the_whole_app_answers_in_the_same_envelope(client: httpx.AsyncClient) -> None:
    """The middleware's refusals (CSRF) and a route's own say the same shape."""
    blocked = await client.post("/api/auth/login", json={"password": "x"})
    assert (blocked.status_code, blocked.json()["error"]) == (
        403,
        {
            "code": "csrf",
            "message": t_en("api.csrf.blocked"),
            "key": "api.csrf.blocked",
            "params": {},
        },
    )
    unknown = await client.get("/api/nothing-here")
    assert unknown.json()["error"]["key"] == "api.http.404"
    not_set_up = await client.post("/api/auth/login", json={"password": "x"}, headers=CSRF)
    assert not_set_up.json()["error"]["key"] == "api.setup.required"


def test_a_refusal_s_english_is_its_message() -> None:
    error = AppError(422, "weak_password", "api.setup.password_short", params={"length": 8})
    assert (
        str(error)
        == error.message
        == ("Use at least 8 characters. A few words together work well.")
    )
    assert (error.key, error.params) == ("api.setup.password_short", {"length": 8})
    with pytest.raises(KeyError):
        AppError(400, "nonsense", "api.nothing.here")  # a key English lacks fails at once
