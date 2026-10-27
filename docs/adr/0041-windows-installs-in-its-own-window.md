# ADR 0041: Windows installs in the PowerShell window the line is typed in

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

- The owner ran the documented line on a Windows computer, typed in PowerShell:
  `powershell -ExecutionPolicy Bypass -c "irm …/kiosk/install.ps1 | iex"`. It failed at once
  with "Program 'powershell.exe' failed to run: Access is denied", and Microsoft Defender said it
  had found threats.
- That error comes from the PowerShell the person typed in, failing to *start* the second one,
  so nothing of `install.ps1` was downloaded or run. Other projects' installers with the same
  line, reported in 2025 and 2026, show what Defender does: its machine-learning detections
  (`Trojan:Win32/Commando.A!ml`, `Trojan:Win32/ClickFix.R!ml`) block a PowerShell started with a
  command line that downloads a script and runs it, and Protection history names that command
  line (`CmdLine`) as the threat. It's the shape of the "ClickFix" attacks, which have people
  paste such a line into the Run box. The same `irm … | iex` typed straight into the window
  starts no process, and the one report that tried it found it ran with no detection.
- `install.ps1` started a second PowerShell itself: uv's installer, downloaded to the temp
  folder, run with `powershell -ExecutionPolicy Bypass -File`. That's the same kind of command
  line, so it could have been stopped next.
- The line's `-ExecutionPolicy Bypass` did nothing for `iex`: the policy governs script files,
  not text run with `iex`. Run in the person's own window, the installer runs under that
  window's policy instead, which is Restricted on Windows unless someone changed it. On Windows
  PowerShell 5.1, `Get-FileHash` and `Expand-Archive` are functions from script modules.

## Decision

| Question | Decision |
|---|---|
| The line | `irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 \| iex`, typed in a PowerShell window (Start, then PowerShell). Never `powershell -c "…"`, and never the Run box. With options, the script block from ADR 0037 is typed in the window too: `& ([scriptblock]::Create((irm …))) -Url …`. A saved copy still runs with `powershell -ExecutionPolicy Bypass -File install.ps1`. The goodbye prints the window's form for `-Uninstall`. |
| No second PowerShell | `install.ps1` starts no PowerShell and runs no script of anyone else's. **uv comes from its own release:** the Windows zip for the computer's architecture (`x86_64`, `aarch64` or `i686`, read from Windows, since an Intel PowerShell on an Arm computer reports AMD64 for itself), checked against SHA-256 sums written beside `$UvVersion` before it is unpacked into `%USERPROFILE%\.local\bin`. |
| A Restricted policy | Hashes and the zip use .NET (`SHA256`, `ZipFile`), not `Get-FileHash` or `Expand-Archive`. CI runs the plan the way people run the line: in the window, under `-ExecutionPolicy Restricted`. |
| `just kiosk-serve` | Its Windows line is `irm http://<this computer>:8765/install.ps1 \| iex`, and it runs the checkout's `install.ps1` in that same window, as a script block. |

## Consequences

- The line Defender stops no longer appears in the docs or the installers' messages. Someone who
  copies an old one gets "Access is denied" and a threat alert, with nothing installed; KIOSK.md
  says what to type instead.
- Defender's detection is machine learning, so the bare line or the script's own text could be
  flagged one day too. A lasting answer is an installer people download and open: signed (for
  example with Azure Artifact Signing), or from winget. That is the owner's call and isn't
  decided here. Meanwhile, Microsoft's submission page for software developers takes reports of
  a wrong detection.
- uv installed from its zip has no install receipt, so `uv self update` refuses to run. Sunroom
  never uses it: Sunroom Screen updates itself with `uv tool install`.
- A new `$UvVersion` needs its three sums too, from the `.sha256` files of that uv release.
- The uninstaller said "remove it with: uv self uninstall", a command uv doesn't have. It now
  points at uv's own guide.
- Changes part of ADR 0035 (uv from astral.sh's installer on Windows) and ADR 0037 (the
  documented line and its options).
