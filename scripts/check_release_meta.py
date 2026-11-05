#!/usr/bin/env python3
"""VERSION is the only version (PLAN §14.5, after Dinner Bell's ADR 0019); everything else stays
0.0.0, except what must carry it: the installers (install.sh and install.ps1), each
naming its own Release, and Sunroom Screen's package, whose wheel is named for it and whose updates compare it
(docs/M7.md T11, T14).
`release.py bump` writes all of them.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
problems: list[str] = []

version = (REPO / "VERSION").read_text().strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    problems.append(f"VERSION must be X.Y.Z (found {version!r})")

pyproject = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())
if pyproject["project"]["version"] != "0.0.0":
    problems.append("backend/pyproject.toml version must stay 0.0.0 (VERSION is the source)")

package = json.loads((REPO / "frontend" / "package.json").read_text())
if package.get("version") != "0.0.0":
    problems.append("frontend/package.json version must stay 0.0.0 (VERSION is the source)")

# The Pi installer is fetched from main, so it carries the released version too.
kiosk = re.search(r'^KIOSK_VERSION="([^"]*)"', (REPO / "kiosk" / "install.sh").read_text(), re.M)
if not kiosk or kiosk.group(1) != version:
    problems.append(f"kiosk/install.sh KIOSK_VERSION must equal VERSION ({version}); `just bump` sets both")

windows = re.search(r'^\s*\$KioskVersion = "([^"]*)"', (REPO / "kiosk" / "install.ps1").read_text(), re.M)
if not windows or windows.group(1) != version:
    problems.append(f"kiosk/install.ps1 $KioskVersion must equal VERSION ({version}); `just bump` sets it")

# Sunroom Screen: its pyproject.toml, and its own entry in uv.lock (or `uv sync --locked` fails).
agent = tomllib.loads((REPO / "kiosk" / "agent" / "pyproject.toml").read_text())
if agent["project"]["version"] != version:
    problems.append(f"kiosk/agent/pyproject.toml version must equal VERSION ({version}); `just bump` sets both")
lock = tomllib.loads((REPO / "kiosk" / "agent" / "uv.lock").read_text())
locked = [p.get("version") for p in lock.get("package", []) if p.get("name") == "sunroom-kiosk"]
if locked != [version]:
    problems.append(f"kiosk/agent/uv.lock's sunroom-kiosk must be version {version} (found {locked}); `just bump` sets it")

if "## [Unreleased]" not in (REPO / "CHANGELOG.md").read_text():
    problems.append("CHANGELOG.md needs an ## [Unreleased] section")

if problems:
    print("\n".join(problems), file=sys.stderr)
    sys.exit(1)
print(f"Release metadata OK (VERSION {version}).")
