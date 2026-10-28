"""The outbound-request audit (PLAN §12.6, §15 M5): every request Sunroom sends to a server it
was told about goes through the guarded client in core/http.py, and only a parent's own choice
lets one reach a private address. The client-construction check itself is in test_netguard.py;
this one watches the ways around it. A new entry in an allowed list below is a decision: say
why in its comment."""

from __future__ import annotations

import ast
from pathlib import Path

import sunroom

ROOT = Path(sunroom.__file__).parent
NETWORK_MODULES = ("socket", "ssl", "http.client", "urllib.request", "aiohttp", "requests")


def modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.relative_to(ROOT).as_posix(), ast.parse(path.read_text()))
        for path in sorted(ROOT.rglob("*.py"))
    ]


def test_only_the_guard_and_two_local_helpers_touch_the_network_directly() -> None:
    found: dict[str, set[str]] = {}
    for name, tree in modules():
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for module in names:
                if module in NETWORK_MODULES or module.startswith(("aiohttp.", "requests.")):
                    found.setdefault(name, set()).add(module)
    assert found == {
        # Resolves a host name to check every address it gives before connecting.
        "core/netguard.py": {"socket"},
        # The container's health probe asks this server itself, on localhost.
        "healthcheck.py": {"urllib.request"},
        # Knows the container's own host name for the Host rule; sends nothing.
        "web/hosts.py": {"socket"},
    }


def test_the_guarded_client_is_made_once_and_shared() -> None:
    made = [
        name
        for name, tree in modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("GuardedHttp")
    ]
    assert made == ["app.py"]


def test_no_code_lets_itself_reach_a_private_address() -> None:
    """``allow_private`` only ever carries a parent's choice from stored data or a request
    body, never a literal True written into the code."""
    literal: list[str] = []
    for name, tree in modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "allow_private"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        literal.append(f"{name}:{node.lineno}")
    assert literal == []


def test_the_core_reaches_out_only_for_plugins_the_update_check_and_feedback() -> None:
    """Outside plugins (which use ``ctx.http``), the shared client is used by the plugin
    context's factory, the opt-in update check, and Send Feedback when someone sends it (ADR
    0042)."""
    users = sorted(
        {
            name
            for name, tree in modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "http"
            and ast.unparse(node.value) == "state"
            and not name.startswith("plugins/")
        }
    )
    assert users == ["meta/feedback.py", "meta/updates.py"]
