#!/usr/bin/env python3
"""The files people install Sunroom from say the same thing (docs/DEPLOY.md, ADR 0046): the compose
example, Unraid's template and the CasaOS store name one image and one port and a kind of install the
server knows. The compose example's updater keeps its schedule, watches Sunroom alone and publishes no
port: a file without HTTP_API_PERIODIC_POLLS would never install anything overnight, and say nothing.
`just deploy-check` runs it, and `just check`."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

REPO = Path(__file__).resolve().parent.parent
IMAGE = "scopexl/sunroom"
PORT = "7867"
LABEL = "com.centurylinklabs.watchtower.enable"
problems: list[str] = []


def check(ok: object, problem: str) -> None:
    if not ok:
        problems.append(problem)


def kinds() -> set[str]:
    words: dict[str, str] = json.loads((REPO / "lang" / "en.json").read_text(encoding="utf-8"))
    found = (re.fullmatch(r"api\.update\.how\.(\w+)", key) for key in words)
    return {match[1] for match in found if match} - {"companion", "companion_waits"}


def image_of(text: str) -> str:
    return text.split("@")[0].rsplit(":", 1)[0]


def compose_example() -> None:
    where = "docker-compose.example.yml"
    compose: dict[str, Any] = yaml.safe_load((REPO / where).read_text(encoding="utf-8"))
    services = compose["services"]
    sunroom, updater = services["sunroom"], services["sunroom-updater"]
    check(image_of(sunroom["image"]) == IMAGE, f"{where}: Sunroom isn't {IMAGE}")
    check(f"{PORT}:{PORT}" in sunroom["ports"], f"{where}: Sunroom isn't on {PORT}")
    check(sunroom["labels"].get(LABEL) == "true", f"{where}: the updater wouldn't watch Sunroom")
    env = updater["environment"]
    check(
        env.get("WATCHTOWER_HTTP_API_PERIODIC_POLLS") == "true",
        f"{where}: without HTTP_API_PERIODIC_POLLS the API turns the schedule off",
    )
    check(env.get("WATCHTOWER_LABEL_ENABLE") == "true", f"{where}: the updater isn't to Sunroom alone")
    check(env.get("WATCHTOWER_SCHEDULE"), f"{where}: the updater has no schedule")
    check(
        "update" in str(env.get("WATCHTOWER_HTTP_API_ENDPOINTS")).split(",")
        and "health" in str(env.get("WATCHTOWER_HTTP_API_ENDPOINTS")).split(","),
        f"{where}: Sunroom needs the updater's update and health endpoints",
    )
    check("@sha256:" in updater["image"], f"{where}: the updater isn't pinned by digest")
    check("ports" not in updater, f"{where}: the updater must publish no port")
    check(
        env.get("WATCHTOWER_HTTP_API_TOKEN") == sunroom["environment"].get("SUNROOM_UPDATER_TOKEN"),
        f"{where}: Sunroom and the updater don't share a token",
    )
    check(
        "volumes" not in sunroom or not any("docker.sock" in v for v in sunroom["volumes"]),
        f"{where}: Sunroom must never see the Docker socket",
    )


def unraid() -> None:
    where = "deploy/unraid/sunroom.xml"
    root = ElementTree.parse(REPO / where).getroot()
    check(image_of(root.findtext("Repository", "")) == IMAGE, f"{where}: not {IMAGE}")
    configs = {config.get("Target"): config for config in root.findall("Config")}
    check(PORT in configs, f"{where}: no port {PORT}")
    check("/data" in configs, f"{where}: no /data")
    kind = configs.get("SUNROOM_INSTALL_KIND")
    check(
        kind is not None and kind.text == "unraid" and kind.text in kinds(),
        f"{where}: the install kind isn't unraid",
    )
    check("--user 99:100" in root.findtext("ExtraParams", ""), f"{where}: appdata needs --user 99:100")
    ElementTree.parse(REPO / "deploy/unraid/ca_profile.xml")


def casaos() -> None:
    where = "deploy/casaos/Apps/Sunroom/docker-compose.yml"
    store = json.loads((REPO / "deploy/casaos/store-config.json").read_text(encoding="utf-8"))
    check(store.get("version") == 2, "deploy/casaos/store-config.json: the store's version isn't 2")
    compose: dict[str, Any] = yaml.safe_load((REPO / where).read_text(encoding="utf-8"))
    casa = compose["x-casaos"]
    sunroom = compose["services"][casa["main"]]
    check(image_of(sunroom["image"]) == IMAGE, f"{where}: not {IMAGE}")
    check(
        str(casa["port_map"]) == PORT and str(sunroom["ports"][0]["target"]) == PORT,
        f"{where}: not on {PORT}",
    )
    kind = sunroom["environment"].get("SUNROOM_INSTALL_KIND")
    check(kind == "casaos" and kind in kinds(), f"{where}: the install kind isn't casaos")
    for field in ("id", "index", "icon", "title", "category", "version", "architectures"):
        check(casa.get(field), f"{where}: x-casaos has no {field}")
    check(casa.get("version") == "0.0.0", f"{where}: the workflow writes the version; leave 0.0.0")
    check((REPO / where).parent.joinpath(casa["icon"]).is_file(), f"{where}: no icon file")
    check({"amd64", "arm64"} <= set(casa["architectures"]), f"{where}: amd64 and arm64")


def main() -> None:
    compose_example()
    unraid()
    casaos()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        sys.exit(1)
    print("The install files agree.")


if __name__ == "__main__":
    main()
