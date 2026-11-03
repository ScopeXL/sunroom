from __future__ import annotations

import logging

import pytest

from sunroom.core.logging import MASK, Redactor, configure_logging, get_logger

SECRET = "super-secret-value-123"


def test_sensitive_keys_are_masked() -> None:
    redact = Redactor()
    out = redact(
        None,
        "info",
        {
            "event": "x",
            "password": "p",
            "refresh_token": "r",
            "Cookie": "c",
            "code": "abc",
            "pin": "1234",
            "poll_token": "t",
            "credentials_enc": "e",
        },
    )
    for key in (
        "password",
        "refresh_token",
        "Cookie",
        "code",
        "pin",
        "poll_token",
        "credentials_enc",
    ):
        assert out[key] == MASK, key


def test_a_photo_library_s_api_key_is_masked_however_it_is_spelled() -> None:
    # Immich's header (ADR 0036), and the same name with an underscore or none.
    out = Redactor()(None, "info", {"event": "x", "x-api-key": "k", "api_key": "k", "apikey": "k"})
    assert (out["x-api-key"], out["api_key"], out["apikey"]) == (MASK, MASK, MASK)
    assert out["event"] == "x"


def test_literal_secrets_and_token_shapes_are_scrubbed_anywhere() -> None:
    redact = Redactor([SECRET])
    out = redact(
        None,
        "info",
        {
            "event": f"failed with {SECRET}",
            "detail": {"nested": ["Bearer abc.def-ghi", "gAAAAA" + "x" * 30]},
            "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        },
    )
    assert SECRET not in str(out)
    assert "Bearer abc" not in str(out)
    assert "gAAAAA" not in str(out)
    assert "eyJhbGci" not in str(out)


def test_no_secret_reaches_captured_output(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True, secret_literals=[SECRET])
    get_logger("test").info("login.attempt", password=SECRET, note=f"value {SECRET}")
    logging.getLogger("uvicorn.error").info("stdlib message with %s", SECRET)
    captured = capsys.readouterr().out
    assert "login.attempt" in captured
    assert "stdlib message" in captured
    assert SECRET not in captured


def test_the_request_log_masks_a_pairing_poll_token() -> None:
    from sunroom.app import RequestLog

    masked = RequestLog.logged_path("/api/auth/kiosk/pairings/Qx7-secret-poll-token_0123456789")
    assert masked == "/api/auth/kiosk/pairings/…"
    assert "secret" not in masked
    # The route itself, and every other path, stay readable.
    assert RequestLog.logged_path("/api/auth/kiosk/pairings") == "/api/auth/kiosk/pairings"
    assert RequestLog.logged_path("/api/calendar/events/abc") == "/api/calendar/events/abc"
