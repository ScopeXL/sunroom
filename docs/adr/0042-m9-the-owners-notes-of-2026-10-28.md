# ADR 0042: The owner's notes of 2026-10-28 (M9)

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

- Sunroom 0.16.1 went on the owner's wall and devices, and Sunroom Screen was tried on Windows, a
  Mac and Linux. The owner's notes of 2026-10-28 were fifteen, in four groups: the Calendar's
  header (the views in one menu, Rolling week as a view of its own, Week with Hours by default);
  the screen's first setup (the choice cards, the address check, the browser that closed and
  reopened, the wizard's words); This Screen and Devices (the network row, the address, updates
  overnight, Shut Down's words, rotation on a computer, Uninstall, renaming screens); and the
  project around the app (no more Sunroom OS, no more "kitchen screen" or "phones" where any device
  is meant, a Discord, and feedback that needs no account). `docs/M9.md` turns them into tasks,
  answers the owner's questions and records every decision; this ADR keeps the ones that change an
  earlier decision or that a later session would otherwise have to rediscover (PLAN §15, M9 →
  0.17.0). It was started with the batch's first task and gained a row with each task after.
- The owner settled the plan's open questions on 2026-10-28: Sunroom OS is deleted, not hidden;
  the Discord webhook lives in a relay the owner runs, which this batch also writes for the owner
  to deploy (never in the repo or the image); and Week with Hours is the default for new
  households only.

## Decision

| Question | Decision |
|---|---|
| Sunroom OS | **Retired, and deleted** (changes part of ADR 0035): `kiosk/os/` (the pi-gen stage, `build.sh`, `imager.py`, the boot splash), its workflow and `docs/SUNROOM-OS.md` are gone, and with them the agent's paths for it: the platform's `sunroom_os` and `update_system`, the Pi's Docker `run_sunroom` (and `PullProgress`, and `stream_command`, which only it used), the updater's restart on `/run/reboot-required`, the root helper's `apt-upgrade` and `run-sunroom`, and `sunroom_os` in the agent's state. A Pi is a Linux computer set up with the installer on Raspberry Pi OS: On This Computer runs Sunroom there as a program, as on any computer (ADR 0038), and `--with-sunroom` (Docker on a Pi) stays, updated through the helper's `update-sunroom`. **Connect to Wi-Fi first** is no longer Sunroom OS's: any screen with no network that can join Wi-Fi goes there before either way. **Updates are Install overnight by default on every screen** (it was Sunroom OS's default alone; a screen whose Updates was set to Off keeps Off). The 0.16.1 Release keeps the last image, and Raspberry Pi Imager's Sunroom entry stops updating; git history keeps the build. The pretend platform keeps `run_sunroom`, the stand-in for local.py under `--fake` |

## Consequences

- No schema change from Sunroom OS. The agent's state (`GET /api/screen`) loses `sunroom_os`
  (`screen-openapi.json` and its types); the root helper's usage is `write-policy PATH |
  update-sunroom`; `just kiosk-image` and the release's Sunroom OS run are gone (RELEASING, the
  deploy skill).
