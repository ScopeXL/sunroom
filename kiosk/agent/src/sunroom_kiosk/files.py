"""Where the installer's templates and helpers are (ADR 0044): inside the package, which the wheel
carries them into (hatchling's ``force-include`` of ``kiosk/files``, ``uninstall.sh``,
``labwc-rule.py`` and ``update.sh``), or the checkout's ``kiosk/`` when run from one."""

from __future__ import annotations

from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_CHECKOUT = _PACKAGE.parents[2]  # kiosk/, from kiosk/agent/src/sunroom_kiosk


def files_dir() -> Path:
    """The templates: the package's copy when it has one, else the checkout's ``kiosk/files``."""
    packaged = _PACKAGE / "files"
    return packaged if packaged.is_dir() else _CHECKOUT / "files"


def script(name: str) -> Path:
    """One of the helpers the installer keeps beside them: ``uninstall.sh``, ``labwc-rule.py``,
    ``update.sh`` (the package's ``files/``, the checkout's ``kiosk/``)."""
    packaged = _PACKAGE / "files" / name
    return packaged if packaged.is_file() else _CHECKOUT / name
