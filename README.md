# Sunroom

A family wall calendar for the kitchen screen and everyone's phones. It runs on your own
computer at home, with no account anywhere and no subscription.

- **The week at a glance** on a touch screen in the kitchen: the clock, today lit up, and a line
  for now, readable from across the room.
- **Every phone** adds and changes things, and the screen follows within a second.
- **Made for a family:** one household password, a parent PIN for Settings on the shared screen,
  children with their own colors, and nothing that needs a technical grown-up every week.
- **Your data stays home,** on the kitchen computer itself or in one Docker container, with
  nightly backups.

**Status:** working, and still growing toward 1.0. It has the calendar (with Apple, Google and
other calendars synced in), lists, tasks with stars and routines, meals, countdowns, a photo
screensaver and the weather. The [plan](docs/PLAN.md#15-milestones) lists what each milestone
adds, and [CHANGELOG.md](CHANGELOG.md) what each release did.

## Install

**Do you already run Docker somewhere at home** (a NAS, a mini PC, Portainer, Unraid)?

- No: put everything on the kitchen computer (a Raspberry Pi, or a Linux, Mac or Windows
  computer by the kitchen), [path a](#a-all-on-the-kitchen-computer).
- Yes: run Sunroom there and use a Pi only as the screen, [path b](#b-sunroom-on-your-server-the-pi-is-the-screen).
- Only trying it out: [path c](#c-any-computer-no-pi).

### a. All on the kitchen computer

The screen and Sunroom on one computer: a Raspberry Pi 4 or 5 with a touch screen (HDMI plus its
USB touch cable, and the official power supply; [docs/HARDWARE.md](docs/HARDWARE.md) helps you
choose), or a Linux computer, a Mac with Apple silicon or a Windows computer by the kitchen.

**The simplest way on a Pi: write Sunroom OS** to the card with Raspberry Pi Imager, start the
Pi, and on the screen choose **On This Computer**. No terminal at all;
[docs/SUNROOM-OS.md](docs/SUNROOM-OS.md) shows each step. Or:

1. **A Pi:** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/), write
   **Raspberry Pi OS (64-bit)**, the one with the desktop. In Imager's settings, set the hostname
   to `sunroom`, your user name and password, your Wi-Fi, your time zone, and turn on SSH.
   **Another computer:** sign in to its desktop as the person the screen is for.
2. Open a terminal (on a Pi you can `ssh` in), and run the one command for it:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
   ```

   On Windows, open PowerShell (Start, then type PowerShell) and run this in its window:
   `irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 | iex`.
   It installs what the screen needs and starts it (a Pi restarts first).
3. **The screen asks where your family's Sunroom will run:** choose **On This Computer**.
   Setting Up Sunroom takes a few minutes. (On a Mac or Windows, if the computer asks whether
   Sunroom may accept connections, choose Allow.)
4. **Set up the household right on the screen:** choose **Set Up Here** and type on the keyboard
   that opens. Choose a household password, add the people who live here, and set a parent PIN.
   The screen becomes your kitchen screen by itself.
5. **Add the phones:** the last page shows a QR code. Scan it with each phone and sign in with the
   household password, then add Sunroom to the home screen (Safari: Share → Add to Home Screen).

Rather set up on your phone? Scan the QR code beside **Set Up Here** instead. The screen then
shows a six-character code: on your phone, open **More → Pair a display** and type it.

Keep that computer on and connected: phones open Sunroom from it. On a Pi,
`… | bash -s -- --with-sunroom` instead runs Sunroom in Docker, set up by the installer, which
prints the address and QR code at the end. If a `.local` address doesn't open, use the numbered
one: phones on a VPN or on mobile data can't see `.local` names. [docs/KIOSK.md](docs/KIOSK.md)
covers rotation, screens that stay blank, updates and removal.

### b. Sunroom on your server, the Pi is the screen

Run the container on the computer that already runs Docker. Nothing needs configuring; it keeps
everything in the `sunroom_data` volume.

- **Docker Compose:** in a folder of its own on the server (for example `/opt/sunroom`), save
  [docker-compose.example.yml](docker-compose.example.yml) as `docker-compose.yml`, then run
  `docker compose up -d`. Keep the `volumes:` block at the end: it creates the `sunroom_data`
  volume. Port 8080 already taken? Change only the left number, for example `"8081:8080"`.
- **Portainer:** Stacks → Add stack → Web editor, paste the same file, Deploy.
- **Unraid, CasaOS, Synology:** add a container from the image `scopexl/sunroom:latest`, port
  8080, and a volume (or folder) for `/data`. If you map a folder, it must be writable by the
  container's user (`--user 99:100` on Unraid's appdata).

Open `http://<server>:8080` on your phone and set up the household: there is nothing to
configure first. Your own HTTPS proxy, Tailscale or Cloudflare work with nothing to
set; [docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md) shows each way, and when to lock Sunroom to a
name with `APP_ALLOWED_HOSTS`.

Then set up the screen with one command. On the Pi (or another Linux computer, or a Mac):

```sh
curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
```

It installs what the screen needs, a browser too, and starts it (a Pi restarts first). On the
screen, choose **On Another Computer**: it looks for Sunroom on your network, so tap **Use This
Sunroom**, or type the address you open on a phone (an `https://` name works too). Then pair the
screen: it shows a six-character code; on your phone, open **More → Pair a display** and type it.
(Haven't set up the household yet? The screen can: choose **Set Up Here**, as in path a.)

### c. Any computer, no Pi

```sh
docker run -d --name sunroom --restart unless-stopped -p 8080:8080 -v sunroom_data:/data scopexl/sunroom:latest
```

Open `http://<computer>:8080` on a phone. Any browser shows the wall screen at `/display`; an old
tablet works as one (Android: Fully Kiosk Browser; iPad: Safari with Guided Access; see
[docs/HARDWARE.md](docs/HARDWARE.md#an-old-tablet-instead)).

### The installer, in short

| On | Command |
|---|---|
| A Pi, a Linux computer or a Mac: the screen | `curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh \| bash` |
| Windows: the screen | `irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 \| iex`, in a PowerShell window |
| A Pi: Sunroom (in Docker) and the screen | the first, ending `\| bash -s -- --with-sunroom` |
| A Pi: only Sunroom, no screen | the first, ending `\| bash -s -- --server-only` |

Each installs what the screen needs (a browser too, when there's none) and starts it. The screen
then asks where your family's Sunroom will run: **On This Computer** sets it up right there, and
**On Another Computer** finds the one you have on your network by itself. `--url <address>` skips the search, and
`--dry-run` (`-DryRun` on Windows) says what it would do first.
[docs/KIOSK.md](docs/KIOSK.md) has every option.

## Lost the household password?

Set `APP_PASSWORD` in the container's environment (it always wins), or run
`sudo docker exec -it sunroom sunroom reset-password`. Either way, phones sign in again and the
kitchen screen shows a new code to pair.

## Documentation

- [Plan](docs/PLAN.md): architecture, data model, plugins, milestones.
  [Adding a plugin](docs/PLUGINS.md) gives the steps.
- [UX](docs/UX.md): screens, flows and visual design.
- [Decision records](docs/adr/README.md): why things are the way they are.
- [The kitchen screen](docs/KIOSK.md), [Hardware](docs/HARDWARE.md), [Deploying](docs/DEPLOY.md),
  [Remote access and HTTPS](docs/REMOTE-ACCESS.md), [Restoring a backup](docs/RESTORE.md) and
  [Releasing](docs/RELEASING.md).
- [CLAUDE.md](CLAUDE.md): working rules for the AI sessions that build and maintain Sunroom.

## Developing

`just setup` once (it needs `uv`, `pnpm`, `gitleaks` and `jq`), then `just dev` for the app at
`http://localhost:5173`, `just seed` for the synthetic Sample Family, `just display` for the wall
screen in a window, and `just check` before every commit. `just` lists every command.

## Privacy

See [PRIVACY.md](PRIVACY.md). In short: your data stays on your own computer, and there are no
analytics or third-party scripts.

## License

[MIT](LICENSE)
