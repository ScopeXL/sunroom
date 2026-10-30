#!/usr/bin/env python3
"""Sunroom's server as a wheel, for Sunroom run as a program on a computer (ADR 0038): the
backend with the built app inside and the release's version stamped in, and the constraints file
that holds what it runs on to backend/uv.lock, as the image is. `just server-build` runs it, and
so does the release workflow.

The repo's backend stays 0.0.0 (PLAN §14.5): the wheel is built from a copy, with VERSION written
into the copy's pyproject and the built app (frontend/dist, which `vite build` makes first)
copied into the copy's package as sunroom/static, the words (lang/) as sunroom/lang. Into
backend/dist (or --out):

  sunroom-X.Y.Z-py3-none-any.whl
  sunroom-X.Y.Z-constraints.txt
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Sunroom's server wheel and constraints.")
    parser.add_argument("--out", type=Path, default=REPO / "backend" / "dist")
    args = parser.parse_args()
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    app = REPO / "frontend" / "dist"
    if not (app / "index.html").is_file():
        fail("frontend/dist has no index.html: build the app first (cd frontend; vite build).")
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("sunroom-*"):
        old.unlink()

    with tempfile.TemporaryDirectory(prefix="sunroom-wheel-") as temp:
        root = Path(temp) / "backend"
        root.mkdir()
        shutil.copy2(REPO / "backend" / "pyproject.toml", root / "pyproject.toml")
        shutil.copytree(
            REPO / "backend" / "src",
            root / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "static", "lang"),
        )
        shutil.copytree(app, root / "src" / "sunroom" / "static")
        # The words (ADR 0043): core/lang.py reads lang/en.json from inside the package.
        shutil.copytree(REPO / "lang", root / "src" / "sunroom" / "lang")
        project = root / "pyproject.toml"
        stamped, count = re.subn(
            r'^version = "0\.0\.0"',
            f'version = "{version}"',
            project.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            fail('backend/pyproject.toml has no version = "0.0.0" line to stamp.')
        project.write_text(stamped, encoding="utf-8")
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(root)], check=True)

    wheel = out / f"sunroom-{version}-py3-none-any.whl"
    if not wheel.is_file():
        fail(f"No {wheel.name} was built.")
    with zipfile.ZipFile(wheel) as archive:
        if "sunroom/static/index.html" not in archive.namelist():
            fail(f"{wheel.name} has no built app (sunroom/static/index.html).")
        if "sunroom/lang/en.json" not in archive.namelist():
            fail(f"{wheel.name} has no words (sunroom/lang/en.json).")
        metadata = archive.read(f"sunroom-{version}.dist-info/METADATA").decode()
        if f"\nVersion: {version}\n" not in metadata:
            fail(f"{wheel.name} doesn't say it is version {version}.")

    constraints = out / f"sunroom-{version}-constraints.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--no-header",  # it names the output's absolute path
            "--no-annotate",
            "--format",
            "requirements-txt",
            "--output-file",
            str(constraints),
        ],
        cwd=REPO / "backend",
        check=True,
        stdout=subprocess.DEVNULL,
    )
    print(f"Built {wheel.relative_to(REPO) if wheel.is_relative_to(REPO) else wheel}")
    print(f"and {constraints.relative_to(REPO) if constraints.is_relative_to(REPO) else constraints}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
