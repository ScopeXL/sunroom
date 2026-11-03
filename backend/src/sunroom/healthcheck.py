"""Docker HEALTHCHECK probe: standard library only, so it starts fast and needs no curl."""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    port = int(os.environ.get("PORT", "7867"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
