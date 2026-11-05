# ADR 0017: A Host rule instead of `APP_BASE_URL`; the cookie name follows the scheme

- **Status:** Accepted; the default Host rule and the proxy list changed by [0034](0034-m6-batch-6-the-owners-sixth-notes.md) (any Host unless `APP_ALLOWED_HOSTS` is set; no `TRUSTED_PROXIES`, forwarded headers believed from the home network)
- **Date:** 2026-10-07

## Context

- One Sunroom is reached under several names at once: `http://sunroom.local:7867` from phones, an IP address such as `http://192.168.1.20:7867` when `.local` fails, `http://localhost:7867` on a Pi that runs both server and display, and perhaps an HTTPS name through a proxy or Tailscale.
- Dinner Bell has one required `APP_BASE_URL`. Its CSRF check compares `Origin` to that one origin, and its session cookie is always `__Host-` with `Secure`. A single base URL would make a non-technical self-hoster configure one, and a `Secure` cookie is never sent over plain HTTP.

## Decision

- **The Host rule** (PLAN §13.4). Every request's `Host`, or `X-Forwarded-Host` from a trusted proxy, must be one of:
  - `localhost`, a loopback address or an IP literal;
  - the container's hostname;
  - a name ending in `.local`, `.lan`, `.home`, `.home.arpa`, `.internal` or `.ts.net`;
  - a name in `APP_ALLOWED_HOSTS`, exact or a wildcard such as `*.example.com`.

  Anything else gets 421, with the fix in the body.
- **CSRF** on every mutating request: `X-Sunroom: 1` must be present, and an `Origin`, when sent, must equal exactly `scheme://Host` (`null` is refused). Without an `Origin`, `Sec-Fetch-Site` must be `same-origin` or `none`. The scheme counts as `https` only when a proxy in `TRUSTED_PROXIES` says so.
- **Cookies by scheme.** Over plain HTTP the session cookie is `sunroom`, without `Secure` or the `__Host-` prefix. Over HTTPS it is `__Host-sunroom` with `Secure`. The two can coexist, so an HTTP cookie never shadows an HTTPS one. HSTS is sent only over HTTPS.
- **Addresses for people.** QR codes use `SUNROOM_ADVERTISED_URL` when the request came from `localhost`; the Pi installer sets it to `http://<hostname>.local:7867`. Settings → Connection lists every address the server has recently been reached on.

## Consequences

- A LAN install needs no address configured at all. A public proxy name needs `APP_ALLOWED_HOSTS` and `TRUSTED_PROXIES`, which is the owner's setup (ADR 0018).
- A reverse proxy must pass `Host` through unchanged and set `X-Forwarded-Proto`. If it isn't listed in `TRUSTED_PROXIES`, every mutation over HTTPS fails the Origin check; Settings → Connection shows the scheme the server sees, so this can be confirmed.
- A web page that points its own name at the household's IP still sends its own `Host`, so it gets 421.
- A browser signs in separately under each name it uses.
- Google's OAuth redirect is registered for one public name, so Google's third tier is the one place an address is still set by hand (ADR 0004).
- M0 checks the rule: `Host: evil.example` gets 421, and a mutation without `X-Sunroom: 1` gets 403.
