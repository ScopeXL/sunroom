"""The household password and the parent PIN (PLAN §12.1, §12.3; ADR 0006). Standard library only.

* The password chosen in the setup wizard is stored with ``hashlib.scrypt`` (n 2^15, r 8, p 1,
  16-byte salt). ``APP_PASSWORD``, when set, is checked instead and always wins.
* The PIN (4 to 6 digits) is stored with PBKDF2-SHA256, 200,000 iterations, 16-byte salt.

Both compare in constant time. Hash strings carry their parameters, so they can be raised later
without a migration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from pydantic import SecretStr

from sunroom.auth.schemas import DeviceFormName
from sunroom.core.lang import Words

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8
PIN_PATTERN = re.compile(r"^\d{4,6}$")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode())


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=SCRYPT_MAXMEM,
            dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def env_password_matches(given: str, configured: SecretStr) -> bool:
    """APP_PASSWORD: constant-time comparison of SHA-256 digests (equal length, no early exit)."""
    given_digest = hashlib.sha256(given.encode()).digest()
    configured_digest = hashlib.sha256(configured.get_secret_value().encode()).digest()
    return hmac.compare_digest(given_digest, configured_digest)


def password_problem(password: str) -> Words | None:
    """Why a new household password won't do, in words for the setup wizard; None if it will."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return Words("api.setup.password_short", {"length": MIN_PASSWORD_LENGTH})
    if password.strip() != password:
        return Words("api.setup.password_spaces")
    return None


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = _unb64(digest)
        actual = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), _unb64(salt), int(iterations), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def device_label(user_agent: str | None) -> str:
    """A short, human label for Settings → Devices ("iPhone, Safari")."""
    ua = user_agent or ""
    if "iPhone" in ua:
        device = "iPhone"
    elif "iPad" in ua:
        device = "iPad"
    elif "Android" in ua:
        device = "Android phone" if "Mobile" in ua else "Android tablet"
    elif "CrOS" in ua:
        device = "Chromebook"
    elif "Macintosh" in ua:
        device = "Mac"
    elif "Windows" in ua:
        device = "Windows PC"
    elif "Linux" in ua:
        device = "Linux computer"
    else:
        device = "Device"
    if "Edg/" in ua:
        browser = "Edge"
    elif "Firefox/" in ua or "FxiOS" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        return device
    return f"{device}, {browser}"


_TABLETS = frozenset({"iPad", "Android tablet"})
_COMPUTERS = frozenset({"Chromebook", "Mac", "Windows PC", "Linux computer"})


def device_form(kind: str, label: str) -> DeviceFormName:
    """What a device is, for its icon in Settings → Devices (ADR 0032): a paired screen, else
    what `device_label` called it at sign-in ("Mac, Safari" is a computer). Only a screen ever
    renames itself, so anything else unknown is a phone, as every device was listed before."""
    if kind == "kiosk":
        return "screen"
    device = label.split(",", 1)[0].strip()
    if device in _TABLETS:
        return "tablet"
    if device in _COMPUTERS:
        return "computer"
    return "phone"
