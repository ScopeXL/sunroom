#!/usr/bin/env python3
"""Try this checkout's installers before a release, on another computer or a virtual machine on
this network (docs/KIOSK.md, "Trying a change before a release"). `just kiosk-serve` builds
Sunroom Screen's wheel and Sunroom's server wheel, then this serves them with the installers and
prints one line per system:

  GET /install.sh      a few lines of bash: this checkout's kiosk folder and the wheels into a
                       temporary folder, then its install.sh with --agent-wheel, --server-wheel
                       and any options
  GET /install.ps1     the same for Windows: install.ps1 and the wheels, then -AgentWheel and
                       -ServerWheel
  GET /kiosk.tar.gz    the kiosk files install.sh needs, as git tracks them, and the wheels
  GET /kiosk/...       install.ps1 and Sunroom Screen's wheel on their own
  GET /server/...      Sunroom's server wheel and its constraints (On This Computer, ADR 0038)

So a computer that runs it takes nothing from GitHub; uv, its Python and a browser still come
from their makers. Only what git tracks under kiosk/ is served, plus the wheels. Ctrl+C stops it.
"""

from __future__ import annotations

import io
import socket
import subprocess
import sys
import tarfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIOSK_FILES = (
    "kiosk/install.sh",
    "kiosk/install.ps1",
    "kiosk/labwc-rule.py",
    "kiosk/update.sh",
    "kiosk/uninstall.sh",
)

BASH = """#!/usr/bin/env bash
# Sunroom's installer from {base}, before a release (scripts/kiosk_serve.py): this checkout's
# kiosk folder and Sunroom Screen's wheel, then the installer from that copy.
set -euo pipefail
try_sunroom() {{
\tlocal dir
\tdir=$(mktemp -d)
\tcurl -fsSL "{base}/kiosk.tar.gz" | tar -xzf - -C "$dir"
\tbash "$dir/kiosk/install.sh" --agent-wheel "$dir/kiosk/agent/dist/{wheel}" \\
\t\t--server-wheel "$dir/server/{server}" "$@"
}}
try_sunroom "$@"
"""

POWERSHELL = """# Sunroom Screen's installer from {base}, before a release (scripts/kiosk_serve.py):
# Sunroom Screen's wheel and Sunroom's, then this checkout's install.ps1 in this same window, as
# the real line runs it (a second PowerShell is what Microsoft Defender stops, ADR 0041).
$sunroomTry = Join-Path ([IO.Path]::GetTempPath()) "sunroom-try"
$null = New-Item -ItemType Directory -Force -Path $sunroomTry
$tryWheel = Join-Path $sunroomTry "{wheel}"
$tryServer = Join-Path $sunroomTry "{server}"
$ProgressPreference = "SilentlyContinue"
Invoke-WebRequest -Uri "{base}/kiosk/agent/dist/{wheel}" -OutFile $tryWheel -UseBasicParsing
Invoke-WebRequest -Uri "{base}/server/{server}" -OutFile $tryServer -UseBasicParsing
Invoke-WebRequest -Uri "{base}/server/{constraints}" -UseBasicParsing `
    -OutFile (Join-Path $sunroomTry "{constraints}")
$tryScript = Invoke-RestMethod -Uri "{base}/kiosk/install.ps1" -UseBasicParsing
& ([scriptblock]::Create($tryScript)) -AgentWheel $tryWheel -ServerWheel $tryServer @args
"""


def tracked(prefix: str) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", prefix], cwd=REPO, capture_output=True, check=True
    )
    return [name for name in listed.stdout.decode().split("\0") if name]


def tarball(wheel: Path, server: Path, constraints: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in [*KIOSK_FILES, *tracked("kiosk/files")]:
            tar.add(REPO / name, arcname=name)
        tar.add(wheel, arcname=f"kiosk/agent/dist/{wheel.name}")
        tar.add(server, arcname=f"server/{server.name}")
        tar.add(constraints, arcname=f"server/{constraints.name}")
    return buffer.getvalue()


def this_address() -> str:
    """This computer's address on its network: the one its default route leaves from (a UDP
    socket's connect sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    wheel = REPO / "kiosk/agent/dist" / f"sunroom_kiosk-{version}-py3-none-any.whl"
    server = REPO / "backend/dist" / f"sunroom-{version}-py3-none-any.whl"
    constraints = REPO / "backend/dist" / f"sunroom-{version}-constraints.txt"
    for built, recipe in ((wheel, "kiosk-build"), (server, "server-build")):
        if not built.is_file():
            print(f"No {built.name}: run `just {recipe}` first.")
            return 1
    base = f"http://{this_address()}:{port}"
    names = {"wheel": wheel.name, "server": server.name, "constraints": constraints.name}
    files: dict[str, tuple[bytes, str]] = {
        "/install.sh": (BASH.format(base=base, **names).encode(), "text/plain"),
        "/install.ps1": (POWERSHELL.format(base=base, **names).encode(), "text/plain"),
        "/kiosk.tar.gz": (tarball(wheel, server, constraints), "application/gzip"),
        "/kiosk/install.ps1": ((REPO / "kiosk/install.ps1").read_bytes(), "text/plain"),
        f"/kiosk/agent/dist/{wheel.name}": (wheel.read_bytes(), "application/octet-stream"),
        f"/server/{server.name}": (server.read_bytes(), "application/octet-stream"),
        f"/server/{constraints.name}": (constraints.read_bytes(), "text/plain"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            found = files.get(self.path.split("?", 1)[0])
            if found is None:
                self.send_error(404)
                return
            body, kind = found
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving this checkout's installers, {wheel.name} and {server.name} on port {port}.")
    print("If macOS asks whether Python may accept incoming connections, allow it.\n")
    print("On a Linux computer or a Mac (options go after `bash -s --`):")
    print(f"  curl -fsSL {base}/install.sh | bash")
    print("On Windows, in PowerShell:")
    print(f"  irm {base}/install.ps1 | iex")
    print("\nA virtual machine on this Mac can use the same address. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
