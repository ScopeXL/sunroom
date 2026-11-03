"""Settings from the environment (PLAN §14.2): everything optional, problems named not echoed."""

from __future__ import annotations

import pytest

from sunroom.core.config import PLACEHOLDER_SECRET, ConfigError, InstallKind, load_settings


def problems(env: dict[str, str]) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        load_settings(env)
    return caught.value.problems


def test_nothing_is_required() -> None:
    settings = load_settings({})
    assert settings.app_secret_key is None  # generated at first boot
    assert settings.app_password is None  # chosen in the setup wizard
    assert settings.tz is None
    assert settings.port == 7867
    assert str(settings.db_path) == "/data/sunroom.db"
    assert str(settings.secret_key_path) == "/data/secret.key"
    assert settings.sunroom_install_kind is InstallKind.DOCKER


def test_app_password_needs_eight_characters() -> None:
    """ADR 0034: eight, as setup asks (it was 12)."""
    assert any(
        "APP_PASSWORD must be at least 8 characters" in p
        for p in problems({"APP_PASSWORD": "seven77"})
    )
    assert load_settings({"APP_PASSWORD": "eight888"}).app_password is not None


def test_lists_split_on_commas() -> None:
    settings = load_settings({"APP_ALLOWED_HOSTS": "Calendar.Example.com, *.example.org"})
    assert settings.app_allowed_hosts == ("calendar.example.com", "*.example.org")


def test_empty_values_from_a_stack_mean_unset() -> None:
    """Portainer passes `${APP_PASSWORD}` through as an empty string when it isn't set."""
    settings = load_settings({"APP_SECRET_KEY": "", "APP_PASSWORD": "", "TZ": ""})
    assert settings.app_secret_key is None
    assert settings.app_password is None
    assert settings.tz is None


def test_problems_name_variables_but_never_echo_values() -> None:
    secret = "short-secret"
    found = problems({"APP_SECRET_KEY": secret, "APP_PASSWORD": "tiny", "TZ": "Mars/Base"})
    text = "\n".join(found)
    assert "APP_SECRET_KEY must be at least 32 characters" in text
    assert "APP_PASSWORD must be at least 8 characters" in text
    assert "TZ must be an IANA time zone" in text
    assert secret not in text
    assert "tiny" not in text


def test_placeholder_secret_is_rejected() -> None:
    assert any("placeholder" in p for p in problems({"APP_SECRET_KEY": PLACEHOLDER_SECRET}))


@pytest.mark.parametrize(
    "hosts", ["https://calendar.example.com", "calendar.example.com:443", "*", "a b", "*.*"]
)
def test_allowed_hosts_are_names_only(hosts: str) -> None:
    assert any(p.startswith("APP_ALLOWED_HOSTS") for p in problems({"APP_ALLOWED_HOSTS": hosts}))


def test_a_leftover_trusted_proxies_is_ignored_with_a_note() -> None:
    """ADR 0034: a proxy on the home network is believed by itself, so an old compose file's
    TRUSTED_PROXIES line still starts, and the log says it's no longer needed."""
    env = {"TRUSTED_PROXIES": "10.0.0.1"}
    settings = load_settings(env)
    assert not hasattr(settings, "trusted_proxies")
    assert settings.warnings(env) == [
        "TRUSTED_PROXIES is no longer needed and is ignored: Sunroom believes a reverse proxy "
        "on the home network by itself (docs/REMOTE-ACCESS.md)"
    ]


@pytest.mark.parametrize("url", ["sunroom.local", "ftp://x.test", "http://x.test/path"])
def test_advertised_url_is_an_address(url: str) -> None:
    found = problems({"SUNROOM_ADVERTISED_URL": url})
    assert any(p.startswith("SUNROOM_ADVERTISED_URL") for p in found)


def test_advertised_url_is_trimmed_to_an_origin() -> None:
    settings = load_settings({"SUNROOM_ADVERTISED_URL": "http://sunroom.local:7867/"})
    assert settings.sunroom_advertised_url == "http://sunroom.local:7867"


def test_test_mode_is_refused_in_the_container() -> None:
    found = problems({"SUNROOM_TEST_MODE": "1", "SUNROOM_CONTAINER": "1"})
    assert any("SUNROOM_TEST_MODE" in p for p in found)


def test_update_check_can_be_forced_off() -> None:
    assert load_settings({"SUNROOM_UPDATE_CHECK": "0"}).update_check_forced_off
    assert not load_settings({}).update_check_forced_off


def test_warnings_flag_typos() -> None:
    settings = load_settings({})
    warnings = settings.warnings({"APP_PASSWROD": "x", "SUNROOM_BUILD_INFO": "/app/x"})
    assert any("APP_PASSWROD" in w for w in warnings)
    assert not any("SUNROOM_BUILD_INFO" in w for w in warnings)


def test_secret_literals_cover_every_secret() -> None:
    settings = load_settings(
        {"APP_SECRET_KEY": "a-very-long-random-secret-key-0123456789", "APP_PASSWORD": "pw" * 8}
    )
    assert set(settings.secret_literals()) == {
        "a-very-long-random-secret-key-0123456789",
        "pw" * 8,
    }
