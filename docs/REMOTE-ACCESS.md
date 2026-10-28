# Remote access and HTTPS

Sunroom works on your home network with nothing to set up: your devices open
`http://sunroom.local:8080` (or the server's numbered address) and everything works. This page
is for when you want more: Sunroom on your devices away from home, the app installed on Android,
or Sign in with Google. Those need Sunroom at an `https://` address, and this page shows four ways
to get one. The commands were checked against each tool's own documentation on 2026-10-08.

## What works without HTTPS

| | Plain http, at home | An https address |
|---|---|---|
| The calendar, lists, chores, meals, countdowns, photos, weather and live updates | Yes | Yes |
| Signing in, pairing the wall screen, and Add a Device (typing the code, or scanning the QR code with the phone's camera) | Yes | Yes |
| Adding photos from a phone | Yes | Yes |
| On an iPhone's or iPad's home screen, opening like an app | Yes, with iOS and iPadOS 26 | Yes |
| Installed as an app on Android (Chrome's **Install app**) | A home-screen shortcut only | Yes |
| Opening when the server can't be reached (it says it's offline instead of showing a browser error) | No | Yes |
| The wall screen on a Raspberry Pi | Yes: the installer sets the Pi's browser up for it | Yes |
| A tablet on the wall keeping its own screen awake | No: set the tablet never to sleep ([HARDWARE.md](HARDWARE.md)) | Yes |
| Sign in with Google | No: Google refuses `http://` addresses (its other two ways work, [SYNC.md](SYNC.md)) | Yes |
| Using Sunroom away from home | No | Yes, with the ways below |

An `http://` address and an `https://` one are separate sign-ins: when a device moves to the new
address, sign in there once, and on a phone add the new address to the home screen (and remove
the old one).

## Which way

| Way | Away from home | What you need | Who can reach the sign-in page | Who else sees the traffic |
|---|---|---|---|---|
| [Stay at home](#stay-at-home-the-default) | No | Nothing | Your home network | Nobody |
| [Tailscale](#tailscale-recommended) (recommended) | Yes, on devices with the Tailscale app | A free Tailscale account | Only your own devices | Nobody: it's encrypted from end to end |
| [Your own HTTPS proxy](#your-own-https-reverse-proxy) | If your proxy is on the internet | A proxy you already run | Depends on your proxy | Usually nobody |
| [Caddy](#caddy-with-a-lets-encrypt-certificate) | Yes, in any browser | A domain name, two ports opened on your router | Anyone on the internet | Nobody |
| [Cloudflare Tunnel](#cloudflare-tunnel) | Yes, in any browser | A domain name on Cloudflare | Anyone on the internet | Cloudflare |

## Stay at home (the default)

- Nothing to set up. Devices on the home Wi-Fi use `http://sunroom.local:8080`, or the server's
  numbered address (the Pi's installer prints it).
- **Never forward port 8080 on your router.** That would put Sunroom on the internet over plain
  http, and the household password would cross the internet unencrypted. Use one of the ways
  below instead.
- If your router has its own VPN and your devices use it away from home, they can reach the server's
  numbered address through it (`.local` names usually don't work over a VPN).

## The one setting (optional)

None of the ways below needs a setting for the proxy (ADR 0034). Sunroom believes a proxy's
forwarded headers ("this came in over https", which device it came from, the name it was asked
for) whenever the connection comes from the home network: loopback, the private ranges, link-local
addresses and Tailscale's `100.64.0.0/10`. That's where every proxy in this page connects from,
whether it runs on the same computer outside Docker, in Docker beside Sunroom, or on another
machine at home. A connection from the internet is never believed. A `TRUSTED_PROXIES` line from
an earlier version is ignored; the log says so.

And by default Sunroom answers to any name, so `http://<server>:8080` works the moment it starts.

- **`APP_ALLOWED_HOSTS`** is an optional lock. With it set, Sunroom answers only to local names
  (`.local`, `.lan`, `.home`, `.home.arpa`, `.internal`, Tailscale's `.ts.net`, numbered
  addresses) and the names you list, for example `calendar.example.com` (several separated by
  commas; `*.example.com` covers every name under it); anything else gets "Sunroom doesn't answer
  to the address …". **When it's worth it:** when Sunroom is on the internet under a public name
  (Caddy, Cloudflare). The lock stops DNS rebinding: a web page that points its own name at your
  home address, so the browser treats it as the same site. Without the lock such a page could read
  Sunroom's public pages (its version, whether it's set up, and the id `/api/discover` gives the
  screens that look for it; never the household's name, which that route tells only a local
  address) and leave a name in About's "Recently reached at"; it can't sign in or change anything. To turn it on without a public name, list
  the name you use, for example `sunroom.local`.

Where to put it:

| How you run Sunroom | Where | Then |
|---|---|---|
| All on the Pi, from the installer | Add a line such as `APP_ALLOWED_HOSTS=calendar.example.com` to `/opt/sunroom/.env` (`sudo nano /opt/sunroom/.env`) | `cd /opt/sunroom && sudo docker compose up -d` |
| Docker Compose ([DEPLOY.md](DEPLOY.md)) | In `docker-compose.yml`, or a `.env` file beside it | `docker compose up -d` in that folder |
| Portainer, Unraid, CasaOS, Synology | The container's environment variables | Redeploy or restart the container |

## Tailscale (recommended)

Tailscale joins your devices and the computer that runs Sunroom into a private network of your
own, called a tailnet. Sunroom gets an https address with a real certificate, it works at home
and away, nothing changes on your router, and only your own devices can reach it. Tailscale's
free Personal plan covers a family (up to six people when this was written).

1. **Make a Tailscale account** at [tailscale.com](https://tailscale.com).
2. **Turn on HTTPS for your tailnet.** In Tailscale's admin console, open **DNS**, check that
   **MagicDNS** is on, and under **HTTPS Certificates** choose **Enable HTTPS**. Sunroom's address
   will be `https://<machine name>.<tailnet name>.ts.net`. Tailscale publishes these names in
   public certificate logs, so if the server's machine name says anything private (a family name,
   say), rename the machine in the admin console first.
3. **Install Tailscale on the computer that runs Sunroom** (the Pi itself, if everything is on
   the Pi):

   ```sh
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   Open the link it prints and sign in. On a NAS, use Tailscale's package for it instead
   (Tailscale's own install pages list them).
4. **Serve Sunroom on the tailnet:**

   ```sh
   sudo tailscale serve --bg 8080
   ```

   If you changed the left number of Sunroom's `ports:` line, use that number. It prints the
   https address, and it keeps serving after a restart. `sudo tailscale serve status` shows it
   again; `sudo tailscale serve reset` turns it off. Tailscale streams live updates by itself.
   Nothing to set in Sunroom: it believes Tailscale's connections, and answers to the `.ts.net`
   name.
5. **On each device:** install the Tailscale app (App Store, Google Play, or tailscale.com for a
   computer), sign in to your tailnet, and leave it connected. Invite the rest of the family from
   the **Users** page of the admin console. Then open the https address, sign in with the
   household password, and on a phone add it to the home screen.
6. **Check it** (see *Check that it worked*).

The wall screen can stay on its home-network address; nothing changes for it.

**Sign in with Google over Tailscale.** Once step 4 is done, Google's sign-in works at the
`.ts.net` address. The redirect address to add to your Google app is
`https://<machine name>.<tailnet name>.ts.net/api/calendar-sync/google/callback`; Sunroom shows
the exact one in its Sign in with Google steps (Settings → Calendars & accounts → Add an
account). Google's rules accept it: it's https, with a real domain name. Google never connects to
it; only your device's browser comes back to it.

## Your own HTTPS reverse proxy

If you already run one (Nginx Proxy Manager, Traefik, Caddy and so on), add Sunroom like any
other app:

- Forward your name to Sunroom's port on the server (`http://<server>:8080`), or to
  `sunroom:8080` when the proxy and Sunroom share a Docker network.
- Pass the `Host` header through unchanged, and set `X-Forwarded-Proto` (and `X-Forwarded-For`).
  Every common proxy does all three by default.
- Live updates stream from `/api/events`: they must not be buffered or compressed, and HTTP/2
  should be on. [DEPLOY.md](DEPLOY.md), step 2, has the setting for each proxy.
- Nothing to set for the proxy. If the name is on the internet, set `APP_ALLOWED_HOSTS` to it
  (see *The one setting*).
- If the name can be reached from the internet, so can Sunroom's sign-in page. Finish the setup
  before you open it up, and choose a long household password. Sunroom locks an address out for
  a while after 5 wrong passwords in 15 minutes.

## Caddy with a Let's Encrypt certificate

Caddy is a web server that fetches and renews its own certificates. With it, Sunroom is at your
own name, such as `calendar.example.com`, from any browser. You need:

- a domain name whose `A` record (and `AAAA`, if you have IPv6) points at your home's internet
  address; if that address changes now and then, your DNS provider's dynamic DNS keeps it up to
  date;
- ports 80 and 443 forwarded on your router to the computer that runs Caddy (usually the one
  that runs Sunroom).

1. **Install Caddy:** follow the "Debian, Ubuntu, Raspbian" steps on
   [caddyserver.com/docs/install](https://caddyserver.com/docs/install). It then runs as a
   service called `caddy`.
2. **Point it at Sunroom:** open its settings with `sudo nano /etc/caddy/Caddyfile` and replace
   what's there with:

   ```
   calendar.example.com {
       reverse_proxy localhost:8080
   }
   ```

3. **Apply it:** `sudo systemctl reload caddy`. Caddy fetches the certificate by itself (from
   Let's Encrypt, or ZeroSSL if that fails), renews it, and sends `http://` visits to `https://`.
   It streams live updates without any extra setting. Its log is
   `journalctl -u caddy --no-pager | less +G`.
4. **Lock Sunroom to the name** (recommended, the name is public): `APP_ALLOWED_HOSTS=
   calendar.example.com`; restart Sunroom.
5. **Check it** (see *Check that it worked*).

Anyone on the internet can now reach Sunroom's sign-in page, so finish the setup first and use a
long household password. If Caddy runs in Docker instead, put it on a network with Sunroom and use
`reverse_proxy sunroom:8080`; nothing else changes.

Caddy can also make an https address for the home network alone, without a domain
(`tls internal`), but then every device has to be set up to trust Caddy's own certificate
authority. That's for people who already know how; most households are better off with
Tailscale.

## Cloudflare Tunnel

A small program from Cloudflare, `cloudflared`, runs on the server and connects out to
Cloudflare, which gives your name an https address. No ports are opened on your router.

**What Cloudflare sees.** Cloudflare holds the https end of the connection, so traffic is
decrypted at Cloudflare before it travels on to your server. Cloudflare can see every page,
event and photo that passes, and the household password whenever someone signs in. If that
matters to your family, use Tailscale instead.

You need a domain name whose DNS is run by Cloudflare. Cloudflare moves its menus now and then;
these are the names it uses now, and its guide "Create a tunnel (dashboard)" has the current
ones.

1. **Make the tunnel:** in the Cloudflare dashboard, go to **Networking → Tunnels → Create a
   tunnel**, give it a name such as `sunroom`, pick your system, and run the install command it
   shows on the server. It looks like `sudo cloudflared service install <token>`. The token is the
   tunnel's password: don't share it or paste it anywhere public.
2. **Route your name to Sunroom:** open the tunnel, then **Routes → Add route → Published
   application**. Enter a subdomain (`calendar`), choose your domain, set the service URL to
   `http://localhost:8080`, and add the route.
3. **Lock Sunroom to the name** (recommended, the name is public): `APP_ALLOWED_HOSTS=
   calendar.example.com`; restart Sunroom.
4. **Leave Rocket Loader off** for this name: Cloudflare's own documentation says it needs a looser
   security policy than Sunroom allows.
5. **Check it** (see *Check that it worked*).

Sunroom marks its answers and the family's photos as not to be cached, and Cloudflare follows
that. A Cache Rule that bypasses the cache for `/api/*` is still a good safety net
([DEPLOY.md](DEPLOY.md), step 2). Live updates stream through the tunnel as they are.

## Check that it worked

On any device, open the new https address, sign in, and go to **Settings → About** (under
**More** on a phone). Under
**Connection**:

- **Live updates** says "connected".
- **URL** shows your `https://` address. If it shows `http://`, the proxy isn't sending
  `X-Forwarded-Proto: https` (see *When something isn't right*).

`<your address>/api/version` should also show Sunroom's version.

## When something isn't right

- **"Sunroom doesn't answer to the address …"** (only with `APP_ALLOWED_HOSTS` set): the name
  isn't in the list. Add it and restart Sunroom.
- **"Sunroom is reached over https, but the proxy didn't say so"**: the proxy isn't sending
  `X-Forwarded-Proto: https`, or it connects from the internet rather than the home network.
  Every common proxy sends it by default; a hand-written nginx needs
  `proxy_set_header X-Forwarded-Proto $scheme;`. Sunroom's log has a line
  `csrf.https_not_forwarded` naming the proxy's address.
- **"This request was blocked for safety" on every change**: the proxy is changing the `Host`
  header on its way through. Make it pass `Host` unchanged.
- **Live updates stay on "connecting" or "checking every 30 seconds"**: the proxy is holding the
  live-update stream back. See [DEPLOY.md](DEPLOY.md), step 2.
- **Sunroom stops at startup with exit code 78** after a change: one of the settings has a typo.
  The log names it. `APP_ALLOWED_HOSTS` takes names only (no `https://`, no port).
- **A `TRUSTED_PROXIES` line from an earlier version** is ignored; the log says so. It can stay
  or go.
- **A device was signed out after moving to the new address**: each address is its own sign-in.
  Sign in once more there.
