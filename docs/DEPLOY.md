# Deploying Sunroom

How to run Sunroom with Docker Compose on a home server, behind your own HTTPS reverse proxy, with
a Raspberry Pi as the wall screen: path b in the [README](../README.md#install). Sunroom lives
in a folder of its own on the server, with a `docker-compose.yml` you edit by hand and start with
`docker compose up -d`. Household-specific values go in that file (or a `.env` beside it), never
into this repository. Portainer, if you use it, can show the logs and stop or start the container;
it doesn't need to manage it.

On a plain home network you can skip the proxy entirely: leave every variable empty and open
`http://<server>:8080`. Sunroom answers to local names and addresses on its own.

## What you need

- A Docker host with Docker Compose.
- For an HTTPS name: a reverse proxy with a subdomain for Sunroom. HTTPS lets phones install
  Sunroom to the home screen, keep working offline and reach it away from home.
- About 300 MB of disk, plus room for backups and photos.

## 1. Start Sunroom

1. On the server, make a folder for Sunroom and put the example compose file in it:

   ```sh
   sudo mkdir -p /opt/sunroom && cd /opt/sunroom
   sudo curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/ScopeXL/sunroom/main/docker-compose.example.yml
   ```

   Any folder works, for example one named after the repo, next to your other apps.
2. Edit `docker-compose.yml` and fill in what applies, either in place of the `${…}` placeholders
   or in a `.env` file in the same folder (Compose reads it by itself):

   | Variable | Value |
   |---|---|
   | `APP_ALLOWED_HOSTS` | Optional. A lock: with it set, Sunroom answers only to these names (e.g. `calendar.example.com`; comma-separated for several; `*.example.com` covers every name under it) and local ones. Left empty it answers to any name, which is all most homes need ([REMOTE-ACCESS.md](REMOTE-ACCESS.md) says when the lock is worth it) |
   | `TZ` | Your time zone, e.g. `America/New_York`. The setup suggests one too |
   | `APP_PASSWORD` | Optional. A household password that always wins over the one chosen in setup, 8 characters or more |
   | `APP_SECRET_KEY` | Optional. Without it, Sunroom makes one and keeps it on the volume. If you set it (`openssl rand -base64 48`), keep a copy in a password manager: changing it signs everyone out |
   | `SUNROOM_INSTALL_KIND` | Optional. `portainer` when Portainer manages the stack, so Settings → About says how to update that way (the default, `docker`, means Compose in this folder) |
   | `SUNROOM_UPDATE_CHECK` | Optional. `0` keeps the daily check for new versions off, whatever Settings → About says |
   | `SUNROOM_FEEDBACK_URL` | Optional. Leave it out, and Settings → Support Sunroom → Send Feedback opens GitHub's new-issue page, which needs a GitHub account. Set it to an address of your own (a Discord webhook of yours works), and Send Feedback posts there instead, from any device and from the screen, with no account needed; it is kept out of the logs |

3. Keep the `volumes:` block at the end of the file, with `name: sunroom_data`. It creates the
   `sunroom_data` volume, where the database, the nightly backups and the photos live, with the
   right ownership by itself (and the commands in RESTORE.md find it by that name). To use a host
   folder instead, see *Troubleshooting*.
4. Another app already uses port 8080 on this server? Change only the left number of the
   `ports:` line, for example `"8081:8080"`, and point the proxy at that port.
5. Start it:

   ```sh
   docker compose up -d
   ```

   Within about a minute `docker compose ps` shows it **healthy** (so does Portainer's container
   list). `docker compose logs -f sunroom` follows the log.

## 2. Point the reverse proxy at it

- Forward your subdomain to the server on the host port from the `ports:` line (or put the
  container on the proxy's Docker network, remove the `ports:` lines, and forward to
  `sunroom:8080`). The proxy must pass the `Host` header through unchanged and set
  `X-Forwarded-Proto` (every common proxy does both by default).
- Turn on **HTTP/2** for the host. Browsers allow only six HTTP/1.1 connections per site, and
  the live-update stream keeps one open on every device and screen.
- Live updates use server-sent events on `/api/events`. They must not be buffered or compressed:

  | Proxy | What to set |
  |---|---|
  | Nginx Proxy Manager / nginx | Nothing is usually needed: Sunroom sends `X-Accel-Buffering: no`. If updates arrive late, add a custom location `/api/events` with `proxy_http_version 1.1; proxy_set_header Connection ""; proxy_buffering off; gzip off;` |
  | Traefik | Don't attach the `buffering` middleware to this router. If you use `compress`, set `excludedContentTypes: [text/event-stream]` |
  | Caddy | `reverse_proxy` already streams events. If you use `encode`, exclude the stream: `@notsse not path /api/events` then `encode @notsse zstd gzip` |
  | Cloudflare (proxied DNS or Tunnel) | Add a Cache Rule that bypasses `/api/*` |

- **Restore from a File** (Settings → Backup) sends a whole backup in one request, and a zip with
  every photo can be a few GB. Let the proxy take it:

  | Proxy | Uploads (Restore from a File) |
  |---|---|
  | Nginx Proxy Manager / nginx | `client_max_body_size 0;` (nginx's default is 1 MB); in Nginx Proxy Manager, in the host's **Advanced** tab |
  | Traefik | Nothing, unless the `buffering` middleware sets `maxRequestBodyBytes`: raise it |
  | Caddy | Nothing, unless a `request_body` sets `max_size`: raise it |
  | Cloudflare (proxied DNS or Tunnel) | 100 MB per request on the Free plan: restore a bigger zip from the home network, or restore Data Only |

  When a file is more than the proxy lets through, Sunroom says "The file is bigger than your
  proxy allows" instead of restoring it.

## 3. Check the proxy's headers

There is nothing to set for the proxy (ADR 0034). Sunroom believes forwarded headers (https,
the real client address, the public name) from any address on the home network (the private
ranges, loopback, link-local and Tailscale's), which is where a proxy in Docker on the same
host, or on another machine at home, connects from; it never believes them from the internet.

What the proxy must do is say the browser is on https: `X-Forwarded-Proto: https`. Every common
proxy does it by default; a hand-written nginx needs `proxy_set_header X-Forwarded-Proto
$scheme;`. When it doesn't, Sunroom refuses changes made through it, with "Sunroom is reached
over https, but the proxy didn't say so", and its log (`docker compose logs sunroom`, or the
container's **Logs** in Portainer) has a line `csrf.https_not_forwarded` with `proxy=<address>`.

An older compose file's `TRUSTED_PROXIES` line can stay: it's ignored, and the log says so.

## 4. First visit

Open the address on any device and follow the setup: a household password, your household's name
and time zone, the people who live here, a parent PIN. Then:

- **iPhone:** Share → **Add to Home Screen**, and open Sunroom from there.
- **Android:** Chrome's menu → **Install app**.

**Settings → About** (under **More** on a phone) shows the version, "Live updates: connected",
and the URL this device used.

## 5. The wall screen

No server at home? The screen's own computer can run Sunroom itself, with no Docker: install the
screen and choose **On This Computer** on it ([KIOSK.md](KIOSK.md#sunroom-on-this-computer)). This
section is for a screen that shows the Sunroom you run here.

On the Raspberry Pi (Raspberry Pi OS 64-bit with desktop), another Linux computer with a desktop,
or a Mac (Windows: [KIOSK.md](KIOSK.md#windows)), one command sets up the screen, a browser
included:

```sh
curl -fsSL https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.sh | bash
```

Then (on a Pi, after its restart) the screen looks for Sunroom on its network and lists what it
finds; a Sunroom behind a proxy that picks a site by its name isn't found that way, so type its
address there (`https://calendar.example.com`), or give it to the installer: `curl … | bash -s --
--url https://calendar.example.com`. Then the screen shows a code; type it on a signed-in device
under **Settings → Devices → Pair a Display** (under **More** on a phone). [KIOSK.md](KIOSK.md) has
the details.

**Optional: let screens find this server by name.** A Sunroom screen looking for Sunroom checks
every address on its network on port 8080, which finds this setup as it is. A server that runs
avahi (most Linux machines do; `systemctl status avahi-daemon`) can also announce Sunroom, which
a screen hears even when Sunroom is on another port. Put this in
`/etc/avahi/services/sunroom.service` (change `8080` to the port you publish); avahi picks it up
by itself:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Sunroom on %h</name>
  <service><type>_sunroom._tcp</type><port>8080</port></service>
</service-group>
```

## Updating

Each release prints these steps. In Sunroom's folder on the server:

1. `docker compose pull && docker compose up -d` (if you pinned a version in `image:`, change it
   to the new one first).
2. Wait for **healthy** (`docker compose ps`), then check `<your address>/api/version` shows the
   new version.

To hear about new versions, turn on **Settings → About → Check for updates daily**: once a
day Sunroom asks GitHub for its latest version (GitHub sees your server's address) and About
says when one is out, with these steps. It's off until you turn it on.

Before migrating, Sunroom copies the database into `/data/backups/pre-migrate/`. If a migration
fails, it refuses to start and the data is left exactly as it was. Every open wall screen and
device refreshes itself within a minute of the update; a screen in the middle of an edit waits
for it.

**If Portainer manages it instead** (a stack pasted from the example): update the stack with
**Re-pull image and redeploy** switched on.

## Backups

- A verified copy is written every night at 03:30 (household time) into `/data/backups/`,
  keeping 14 daily and 8 weekly copies unless **Settings → Backup** says otherwise (it can turn
  the nightly copies off, too). It shows when the last one ran and every copy on the server, to
  download or remove, and has **Back Up Now** and **Download**: **Data Only** (the database,
  copied that moment) or **Data & Photos** (the database and every photo in one zip, which
  restores anywhere).
- Photos are files on the volume, not in the database: only Data & Photos has them. Include
  the whole `sunroom_data` volume in your host's own backups too, or download Data & Photos now
  and then and keep it off the server.
- To restore, see [RESTORE.md](RESTORE.md).

## Troubleshooting

**"Sunroom doesn't answer to the address …" (421).** Only with `APP_ALLOWED_HOSTS` set: the name
in the browser isn't a local one and isn't in the list. Add it in `docker-compose.yml` and run
`docker compose up -d`, or empty the setting to answer to any name.

**A host folder instead of the volume.** Sunroom never runs as root: it runs as uid 10001, so a
folder you mount at `/data` must be writable by the user it runs as. The simplest is to run it as
the folder's owner: add `user: "1000:1000"` to the service, with the owner's ids from `id -u` and
`id -g`. Or give the folder to uid 10001: `sudo chown -R 10001:10001 <folder>`.

The container logs explain every refusal in plain words. The exit code says which step failed:

| Exit code | Meaning | Fix |
|---|---|---|
| 78 | A setting is invalid (the log names it, never its value) | Fix the setting named in the log, then `docker compose up -d` |
| 73 | `/data` isn't a mounted volume, isn't writable, is a network filesystem, or another instance is using it | Keep the example's `volumes:` block (the `sunroom_data` volume); with a host folder, see above. Run exactly one container per volume |
| 74 | Not enough disk space, or the pre-upgrade backup failed | Free disk space and start it again |
| 65 | The database was upgraded by a newer Sunroom than this image | Start the newer version, or restore the pre-upgrade backup (RESTORE.md) |
| 70 | A migration failed. Nothing was changed | Start the previous version (set it in `image:`) and report the log |

Live updates stuck on "connecting", or "checking every 30 seconds"? Your proxy is buffering the
stream: see step 2.
