# ADR 0044: Sunroom Screen sets itself up again

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

- Until 0.18.0 an update replaced one thing: Sunroom Screen's wheel. Everything the installer put
  around it (the user service, the LaunchAgent or the Startup shortcut, labwc's autostart block
  and window rule, the browser's policy and the root helper that writes it, the Wi-Fi and
  backlight files, the packages) stayed as the day it was installed, so a release that changed
  how the screen starts, what it runs on or what the helper may do couldn't reach a screen
  already installed, and the only fix was the installer again, in a terminal a family at a wall
  can't type in. The owner's notes of 2026-10-30 asked for an update that does the whole job
  from the screen: tap Update, confirm, and the screen comes back as it was, restarted if need
  be, with every setting and the pairing kept (`docs/M10.md`, Answer D).
- Uninstalling and installing again would lose the pairing (the uninstaller's default deletes the
  browser's profile), leave the screen dark for minutes, and leave nothing to come back to if it
  failed halfway. What the family needs is a fresh install's end state with their settings kept,
  which a rerun of the installer already promises. This ADR records how Sunroom Screen does that
  rerun itself. It was started with the batch's first task of this part (T10) and gains a row
  with each task after.

## Decision

| Question | Decision |
|---|---|
| Who sets the screen up (T10) | **Sunroom Screen, from the version it runs.** Its wheel carries `kiosk/files`, `uninstall.sh`, `labwc-rule.py` and `update.sh` (hatchling's `force-include`), and `sunroom-kiosk setup` renders each file the installer puts in place for this user from them and this screen's settings, compares, and rewrites what differs: the user service; labwc's block and window rule on a Pi on Wayland, the XDG entry on X11 and other Linux desktops; the LaunchAgent on a Mac; Windows' `Run` value; the helper copies; Sunroom run here's service; the settings file; the install-state. It runs at every start (installed as a tool, never from a checkout or `--fake`), so a broken file heals itself |
| Windows' start-up entry (T10) | The `Run` value `SunroomScreen` under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`, `"…\.local\bin\sunroom-kioskw.exe" run`, written with `winreg` (standard library) instead of the Startup folder's `.lnk`, which needs COM to write; setup takes an old `.lnk` out, and `uninstall.py` takes the value out |
| What counts as a change (T10) | Every file names the version that wrote it, so a comparison ignores that: the "Written by" line goes and every version becomes a mark. A version-only difference is rewritten quietly; a restart is asked for only when the service's or LaunchAgent's definition changed, and a reboot only when labwc's block or rule did |
| The settings file (T10) | `SUNROOM_CONFIG_VERSION` and `config.migrate`, ordered steps (none yet), run by setup: a key a step sets is written in place, one it removes is gone, every other line kept |
| What's kept safe (T10) | Before the first change, the settings file, the install-state, `update.json` and `sunroom.json` are copied to `~/.local/state/sunroom-kiosk/backup/<version>/` (`%LOCALAPPDATA%\sunroom-kiosk\backup\` on Windows), once per version, the last three versions kept. The browser's profile and Sunroom's data are never touched |
| Root's part (T10) | Never written by setup: `needs_root` names the root helper (on a Pi, or a computer that has one) and the Wi-Fi, backlight, i2c and avahi files the install-state says the installer wrote, when they differ |
| Root's part, applied (T11) | **The root helper applies it, trusting nothing it's handed**: `sunroom-kiosk-root apply-system WHEEL` reads the release from the wheel's name, fetches that release's `SHA256SUMS` from GitHub itself (HTTPS, the system's certificates) and refuses a wheel it doesn't list; it reads the wheel once into memory (so the file can't be swapped after the check) and takes only known paths from its `kiosk/files`. In order: the Wi-Fi drop-in (a Pi with NetworkManager), the backlight rule or the i2c module file (as the screen's `SUNROOM_BRIGHTNESS` and `SUNROOM_BACKLIGHT` say), an all-in-one Pi's avahi file (its port kept), the packages `files/packages/<pi|linux>.txt` list for this desktop that are missing and offered (names checked against `^[a-z0-9][a-z0-9.+-]*$`), `udevadm` when a rule changed, the user's `video` or `i2c` group, and last the sudoers rule (`visudo -c` first) and the helper's next version. It prints `{changed, failed, needs_reboot}` (a desktop's package or a group counts from the next sign-in) and fails only when the wheel didn't check out. `version` prints the release it was written from. The browser's policy stays `write-policy`'s, `/opt/sunroom` `update.sh`'s |
| A helper too old (T11) | A helper from before 0.18.0 has neither verb, so when root's part differs Sunroom Screen keeps the installer's one line for this platform (`needs_terminal`, from `platform.install_command()`) for This Screen to show; `SYSTEM_PART_SINCE` (`setup_files.py`) names the release whose root files last changed, and a session that changes one bumps it |
| The update, the whole way (T12) | **The apply step runs the new version's setup between its install and its start**: `uv tool install`, then `sunroom-kiosk setup --from-update --json` (its report kept in `update.json`'s `setup`), then the agent started as the report says (Linux: `daemon-reload` when the unit changed; a Mac: `bootout` and `bootstrap` when the LaunchAgent changed, since a running job can't read its own new file, else `kickstart -k`; Windows: `sunroom-kioskw.exe`). A setup that fails outright, or a version that doesn't answer within a minute, puts the previous wheel back *and runs its setup*, so the files always match the version that runs. The updater copies the small files aside before the download (`back_up`, opt-in in its constructor so a test never copies a real home); the apply step's own steps (Setting up… 70, Starting again… 85) reach the wall through `update.json`'s `progress`, which the old agent relays while it still runs |
| The new version's start (T12) | `Agent.finish_update`, at every start: root's part through `apply-system` when it differs and the helper knows the verb (else `needs_terminal`); an all-in-one Pi's Docker Sunroom brought to this version through `update.sh`; then a restart of the computer when the setup or the helper said `needs_reboot`, **once per version** (`rebooted_for` in `update.json`), so a change that keeps asking can never loop. `update.json`'s `last` (`{version, ok, at, previous, again}`) becomes `last_result` in the state only once all that is done, and stays until a page has shown it (`POST /api/screen/update/seen`): one mechanism, so the wall never says Updated twice and a page that connects later still hears it |
| Reinstall… (T12) | `POST /api/screen/reinstall`: the installed version's wheel (kept since it came; downloaded and checked again when it's gone) through the same apply step with `--force`, its setup rewritten whole; it says "Reinstalled Sunroom Screen 0.18.0", and one that fails marks no version as failed |
| This Screen (T13) | **Update Now asks first** (**Update This Screen?**, with what it does and what stays), and the row is the update: each step and its percent, "Starting again…" while the agent is away (the state query errors after it had answered; it asks every 2 s while a step is on), "Restarting the computer…". `lib/screenAgent.followUpdate`, on every state from the stream or the poll, ends the steps once the agent is back and not installing (below 90: the new version's own last steps keep theirs) and says `last_result` once (kept by version and time) before `POST /api/screen/update/seen`. **Update Sunroom Too goes**: the update brings Sunroom along, and the row's hint says when it's behind. **Reinstall…** is quiet and offered only without an update to offer (Update Now sets the same files up on its way). `needs_terminal` is a box to read, with nothing to tap. The pretend agent (`--fake`) runs the real steps, then `Agent.go_away`: its event streams end and the Guard holds every request for two seconds, as a restart looks to a page (rather than a 503, which an `EventSource` never retries) |

## Consequences

- No schema change. New in Sunroom Screen: `files.py`, `setup_files.py` (`Machine`, the pieces,
  `run`, `Report`, `SYSTEM_PART_SINCE`), the `setup` command, `Agent(setup=…)` and
  `Agent.setup_report`; `config.set_values`, `STEPS`, `CONFIG_VERSION`, `migrate`, `migrated`;
  `local.program_command` and `program_environment`; the Windows registry's `user_value`;
  `uninstall.remove_run_value`. The release's check names `sunroom_kiosk/files/sunroom-kiosk-root`.
- New in the root helper: `version`, `apply-system` (`fetch_sums`, `screen_settings`,
  `packages`, `add_to_group`, `install_file`); `kiosk/files/packages/pi.txt` and `linux.txt`. In
  Sunroom Screen: `platform.SystemReport`, `Platform.root_helper_version`, `apply_system` and
  `install_command` (Linux's `INSTALL_COMMAND`), `setup_files.needs_terminal`,
  `Agent.needs_terminal`.
- `local.py`'s LaunchAgent uid comes from `platform.base.user_id`, which pyright on Windows
  understands (the kiosk CI job had been red on that since 0.15.0).
- The update (T12): `apply.run_setup`, `restart_service`, `note_progress`; `apply()` takes
  `setup` and `force`; `Updater.reinstall`, `relay`, `last_result`, `seen`, `setup_said`,
  `kept_wheel`, `rebooted_for`, `note_rebooted`; `Agent.finish_update` and `finishing`;
  `ScreenUpdateOut.last_result` (`ScreenUpdateResultOut`) and `needs_terminal`; the routes
  `POST /api/screen/reinstall` and `POST /api/screen/update/seen`; `sunroom-kiosk update --force`.
  The agent's API has 21 paths.
