# Hardware for the kitchen screen

What to buy for Sunroom's wall screen, and why. If everything runs on one Raspberry Pi (path a
in the [README](../README.md#install)), that Pi also keeps the family's data. If Sunroom runs on
another computer (path b), the Pi only shows the screen. [KIOSK.md](KIOSK.md) covers installing
and running it. The product details here were checked against the makers' own pages on
2026-10-08.

## The short version

- A **Raspberry Pi 5 with 4 GB**.
- The official **27 W USB-C power supply**.
- The **Active Cooler**, because a Pi behind a monitor gets warm.
- An official **Raspberry Pi SD card**, 32 GB or more, or an SSD (see *Storage*).
- A **21.5 to 24 inch touch monitor** with HDMI, a USB touch cable and VESA 100 holes on the back.
- A **micro HDMI to HDMI cable**: the Pi's video sockets are the small micro HDMI kind.
- A **VESA wall mount**, and a way to fix the Pi to the back of the monitor.

## The computer

| Raspberry Pi | Sunroom and the screen on one Pi | Only the screen (Sunroom runs elsewhere) |
|---|---|---|
| Pi 5, 4 GB | Recommended | Recommended |
| Pi 5, 8 GB or 16 GB | Works; more memory than it needs | Works; more than it needs |
| Pi 4, 4 GB or 8 GB | Fine | Fine |
| Pi 5 or Pi 4, 2 GB | No | Fine |
| 1 GB models, Pi 3, Pi Zero 2 W | No | No |

- **Why a Pi 5:** its browser is the quickest, which the week board, the screensaver's fades and
  the moment a chore is done all show. It can take a fast SSD on the M.2 HAT+. It's made for
  the 27 W supply, and it runs best with active cooling, which matters in the closed space
  behind a monitor.
- **A Pi 4** is fine. The browser slowly collects memory over days; the screen setup restarts it
  at about 04:00 every night, which keeps a 4 GB Pi 4 smooth. It uses the 15 W USB-C supply.
- **Older Pis** don't have the memory for a modern browser and a week of events.

## Storage

This matters when Sunroom runs on the Pi: the database, the nightly backups and the photos all
live there. A Pi that is only the screen keeps nothing but the browser and its pairing, and any
decent card does.

- **An SD card** is fine to start: Raspberry Pi's own cards (32, 64 or 128 GB, class A2) are
  fast in a Pi 5. 32 GB is plenty for Sunroom; photos take the most room, so choose 64 GB if
  the family will add a lot.
- **An SSD is better**: on a Pi 5, an NVMe SSD on the M.2 HAT+ (Raspberry Pi's SSD Kit has both);
  on a Pi 4 or 5, an SSD in a USB case. Starting the Pi from an SSD takes a few extra steps,
  in Raspberry Pi's documentation.
- **Wear is not the worry.** Sunroom's database doesn't force each change onto the card the
  moment it happens, so it's gentle on cards. The real risk to any card is the power going off
  while the Pi is writing, for example in the middle of a system update. Use the official power
  supply, and keep a copy of the family's data off the Pi (Settings → Backup, and
  [RESTORE.md](RESTORE.md)).

## Power

- **Use the official supply:** 27 W for a Pi 5, 15 W for a Pi 4. With a weaker supply, a Pi 5
  allows its USB sockets only 600 mA between them.
- **Never power a monitor from the Pi's USB sockets.** A portable monitor comes with its own
  power brick: use it. The touch cable itself draws very little and is fine on the Pi.
- The screen needs two power points close by (the monitor's and the Pi's), or a power strip.

## The screen

| | Portable touch monitor | Desktop touch monitor (recommended) | Raspberry Pi Touch Display 2 |
|---|---|---|---|
| Size | 15.6 inches | 21.5 to 24 inches | 5, 7 or 10 inches |
| Picture | HDMI (often a mini HDMI socket on the monitor) | HDMI | A ribbon cable to the Pi's display socket |
| Touch | A separate USB cable | A separate USB cable (often USB-B) | The same ribbon cable |
| Power | Its own brick | Its own power cable | From the Pi |
| Mounting | Few have VESA holes: a stand, or a mount made for it | VESA 100, with the Pi on the back | A case or frame made for it |
| Sunroom can change its brightness | If it supports DDC/CI | Often, through DDC/CI | Yes, through its backlight |

- **Size.** A family's week has to read from across the kitchen: 21.5 inches or more. A 15.6
  inch screen reads well at arm's length, less so from the doorway. Desktop touch monitors are
  sold for offices and shop counters; ViewSonic's TD series is one example.
- **The Touch Display 2.** The 5 and 7 inch models (720 × 1280) are too small for a family's
  week. The 10 inch (1200 × 1920, tall) suits a hallway or Sunroom's portrait layout, and it
  needs a Pi 5.
- **Resolution.** Sunroom is designed and tested at Full HD: 1920 × 1080, or 1080 × 1920 turned on
  its side. A bigger resolution only makes everything smaller.
- **Touch without drivers.** Look for "works with Linux" or "Raspberry Pi" in the description;
  touch has to work as soon as it's plugged in.
- **One cable won't do.** The Pi's USB-C socket only takes power in. The single USB-C cable that
  carries a laptop's picture to a portable monitor can't do that from a Pi: use HDMI for the
  picture and USB for touch.
- **Touch while the screen sleeps.** At night Sunroom can switch the screen off (Settings →
  Display → Sleep, "Screen off"). A tap wakes it only if the monitor keeps touch working while
  its picture is off. Most USB touch monitors do; for one that doesn't, see "When touch stops
  working while the screen is off" in [KIOSK.md](KIOSK.md).
- **Brightness.** Sunroom can dim the screen in the evening (Settings → Display → Sleep, "Dim in
  the evening"). On a monitor with DDC/CI (switch it on in the monitor's own menu if it has the
  option) and on the Touch Display 2, the Pi turns the real backlight down. Otherwise Sunroom
  darkens the picture itself. "How the brightness is set" in [KIOSK.md](KIOSK.md) explains how
  the installer chooses.
- **Speakers** aren't needed: Sunroom's sounds are off by default.

## Cables and mounting

- **A micro HDMI to HDMI cable** (or micro HDMI to mini HDMI, for a portable monitor with the
  small socket). Plug it into the Pi's socket marked HDMI0.
- **Right-angle adapters** where cables leave the back of a screen that sits flat on the wall.
- **The USB touch cable**, from the monitor to the Pi, with a label on it. Without it the picture
  shows but taps do nothing.
- **A VESA 100 wall mount** or a short arm. Fix the Pi to the back of the monitor with a VESA
  plate or a case with VESA holes, and keep its SD card (or SSD) reachable without taking the
  screen off the wall.
- **Air around the Pi.** Don't shut it in a closed box behind the screen.
- **Network.** A network cable is steadiest if one reaches. Wi-Fi works too: the installer
  switches off the Wi-Fi power saving that would otherwise interrupt live updates.
- **No keyboard left attached.** A keyboard's shortcuts can close the browser (it comes back by
  itself within seconds).
- **Height.** Hang it where the children can reach the bottom of the screen.

## An old tablet instead

A spare tablet can be the wall screen. Sunroom then runs on another computer (path b or c in
the README), and the tablet opens `http://<server>:8080/display` in a browser. Pairing is the
same: the tablet shows a code, and you type it on a phone under **More → Pair a display**.

- **Android:** Fully Kiosk Browser, with `http://<server>:8080/display` as its Start URL and Keep
  Screen On. Locking the tablet to Sunroom (its kiosk mode) and switching the screen off on a
  schedule ("Schedule Wakeup and Sleep") need the app's paid PLUS licence; without them,
  Sunroom's own Sleep setting still darkens the page at night.
- **iPad:** open the address in Safari, then **Share → Add to Home Screen**; on iPadOS 26 it opens
  full screen, like an app. Pair it after opening it from the home screen, because the
  home-screen app keeps its own sign-in. Set **Settings → Display & Brightness → Auto-Lock** to
  Never. Guided Access keeps the iPad on Sunroom: turn it on in **Settings → Accessibility →
  Guided Access** (set its Display Auto-Lock to Never too), open Sunroom, and triple-click the
  top button (or the Home button) to start it.
- **Both:** keep it on a charging stand, and turn on its battery-protection setting if it has one.
  Over plain `http://`, a web page can't keep a tablet's screen awake by itself (that needs an
  `https://` address, [REMOTE-ACCESS.md](REMOTE-ACCESS.md)), so the tablet's own "never sleep"
  setting does it. Sunroom's Sleep setting still darkens the page at night, but it can't switch a
  tablet's screen off.
- **Size:** a 10 or 11 inch tablet suits a hallway or a desk more than a kitchen wall.

## Hardware test matrix

Each of these is tried on real hardware before the first kitchen-screen release is called
finished (PLAN §13.10). The owner fills in the results; nothing here is a guess. Write each result
with its date, the Sunroom version and the Raspberry Pi OS release, and never a household name,
an address or a photo of the family's own screen.

| # | Setup or test | It passes when | Result |
|---|---|---|---|
| 1 | Pi 5, Raspberry Pi OS Trixie, a 24 inch HDMI touch monitor, landscape | It installs and pairs; the week fills the screen at 1920 × 1080; taps land where touched; "Dim in the evening" turns the monitor's own brightness down (DDC/CI) | Not tested yet |
| 2 | The same monitor in portrait (`--rotate 90`) | The portrait layout fills the screen and taps land where touched | Not tested yet |
| 3 | Pi 4 (4 GB), Raspberry Pi OS Bookworm on labwc, a 15.6 inch portable touch monitor | It installs and pairs; the board stays smooth; after the 04:00 browser restart the board is back without a touch | Not tested yet |
| 4 | Raspberry Pi Touch Display 2, 10 inch, on a Pi 5 | Touch works; "Dim in the evening" turns its backlight down (sysfs); "Screen off" switches the backlight off at night | Not tested yet |
| 5 | Pull the power plug, five times | The screen comes back paired each time, with no "Restore pages?" bubble; on a Pi that runs Sunroom, `sudo docker exec sunroom sunroom inspect-backup /data/sunroom.db` shows `"quick_check": "ok"` | Not tested yet |
| 6 | A 72-hour soak | Still smooth after three days; memory samples (for example `free -m` once an hour) climb during the day and fall back at each 04:00 restart | Not tested yet |
| 7 | Wi-Fi only, no network cable | Live updates stay connected for a day; a change made on a phone shows on the wall within a few seconds | Not tested yet |
| 8 | Tap to wake with the panel off | With "While asleep" set to "Screen off", the panel goes dark at the sleep time, and a tap turns it on for 2 minutes | Not tested yet |
| 9 | squeekboard (Raspberry Pi's on-screen keyboard) | Sunroom's own keyboard opens for its fields, and squeekboard doesn't pop up over it | Not tested yet |
| 10 | `.local` from an iPhone | `http://sunroom.local:8080` opens | Not tested yet |
| 11 | `.local` from an Android phone | `http://sunroom.local:8080` opens | Not tested yet |
| 12 | `.local` from a Windows computer | `http://sunroom.local:8080` opens | Not tested yet |

Sunroom Screen (0.13.0, [M7](M7.md) T10): the same installer, now with the program that runs the
screen. Rows 13 to 23 are a Pi's and a Linux desktop's; macOS and Windows follow.

| # | Setup or test | It passes when | Result |
|---|---|---|---|
| 13 | A Pi set up before 0.13.0, the installer run again with its first options | Sunroom Screen replaces the launcher and the screen helper (the log says so); the screen comes back paired, on its board; `sunroom-kiosk status` answers | Not tested yet |
| 14 | A fresh Pi, the installer with no option | After the restart, Where Is Your Sunroom? lists the server under On Your Network, and Use This Sunroom opens it at its pair code | Not tested yet |
| 15 | A typed address (Somewhere Else, on the wall's keyboard) | Check Address says whose Sunroom it is, or why not; Use This Sunroom opens it | Not tested yet |
| 16 | Chrome's Local Network Access | Settings → This Screen shows on the wall with no prompt on the screen | Not tested yet |
| 17 | This Screen's Restart and Shut Down | Restart: the screen is back on its board in about a minute; Shut Down asks first, then the Pi powers off | Not tested yet |
| 18 | This Screen's Rotation, each of the four | The picture turns at once, and taps land where touched after each turn and after a restart | Not tested yet |
| 19 | This Screen's Change Wi-Fi and Change Address | It joins the network whose password was typed on the wall's keyboard; Change Address asks first, keeps the pairing and opens Where Is Your Sunroom? | Not tested yet |
| 20 | Update Now from a real older version | The Software row shows the percent and the screen comes back on the new version; Updates on Install overnight does the same in the sleep hours | Not tested yet |
| 21 | The server's address changed | A Sunroom found on the network is found at its new address within a few minutes; a typed one shows Can't Reach | Not tested yet |
| 22 | Sunroom stopped for five minutes | Can't Reach shows after about two minutes, and the board comes back by itself when Sunroom answers | Not tested yet |
| 23 | A Linux desktop (Debian or Ubuntu), the installer with no option | With no browser it installs Chromium (Debian) or Google Chrome (Ubuntu) first; the screen starts at once and at each sign-in, full screen, and pairs; This Screen has Quit Sunroom Screen, which closes it until the next sign-in | Not tested yet |

macOS and Windows (0.13.0, [M7](M7.md) T13). Rows 24 to 33 were Sunroom OS's, the card image
retired in 0.17.0 ([ADR 0042](adr/0042-m9-the-owners-notes-of-2026-10-28.md)); a Pi is set up with
the installer, as in rows 13 to 23.

| # | Setup or test | It passes when | Result |
|---|---|---|---|
| 34 | A Mac, `install.sh` with no option | With no browser it installs Google Chrome first; the screen starts at once and at each sign-in, full screen, and pairs; This Screen's Quit closes it until the next sign-in | Not tested yet |
| 35 | A Windows computer, `install.ps1` | The line, typed in a PowerShell window with Microsoft Defender on, installs with no threat found (ADR 0041); it starts at sign-in with no console window, and none flashes while it runs; in Edge, full screen, and pairs; This Screen's Quit closes it; `-Uninstall` takes it off | Not tested yet |

The one-command installer ([ADR 0037](adr/0037-one-command-sets-up-a-screen.md)): the kitchen screen
alone is the default everywhere, and Sunroom on a Pi takes `--with-sunroom`.

| # | Setup or test | It passes when | Result |
|---|---|---|---|
| 36 | A Pi that runs Sunroom from an earlier installer, run again with no option | It says the Pi keeps Sunroom; Sunroom and the screen come back as they were | Not tested yet |
| 37 | A fresh Pi, `--with-sunroom` | The phone address and QR code as before; after the restart, the screen shows its pair code | Not tested yet |

On This Computer, Sunroom run as a program by Sunroom Screen ([ADR 0038](adr/0038-sunroom-on-this-computer.md)).
Each from a fresh install with no option, then **On This Computer** → **Run Sunroom Here**.

| # | Setup or test | It passes when | Result |
|---|---|---|---|
| 38 | A Pi with 64-bit Raspberry Pi OS | Setting Up Sunroom counts up, Sunroom's setup QR code opens on a phone, the screen pairs; after a power cut Sunroom and the screen come back by themselves | Not tested yet |
| 39 | A Linux desktop (Debian or Ubuntu) | As row 38; `systemctl --user status sunroom` is active, and Sunroom answers phones after a restart before anyone signs in | Not tested yet |
| 40 | A Mac with Apple silicon | As row 38; macOS asks once to let Sunroom accept connections (Allow), and the Mac doesn't sleep while Sunroom runs | Not tested yet |
| 41 | A Windows computer (x64, and ARM) | As row 38; Windows asks once to let Sunroom through its firewall (Allow), Sunroom starts again at sign-in and after a restore, and `-Uninstall` stops it and keeps its data | Not tested yet |
