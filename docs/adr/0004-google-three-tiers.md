# ADR 0004: Google in three tiers, with OAuth only where Google allows it

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

- Google rejects OAuth redirect URIs that are plain HTTP, raw IP addresses or non-public hostnames; `localhost` is the one exception. A Sunroom reached as `http://sunroom.local:7867` or `http://192.168.1.20:7867` can't complete Google's web sign-in.
- The device-code flow, made for TVs and other devices without a keyboard, does not allow Calendar scopes.
- Both facts were checked against Google's docs on 2026-10-07 (PLAN §3, §8.1).
- Most households start on a plain-HTTP LAN (PLAN §13.8).
- Every two-way option needs a Google Cloud project, and some families won't finish that setup (PLAN §17, risk 1).

## Decision

Offer three tiers, in this order, all set up on a phone (UX §6):

| Tier | How | Direction | On a plain-HTTP LAN |
|---|---|---|---|
| 1. Secret address | Paste the calendar's "Secret address in iCal format" into the `ics` provider (ADR 0005) | Read-only | Works |
| 2. Service account | The family makes a service account in their own Google Cloud project, uploads its JSON key, and shares each calendar with the account's email, choosing "Make changes to events" | Two-way | Works |
| 3. OAuth | The standard web flow, with the household's own client ID and secret entered in Settings | Two-way | Only on the display itself, at `localhost` |

- **Tier 1 is the default suggestion.** It needs no setup, and the UI says plainly that Google updates it slowly.
- **Tier 2** has no consent screen, no verification and no token expiry. Sunroom shows the account's email with a copy button, adds each shared calendar by its ID with `calendarList.insert`, then syncs with `syncToken`. The key is stored encrypted and never shown again.
- **Tier 3** works when Sunroom has a public HTTPS address (a reverse proxy, Tailscale Serve). It reuses Dinner Bell's Kroger account module: PKCE, single-use state, an encrypted refresh token, single-flight refresh, and `needs_reconnect` on `invalid_grant`. Settings shows the exact redirect URI to register, such as `https://calendar.example.com/api/calendar-sync/google/callback`.
- **On a Pi that runs both the server and the display,** Settings on the display offers "Connect Google on this screen" when the page's hostname is `localhost`, because Google accepts loopback redirects.
- **Words.** The UI never says "OAuth" or "service account". The tiers read "Paste the secret address", "Share with a Sunroom helper" and "Sign in with Google".

The order in which the tiers are built is ADR 0020.

## Consequences

- A family on a LAN gets two-way Google sync without a domain or a certificate, at the cost of about seven guided steps, once.
- A service account can't invite attendees. Sunroom doesn't need that.
- An OAuth app left in Google's "Testing" status gets refresh tokens that expire after 7 days, so the guide says to publish it. Personal use needs no verification, only a tap through the warning screen.
- The secret address's freshness is undocumented. M2 measures it and records it in `docs/SYNC.md`.
- Google's hosts are constants in the SSRF guard (PLAN §12.6).
- A redirect relay for LAN-only households stays a later idea, if tier 2 proves too hard (PLAN §19).
