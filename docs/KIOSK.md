# The kitchen screen: Sunroom Screen

How `kiosk/install.sh` turns a Raspberry Pi (or another Linux computer, or a Mac; Windows has
`install.ps1`) into Sunroom's wall screen, what it changes, how the screen sleeps and dims at night, and what to do when something
looks wrong. The design is in [PLAN §13](PLAN.md#13-setup-deployment-and-the-raspberry-pi-kiosk)
and [ADR 0035](adr/0035-m7-sunroom-screen.md); what to buy, and the hardware it has been tried on,
is in [HARDWARE.md](HARDWARE.md).

The screen runs **Sunroom Screen**, a small program the installer puts on it. It opens Sunroom
full screen in the browser and keeps it there, puts the screen to sleep and dims it on Sunroom's
schedule, finds Sunroom on your network, shows its own pages while it has no Sunroom or can't
reach it, and gives the wall **Settings → This Screen** (its Wi-Fi, address, rotation, updates,
Restart and Shut Down).

## What you need

- A Raspberry Pi 4 or 5 with Raspberry Pi OS (64-bit) **with desktop**, Bookworm or Trixie,
  written with Raspberry Pi Imager. In Imager's settings, set the hostname (for example
  `sunroom`), your user, Wi-Fi, the time zone, and turn on SSH.
- A touch screen: HDMI for the picture and a USB cable for touch (without it, the picture shows
  but taps do nothing).
- The official power supply. Don't power a portable monitor from the Pi's USB ports.

Another Linux computer with a desktop (and systemd), a Windows computer or a Mac can be the
screen too, with one command and nothing to install first; see their sections below.

## Install

Sign in to the Pi (at its desktop, or `ssh` in) and run one of these as your normal user, not
root; it asks for `sudo` itself.

| You want | Command |
|---|---|
| The screen on this Pi; Sunroom runs elsewhere | `curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh \| bash` |
| Sunroom and the screen, both on this Pi | the same, ending `\| bash -s -- --with-sunroom` |
| Only Sunroom, no screen (Pi OS Lite) | the same, ending `\| bash -s -- --server-only` |

The installer finishes by saying what's next (with Sunroom on the Pi, the phone address and a QR
code), then offers to restart.

The screen looks for Sunroom on your network after the restart and lists what it finds: tap
**Use This Sunroom**, or type the address you open on a phone and tap **Check Address**.
`--url https://calendar.example.com` (or `http://192.168.1.20:8080`) gives it the address and
skips the search. Then the screen shows a six-character code: on a phone signed in to Sunroom,
open **More → Pair a display** and type it. A Sunroom that isn't set up yet shows **Set Up
Sunroom** instead: **Set Up Here** sets the household up on the screen itself, on its keyboard,
and the screen pairs itself (ADR 0039); or scan its QR code and set it up on a phone.

Earlier installers put Sunroom and the screen on a Pi when run with no option (ADR 0037 changed
that). A Pi set up that way, or with `--server-only`, keeps Sunroom when the installer runs again
with no option (it says so); `--display-only` makes it the screen alone.

Other options (`--help` lists them all):

- `--dry-run` says what the installer would do on this computer, and changes nothing.
- `--rotate 90|180|270` turns the picture for a screen mounted on its side (90 = left, 180 =
  upside down, 270 = right), and touch with it. **Settings → This Screen → Rotation** changes it
  later.
- `--force-hdmi 1920x1080` keeps the HDMI output on at that size even when the monitor is off at
  startup (see "Blank after a restart" below).
- `--output HDMI-A-2` picks the connector when two are in use.
- `--brightness auto|ddc|sysfs|none` picks how the screen is dimmed in the evening (see "Sleep
  and dimming" below); `auto` is right for most screens.
- `--no-screen-helper` leaves the screen itself on all night; the page still goes black or dim.
  It's for monitors whose touch stops working while the screen is off.
- `--version X.Y.Z` runs that Sunroom version on the Pi (with `--with-sunroom`) instead of the
  newest. The screen's own software is always the installer's version.
- `--x11` uses the older X11 desktop instead of labwc.

Running the installer again is safe: it keeps what is already right (the address the screen
found, its pairing, its Updates choice) and replaces only its own files. Its log is
`~/.local/state/sunroom-kiosk/install.log`.

## What it changes

- Installs `chromium`, `curl`, `jq`, `qrencode`, `python3` and the screen tools for the desktop
  (`wlr-randr` and `wlopm` on labwc, `x11-xserver-utils` and `unclutter` on X11) when they are
  missing.
- Without `--display-only`: Docker (from `get.docker.com`), and Sunroom in
  `/opt/sunroom/docker-compose.yml` with its data in the `sunroom_data` volume, optional settings
  in `/opt/sunroom/.env`, and `/opt/sunroom/update.sh`; and
  `/etc/avahi/services/sunroom.service`, which lets Sunroom screens on the network find this Pi
  by themselves (`--purge` removes it with Sunroom).
- **Sunroom Screen:** `uv` in `~/.local/bin` when there is no uv yet (a pinned version, from its
  makers' site), then Sunroom Screen itself with uv, from the same Sunroom release as the
  installer on GitHub, checked against the release's `SHA256SUMS` before anything installs it.
  uv gives it its own Python, apart from the system's. Its command is `~/.local/bin/sunroom-kiosk`;
  the copy it was installed from stays in `~/.local/share/sunroom-kiosk/wheels`, for updates to
  fall back on.
- The user service `sunroom-kiosk.service` (started again 3 seconds after it fails), which the
  desktop starts when it logs in. Sunroom Screen runs the browser (and restarts it at about 04:00
  to give back memory), the screen's sleep and brightness, and its own pages on
  `http://127.0.0.1:7800`, which only this computer can open. Its settings are in
  `~/.config/sunroom-kiosk/config`; the browser profile, which holds the screen's pairing, is in
  `~/.config/sunroom-kiosk/profile`.
- One root helper, `/usr/local/sbin/sunroom-kiosk-root`, which `/etc/sudoers.d/sunroom-kiosk`
  lets your user run without a password, and nothing else: it writes the browser's policy (on
  any Linux screen since ADR 0038), and on a Pi installs the Pi's own updates and runs
  `/opt/sunroom/update.sh`. It checks what it's asked.
- The browser's policy, `/etc/chromium/policies/managed/sunroom-kiosk.json` (Google Chrome's is
  under `/etc/opt/chrome`, Edge's under `/etc/opt/edge`): no sign-in, password, translation or
  default-browser prompts, and Sunroom's page may reach Sunroom Screen on this computer without a
  prompt nobody is there to answer (Chrome's Local Network Access). Sunroom Screen rewrites it
  when the address changes.
- Logs in to the desktop by itself and turns off screen blanking (`raspi-config`).
- For the brightness, depending on the screen: `ddcutil`, `i2c-dev` loaded at every start
  (`/etc/modules-load.d/sunroom-kiosk-i2c.conf`) and your user in the `i2c` group, for a monitor
  with DDC/CI; or a udev rule that lets the `video` group dim the backlight and switch it off
  (`/etc/udev/rules.d/90-sunroom-kiosk-backlight.rules`) and your user in `video`, for a panel
  with a backlight. Raspberry Pi OS's first user is usually in both groups already.
- On labwc: a block between `# >>> sunroom-kiosk` and `# <<< sunroom-kiosk <<<` in
  `~/.config/labwc/autostart`, and a window rule in `~/.config/labwc/rc.xml` that hides the
  pointer and gives Chromium real touch events, and turns touch with a turned picture (a copy
  from before is kept as `rc.xml.sunroom-backup`). On X11:
  `~/.config/autostart/sunroom-kiosk.desktop`.
- Turns off Wi-Fi power saving (`/etc/NetworkManager/conf.d/zz-sunroom-kiosk-wifi.conf`), which
  otherwise drops live updates.
- Turns on `systemd-time-wait-sync`, so the clock is set from the internet before it's relied on.
  Sunroom Screen also waits up to a minute for it, and the screen shows the server's time anyway.
- With `--force-hdmi`: two options in the kernel command line (`cmdline.txt`), with the original
  kept beside it.

`~/.local/state/sunroom-kiosk/install-state` records the changes to shared files, so the
uninstaller can put them back. The files the installer copies are in `kiosk/files/`.

### A Pi set up before Sunroom 0.13.0

Run the installer again with the options you used the first time (for example `--display-only
--url …`), then let it restart the Pi. It replaces the old launcher, the screen helper and their
services with Sunroom Screen (the log says so), and keeps the address and the pairing. `update.sh`
alone doesn't do this: it updates Sunroom, not the Pi's screen setup.

## Another Linux computer

On a Linux computer that isn't a Raspberry Pi, sign in to its desktop as the person the screen
runs for, and in a terminal run the same command:

```sh
curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
```

It sets up the screen only, and needs systemd and a desktop. **The browser:** it uses Chromium,
Google Chrome or Microsoft Edge when one is installed, and otherwise installs one with `sudo`:
the system's own Chromium (Debian with apt, Fedora with dnf, openSUSE with zypper, Arch with
pacman), or Google Chrome from Google where the system's Chromium is a snap (Ubuntu). Google's
package adds Google's software source, so the system's own updates keep Chrome up to date. A
snap's browser is never used: its sandbox can't open the screen's profile or read its policy.

Then it installs uv and Sunroom Screen as above, the user service, and
`~/.config/autostart/sunroom-kiosk.desktop`, which starts it when you sign in. With `sudo` it
writes the browser's policy and puts in the root helper (below), which lets Sunroom Screen
rewrite that policy whenever the screen's address changes, so the browser never asks on the
screen to let Sunroom reach Sunroom Screen (without `sudo`, it asks once). Nothing else on the
computer changes. When the desktop is signed in, the
one it ran on or, over `ssh`, the one this user is signed in to, it starts the screen at once.
The computer's own settings turn and dim its screen; This Screen has **Quit Sunroom Screen**,
which closes it until the next sign-in. Before the screen is paired, `systemctl --user stop
sunroom-kiosk` in a terminal does the same.

## Windows

On Windows 10 or 11, sign in as the person the screen runs for, open PowerShell (Start, then type
PowerShell), and run this in its window:

```powershell
irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 | iex
```

Type it in the window itself. Wrapped in a second PowerShell (`powershell -c "…"`), or typed in
the Run box, Microsoft Defender stops it with "Access is denied" and says it found a threat: a
PowerShell started with a command that downloads a script and runs it is how "ClickFix" attacks
begin (ADR 0041). The installer itself starts no other PowerShell.

It needs no administrator and installs no service. It installs uv (uv's own zip from GitHub,
checked against its checksum) and Sunroom Screen (the same release and checks as above) for this
user, puts **Sunroom Screen** in the Startup folder (it starts at sign-in with no console
window), and starts it: Microsoft Edge full screen, or Google Chrome when there's no Edge.
Sunroom Screen writes the browser's policy for this user itself
(`HKEY_CURRENT_USER\Software\Policies\…`), so Sunroom reaches it without a prompt.

Edge runs full screen on the screen's own profile, not in Edge's kiosk mode: that mode is an
InPrivate session, which used to forget the pairing at every restart (ADR 0040). F11 or Esc can
take it out of full screen; it goes back by itself within half a minute.

Its settings, browser profile (the pairing) and log are in `%LOCALAPPDATA%\sunroom-kiosk`. Windows
joins Wi-Fi, turns the picture and sets the brightness itself, so This Screen has **Open Network
Settings** instead of Wi-Fi, no Rotation, and the page dims itself in the evening. **Quit Sunroom
Screen** closes it until the next sign-in. Updates work as on a Pi.

With options (`-Url https://calendar.example.com`, `-DryRun`, `-AgentWheel FILE`, `-Uninstall`),
run the same download as a script block, in the PowerShell window too:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1))) -Url https://calendar.example.com
```

or save the file and run `powershell -ExecutionPolicy Bypass -File install.ps1 -Url …`.
`-Uninstall` takes it off again, asking before it deletes the pairing; uv stays. The installer
ends by printing the exact command that removes it.

## A Mac

On a Mac, sign in as the person the screen runs for, and in Terminal run the same command:

```sh
curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
```

It needs no administrator. With no Google Chrome, Chromium or Microsoft Edge in `/Applications`
or `~/Applications`, it downloads Google Chrome from Google, checks Google's signature on it,
and puts it in `/Applications` (in `~/Applications` for an account that can't write there).
Then it installs uv and Sunroom Screen (the same release and checks as above) for this user, and
a LaunchAgent, `~/Library/LaunchAgents/app.sunroom.kiosk.plist`, which starts it at sign-in and
again if it fails, and starts it now when the Mac is signed in (before the screen is paired,
`launchctl bootout gui/$(id -u)/app.sunroom.kiosk` in Terminal closes it until the next
sign-in). Sunroom Screen sets the browser's policy in its own preferences (`defaults`, this user
only), keeps the display awake
while the household's times say on (`caffeinate`) and lets it sleep at night (`pmset
displaysleepnow`); the page dims itself in the evening. The first Restart or Shut Down asks once
whether Sunroom Screen may control System Events. **Quit Sunroom Screen** in This Screen closes
it until the next sign-in. Its log: `~/Library/Logs/sunroom-kiosk.log`. `--url`, `--dry-run` and
`--agent-wheel` work as on Linux; `bash ~/.local/share/sunroom-kiosk/uninstall.sh` takes it off
(Google Chrome stays).

## Sleep and dimming

Set the times in Sunroom, on a phone or on the screen: **Settings → Display → Sleep**.

- **Sleep at night**, from and until a time. **While asleep** shows either a **Dim clock** (the
  time on black, with the screen turned down low) or **Screen off** (black, with the screen itself
  switched off).
- **Dim in the evening**: from a time until sleep starts, the screen is less bright (**A little**,
  **Half** or **Low**).
- **A tap wakes it** for 2 minutes, at full brightness.

The page does the part a browser can: the black screen, the dim clock, and on screens Sunroom
Screen can't dim, a darker page in the evening. Sunroom Screen does the rest: it asks Sunroom
what the screen should be doing, switches the screen off and on, and sets its brightness. A tap
on the dark screen still reaches the page (most touch monitors keep their touch working while the
picture is off), the page tells Sunroom, and moments later the screen comes back on. Sunroom
Screen opens `/display?dimmer=screen` when it sets the brightness and `/display?dimmer=page` when
it can't, so the page and the screen never both dim.

### How the brightness is set

The installer's `--brightness` decides; what it finds is saved in `~/.config/sunroom-kiosk/config`
and checked again each time Sunroom Screen starts.

| `--brightness` | For | How |
|---|---|---|
| `auto` (the default) | Any screen | `sysfs` when the screen has a backlight the Pi controls, else `ddc` when the monitor answers, else `none` |
| `ddc` | HDMI monitors with DDC/CI (many 21–24" touch monitors) | `ddcutil` sets the monitor's own brightness over the HDMI cable |
| `sysfs` | Raspberry Pi Touch Display and other panels on the DSI connector | the backlight in `/sys/class/backlight`; at night only the backlight goes off, so the touch panel keeps working |
| `none` | Screens that misbehave with the others | the screen keeps its own brightness; the page darkens itself in the evening |

`sunroom-kiosk screen --method` prints what it uses here (`ddc`, `sysfs` or `none`), and so does
its log when it starts. Many monitors come with DDC/CI switched off: look for "DDC/CI" in the
monitor's own menu, turn it on, then run the installer again (it looks for the monitor while
installing, so leave the monitor on). `sudo ddcutil detect` shows whether the Pi can reach it.
Portable USB-C monitors rarely have DDC/CI, so they get `none`.

To switch the screen off, Sunroom Screen uses `wlopm` on labwc (or `wlr-randr` when `wlopm` is
missing; a tap may not wake the screen then, so install it with `sudo apt install wlopm`), and
`xset dpms force off` on X11. With `sysfs`, only the backlight is switched off.

### When touch stops working while the screen is off

A few monitors switch their touch off together with the picture, so a tap can't wake them before
the morning. Run the installer again with `--no-screen-helper`: at night the page still goes black
or shows the dim clock, and the screen itself stays on (**Dim clock** suits these screens best).

### If Sunroom can't be reached

Sunroom Screen asks again after 2 seconds, then waits longer each time, up to a minute. After
about half a minute without an answer it switches the screen on, and when it stops, or is
removed, it leaves the screen on at full brightness: a dark screen that can't wake up is worse
than a lit one. As soon as Sunroom answers again, the screen follows the schedule again.

### Its log

`journalctl --user -u sunroom-kiosk` has one line per change, for example:

```text
Following the screen's sleep times from http://localhost:8080; brightness through DDC/CI on I2C bus 20.
Brightness 40%: evening dim.
Screen off: sleep time.
Screen on: tapped awake for 2 minutes.
```

## Sunroom on this computer

The screen's first page asks **Where will your family's Sunroom run?** (ADR 0038). **On This
Computer** → **Run Sunroom Here** sets Sunroom up on the computer the screen runs on, so it is the
family's Sunroom as well as its kitchen screen. **Setting Up Sunroom** shows how far it is
("Downloading Sunroom… 40%", "Installing Sunroom…", "Starting Sunroom…"; the first time takes a
few minutes), then the screen opens Sunroom's own **Set Up Sunroom**: **Set Up Here** sets the
household up right there, on the screen's keyboard, and the screen pairs itself; its last page
has the QR code that phones scan to join (ADR 0039). Or scan the QR code beside it and set up on a
phone. If Setting Up Sunroom stops, the page says why, with **Try Again**.

- **What it is:** Sunroom as a program for the screen's user, not Docker: Sunroom Screen installs
  this release's `sunroom` wheel with uv, as it installs itself, held to the release's versions
  of everything Sunroom uses (its constraints file), checked against `SHA256SUMS`. A Pi on Sunroom
  OS is the exception: there it starts the Docker setup the card carries, as before.
- **Which computers:** a Raspberry Pi with 64-bit Raspberry Pi OS, other 64-bit Linux computers,
  Macs with Apple silicon, and Windows (on ARM, through an x64 Python). An Intel Mac shows only
  **On Another Computer**: a library Sunroom needs no longer ships for it.
- **Where the family's data is:** `~/.local/share/sunroom` on Linux, `~/Library/Application
  Support/Sunroom` on a Mac, `%LOCALAPPDATA%\Sunroom` on Windows; for that user only. Backups go
  into its `backups` folder every night, as on any Sunroom; Settings → Backup downloads a copy.
- **What keeps it running:** on Linux the user service `sunroom.service`, which also runs from the
  computer's start with nobody signed in (its log: `journalctl --user -u sunroom`); on a Mac the
  LaunchAgent `~/Library/LaunchAgents/app.sunroom.server.plist`, from sign-in (its log:
  `~/Library/Logs/sunroom.log`); on Windows Sunroom Screen starts it at sign-in and again whenever
  it stops answering (its log: `%LOCALAPPDATA%\Sunroom\sunroom.log`). Each keeps the computer
  from going to sleep while Sunroom runs, and the screen still sleeps on its schedule. A Linux
  desktop may refuse (Sunroom Screen's log says so): then turn off automatic suspend in its power
  settings, so phones reach Sunroom at night.
- **Phones:** Sunroom answers on port 8080 (or the next free one), at `http://<computer>.local:8080`
  on a Mac and on Linux with avahi, else at the computer's numbered address; the QR codes on Set
  Up Sunroom and on setup's last page have it. Sunroom Screen announces it on the network, so other screens find it too. On a Mac
  or Windows the first start may ask whether Sunroom may accept connections: choose Allow, or
  phones can't reach it.
- **Updates:** it stays at Sunroom Screen's version: when Sunroom Screen updates itself, Sunroom
  follows. This Screen's **Update Sunroom Too** installs the newest; a version that doesn't
  answer within five minutes is put back.
- **The household password, lost:** `DATA_DIR=~/.local/share/sunroom ~/.local/bin/sunroom
  reset-password` (the data folder above for a Mac or Windows).
- **Removing it:** the screen's uninstaller leaves Sunroom running, with the family's data, unless
  you add `--purge` (it asks first); on Windows `-Uninstall` stops and removes it, and keeps its
  data folder.

## Letting screens find a Sunroom on a NAS or server

A Sunroom screen that isn't told an address looks for Sunroom on its network: it asks every
address on its own network on ports 8080, 80 and 443, which finds a server set up as
[DEPLOY.md](DEPLOY.md) shows. It also listens for Sunrooms that announce themselves, which an
all-in-one Pi does. To announce one on another Linux machine that runs avahi, put this in
`/etc/avahi/services/sunroom.service` (with the port you publish); it's optional:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Sunroom on %h</name>
  <service><type>_sunroom._tcp</type><port>8080</port></service>
</service-group>
```

A reverse proxy that picks a site by its name isn't found either way: type its address on the
screen instead.

## Every day

- **The screen's own software (Sunroom Screen) updates itself** when Settings → This Screen →
  Updates says Install overnight, as every screen starts (Off updates it only when asked): at the
  start of the household's sleep hours (03:30 without them) it asks GitHub for the newest
  version, downloads it, checks it against the release's checksums and starts it; if the new
  version doesn't start within a minute, the one before comes back and This Screen says so.
  **Update Now** there does the same at once; `sunroom-kiosk update` on the Pi says whether
  there's one. On an all-in-one Pi, This Screen's **Update Sunroom Too** updates
  Sunroom itself, as `update.sh` does.
- **Update Sunroom on the Pi:** `sudo /opt/sunroom/update.sh` (or `sudo /opt/sunroom/update.sh
  0.2.0` for exactly that version, which is also how to go back). Your family's data stays.
- **The screen's log:** `journalctl --user -u sunroom-kiosk`; **what it says about itself:**
  `sunroom-kiosk status`.
- **Restart it:** `systemctl --user restart sunroom-kiosk` (the screen comes on while it
  restarts), or **Restart** in This Screen, which restarts the whole Pi.
- **Remove the screen setup:** `bash ~/.local/share/sunroom-kiosk/uninstall.sh`. It asks before
  deleting the browser profile (and with it the pairing). `--purge` also deletes Sunroom and all
  its data from the Pi. The packages the installer added, the browser among them, stay.

## Trying a change before a release

From a checkout, `just kiosk-serve` builds Sunroom Screen's wheel and Sunroom's own (`just
server-build`) and serves this checkout's installers with them on port 8765, then prints one line for a Linux computer or a Mac (`curl -fsSL
http://<this computer>:8765/install.sh | bash`) and one for Windows (`irm … | iex`). Run that
line on the computer or virtual machine to try: it installs from this checkout and those
wheels (On This Computer uses the server wheel it was given), taking nothing from GitHub. Options go after `bash -s --`, as with the real one. Ctrl+C stops it.

By hand: `just kiosk-build` makes the wheel in `kiosk/agent/dist/`. Copy the `kiosk` folder and
that wheel to the Pi, then run the installer from the copy with `--agent-wheel <the wheel>` (and
`--server-wheel` for Sunroom's own, from `just server-build`): it uses the files next to it and
those wheels instead of the release's. Either way the wheel isn't
checked against a release, so use it only for testing. `--dry-run` shows the plan first.

## When something looks wrong

**The screen says it can't reach Sunroom.** Sunroom Screen tries again every 10 seconds and goes
back to Sunroom by itself the moment it answers. On a Pi that runs Sunroom, `sudo docker logs
sunroom` says why it isn't up; otherwise open the address on a phone. **Change Address** on that
page finds or takes another one. A Sunroom the screen found by itself that moved to a new address
is found again.

**The desktop picture stays.** Sunroom Screen isn't running: `journalctl --user -u
sunroom-kiosk` says why (for example, no browser found).

**Windows says "Access is denied", and Microsoft Defender found a threat.** The install line ran
inside a second PowerShell (`powershell -ExecutionPolicy Bypass -c "irm … | iex"`, as it read
before ADR 0041) or from the Run box, and Defender stopped that PowerShell before it started.
Nothing was installed, and the alert can be dismissed. Open PowerShell and type the line in its
window instead (see Windows, above).

**The screen shows a code again.** Its sign-in was ended: a new household password, a new secret
key, a restore, or **Unpair** in Settings → Devices. Pair it again from a phone. A restart, an
update or Quit keeps the pairing, straight after pairing too: the browser saves it the moment the
screen is paired (ADR 0040). A Linux screen set up before this saves it within half a minute
until the install command is run again.

**The screen doesn't go dark at night.** Check the times and **While asleep** in Settings →
Display → Sleep (**Dim clock** keeps the screen on, turned down). Then read its log: "No answer
from Sunroom" means the screen can't reach its address; a line ending in "didn't work" names the
command that failed.

**The evening dim makes the page darker but not the screen.** Sunroom Screen found no way to set
the brightness (`sunroom-kiosk screen --method` says `none`). Turn on DDC/CI in the monitor's menu
and run the installer again, or keep the page's dimming.

**A tap doesn't wake the dark screen.** The monitor's touch sleeps with its picture: see "When
touch stops working while the screen is off" above.

**Taps land in the wrong place on a turned screen.** Sunroom Screen tells labwc to turn touch
with the picture (`mapToOutput` on its `<touch>` lines in `~/.config/labwc/rc.xml`). If a touch
screen isn't matched that way, take `mapToOutput="…"` out of those lines and add a calibration
matrix for touch devices inside `<openbox_config>` (or `<labwc_config>`), then restart the Pi:

```xml
<libinput>
  <device category="touch">
    <calibrationMatrix>0 -1 1 1 0 0</calibrationMatrix>
  </device>
</libinput>
```

That matrix is for a turn of 90; if taps come out mirrored, use `0 1 0 -1 0 1` instead (the one
for 270). For 180 it is `-1 0 1 0 -1 1`. Changing the rotation in This Screen puts Sunroom
Screen's own settings back, so check again after one.

**The rotation doesn't stick.** If you once saved a layout in Raspberry Pi's **Screen
Configuration**, the desktop may apply it after Sunroom Screen's. Turn the screen in one place
only: This Screen → Rotation.

**Blank after a restart, or the screen wakes right after going dark.** Some monitors that are off
when the Pi starts are never detected. Run the installer again with `--force-hdmi 1920x1080` (use
your screen's size).

**The pointer stays visible.** Sunroom's page hides the pointer itself three seconds after the
mouse stops, and at once when the screen is touched; moving the mouse brings it back. labwc 0.8.4
and, on X11, `unclutter` keep it hidden before the page loads; if you see it then, bring the Pi up
to date with `sudo apt update && sudo apt full-upgrade`.

**`sunroom.local` doesn't open on a phone.** Use the numbered address the installer printed.
Phones on a VPN or on mobile data can't see `.local` names, and some routers block them.

**"This Pi's desktop uses Wayfire".** Older Bookworm images start Wayfire; the installer prints
the one line that switches to labwc.

**A keyboard is plugged in.** Alt+F4 closes the browser; it comes back by itself within a few
seconds. It's best not to leave a keyboard attached.
