"""Settings come from environment variables only (docs/PLAN.md §14.2).

Infrastructure only: the household's own choices (time zone, theme, the password chosen in the
setup wizard) live in the database. Problems are reported by variable *name*, never by value,
so a misconfigured secret can't end up in a log. The CLI prints the report and exits with 78.
"""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, ClassVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"  # noqa: S105 - the documented placeholder
# A public reverse-proxy name: exact (calendar.example.com) or one wildcard label (*.example.com).
_ALLOWED_HOST = re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")


class InstallKind(StrEnum):
    """Only changes how the update pill words its instructions (PLAN §13.6)."""

    DOCKER = "docker"
    PI = "pi"
    PORTAINER = "portainer"
    HA = "ha"
    COMPUTER = "computer"  # run as a program for a computer's user by Sunroom Screen (ADR 0038)


class ConfigError(Exception):
    """Raised with a list of human-readable problems; each names a variable, never a value."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # Optional: when unset, generated on first boot and kept at $DATA_DIR/secret.key
    # (core/secretkey.py).
    app_secret_key: SecretStr | None = None
    # Optional: overrides the password chosen in the setup wizard, at every boot (ADR 0006).
    app_password: SecretStr | None = None
    # Optional lock (ADR 0034): set, the Host rule accepts only LAN-style names plus these;
    # unset, any Host is answered.
    app_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = ()
    tz: str | None = None
    port: int = Field(default=8080, ge=1024, le=65535)
    log_level: str = "INFO"
    data_dir: Path = Path("/data")
    data_dir_unsafe_fs_ok: bool = False
    sunroom_advertised_url: str | None = None
    sunroom_install_kind: InstallKind = InstallKind.DOCKER
    sunroom_update_check: bool | None = None
    sunroom_allow_private_urls: bool = False
    sunroom_test_mode: bool = False
    # Optional (ADR 0042): where Send Feedback posts; unset, the project's relay
    # (meta/feedback.py); empty, feedback is off. A secret: it may hold a Discord webhook's token.
    sunroom_feedback_url: SecretStr | None = None
    sunroom_container: bool = False
    sunroom_static_dir: Path | None = None

    _LOG_LEVELS: ClassVar[frozenset[str]] = frozenset(
        {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    )

    @field_validator("app_secret_key")
    @classmethod
    def _check_secret_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None  # a stack may pass it through empty: generate one instead
        raw = value.get_secret_value()
        if raw == PLACEHOLDER_SECRET:
            raise ValueError("is still the placeholder; remove it, or use openssl rand -base64 48")
        if len(raw) < 32:
            raise ValueError("must be at least 32 characters (openssl rand -base64 48)")
        return value

    @field_validator("app_password")
    @classmethod
    def _check_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        if len(value.get_secret_value()) < 8:  # auth/password.py's MIN_PASSWORD_LENGTH
            raise ValueError("must be at least 8 characters (a few words together work well)")
        return value

    @field_validator("tz", mode="before")
    @classmethod
    def _empty_tz(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("tz")
    @classmethod
    def _check_tz(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("must be an IANA time zone such as America/New_York") from exc
        return value

    @field_validator("app_allowed_hosts", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("app_allowed_hosts")
    @classmethod
    def _check_allowed_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for entry in value:
            name = entry.lower().rstrip(".")
            if "://" in name or "/" in name or ":" in name:
                raise ValueError("must list host names only, like calendar.example.com")
            if name in {"*", "*.*"} or not _ALLOWED_HOST.match(name):
                raise ValueError("must list host names like calendar.example.com or *.example.com")
            cleaned.append(name)
        return tuple(cleaned)

    @field_validator("sunroom_advertised_url")
    @classmethod
    def _check_advertised_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("must be an address like http://sunroom.local:8080")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("must be an address only, with no path, query or fragment")
        return f"{parts.scheme}://{parts.netloc}"

    @field_validator("sunroom_feedback_url")
    @classmethod
    def _check_feedback_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return value
        parts = urlsplit(value.get_secret_value().strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("must be an address like https://feedback.example.com, or empty")
        return value

    @field_validator("sunroom_update_check", mode="before")
    @classmethod
    def _empty_update_check(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in cls._LOG_LEVELS:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return upper

    @model_validator(mode="after")
    def _check_cross_fields(self) -> Settings:
        if self.sunroom_test_mode and self.sunroom_container:
            raise ValueError("SUNROOM_TEST_MODE is for local end-to-end runs, never a container")
        return self

    # ---- derived values -------------------------------------------------------------------

    @property
    def env_zone(self) -> ZoneInfo | None:
        """The TZ override, if any; the household's own zone lives in the database."""
        return ZoneInfo(self.tz) if self.tz else None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sunroom.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / ".lock"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def update_check_forced_off(self) -> bool:
        return self.sunroom_update_check is False

    def secret_literals(self) -> list[str]:
        """Exact secret values from the environment, so log redaction can scrub them anywhere."""
        values = [
            secret.get_secret_value()
            for secret in (self.app_secret_key, self.app_password, self.sunroom_feedback_url)
            if secret is not None
        ]
        return [v for v in values if v]

    def warnings(self, environ: dict[str, str] | None = None) -> list[str]:
        """Non-fatal problems worth a log line (typos in variable names)."""
        env = os.environ if environ is None else environ
        known = {name.upper() for name in type(self).model_fields}
        found: list[str] = []
        for name in sorted(env):
            upper = name.upper()
            if upper == "TRUSTED_PROXIES":
                found.append(
                    "TRUSTED_PROXIES is no longer needed and is ignored: Sunroom believes a "
                    "reverse proxy on the home network by itself (docs/REMOTE-ACCESS.md)"
                )
                continue
            if upper.startswith(("APP_", "SUNROOM_")) and upper not in known:
                if upper == "SUNROOM_BUILD_INFO":
                    continue  # read by core/version, set in the image
                found.append(f"{name} is not a setting Sunroom knows (typo?)")
        return found


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Build Settings from the environment, turning every problem into a name-only message."""
    try:
        if environ is None:
            return Settings()
        return Settings.model_validate(_lower_keys(environ))
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from None


def _lower_keys(environ: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in environ.items()}


def _describe(exc: ValidationError) -> list[str]:
    problems: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "settings"
        name = location.upper() if error["loc"] else ""
        message = str(error["msg"])
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        if error["type"] == "missing":
            message = "is required"
        problems.append(f"{name} {message}".strip())
    return problems
