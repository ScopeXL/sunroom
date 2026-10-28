# Synced calendars

How Sunroom keeps Google, iCloud, other calendar servers, calendar addresses and holidays on
the board (PLAN §8, ADRs 0004, 0005, 0020, 0024 and 0028), and every server quirk met so far. For
a household: Settings → Calendars & Accounts → **Add an Account**, on any device or on the
wall screen. On the wall screen, Google's helper (a key file) and Sign in with Google
(Google's own page) show a QR code that opens them on a device.

## The kinds of account

| Kind | How it's connected | Direction | How fresh |
|---|---|---|---|
| A calendar address (.ics) | Paste the link. `webcal://` works | Shows events only | Checked every 30 minutes by default (15 minutes to 6 hours), never more often than every 5 |
| Google: the secret address | Paste "Secret address in iCal format" from Google Calendar's settings | Shows events only | Google itself updates this address slowly: see "Measured freshness" below |
| Google: a helper | A service account in the family's own Google Cloud project; each calendar is shared with its address ("Make changes to events") and added by its ID | Both ways | Every 5 minutes, plus Refresh now |
| Google: sign in | The household's own OAuth client, on a device at an https:// address (or at `localhost`) | Both ways | Every 5 minutes, plus Refresh now |
| iCloud | The Apple ID email and an app-specific password | Both ways | Every 5 minutes, plus Refresh now |
| A calendar server | Nextcloud, Fastmail, Radicale, Baïkal and others: the server's address, a user name and a password | Both ways | Every 5 minutes, plus Refresh now |
| Holidays | A country, and optionally a state or region | Shows events only | Made offline, again when the year turns |

## How a sync runs

- Every minute the engine starts the accounts that are due, two at a time. Each one:
  1. refreshes its list of calendars: new ones show up unmapped, and names follow the server;
  2. pulls each mapped calendar's changes since its cursor (a sync token, a ctag or a feed's
     ETag) and merges them;
  3. pushes the changes people made in Sunroom.
- Changes made in Sunroom also go out within a few seconds, without waiting for the next pull.
- **The Default calendar** (Settings → Calendars & Accounts) can be an account's calendar that
  works both ways: an event added without picking another calendar goes there, and out to the
  server. While it's unmapped (Sync off, or its account removed) or turns read-only, new events
  go to the household's first own calendar (Sunroom always keeps one), and it's the default
  again when it's back.
- **Merging** (PLAN §7.5):
  - a series is known by its calendar, its UID and the occurrence it changes;
  - an unchanged etag is skipped;
  - a change made here that is newer than the server's waits for its push, and the push lands
    on top of the server's latest version (it takes the server's etag);
  - anything else takes the server's version, with a revision first, so a server's removal shows
    in Recently removed;
  - ties go to the server.
- **A 412 on a push** (someone changed it on the server meanwhile) pulls, merges and tries once
  more.
- **Failures** never stop the plugin:
  - a refused password marks the account "needs reconnecting" and it waits for someone to connect
    it again;
  - anything else backs off (the interval × 2^failures, at most an hour, ±20 %), and after three
    failures in a row the account shows as an error;
  - the board shows a quiet pill ("Google hasn't answered since 9:10 AM. Showing what we had."),
    and the calendar's events stay.
- **Recurring events** are expanded by Sunroom itself (ADR 0003, ADR 0023); no server is ever
  asked to expand them.

## Secrets

- Passwords, keys and tokens are typed on a device or on the wall screen (a masked
  field on its own keyboard, behind the parent PIN), checked against the server, and stored
  encrypted (`credentials_enc`, Fernet under the plugin's key). They never come back to a browser.
- Back from Google's sign-in page, the browser lands on Calendars & Accounts with
  `?google=connected&account=<id>` (or `denied`, `expired`, `failed`); the page says how it went,
  opens a new account's calendars to pick, and takes the query off the address.
- A feed's address is a secret too (Google's secret address is the password to that calendar).
  It's stored encrypted and shown only with its secret part hidden:
  "calendar.google.com/…/private-3f9a…/basic.ics".
- A new `APP_SECRET_KEY` wipes every stored credential at boot; the accounts ask to be connected
  again.
- Logs name a server's host at most; never a token, a path, or an event's text.

## Private addresses

A server at home (a Nextcloud on the NAS, say) has a private address. Sunroom refuses private
addresses unless a parent:

1. ticks "This server is on your home network" on that account, **and**
2. adds the server under Settings → Network.

Every request is pinned to the address that was checked, and each redirect is checked again
(PLAN §12.6, ADR 0024).

## Server quirks

### iCloud

The app calls it **Apple** wherever the family reads it (0.10.0, ADR 0032): the chooser, an
account's name, its sheet, the source line on events and the error copy. iCloud stays the
technical name here.

- **Host:** start at `https://caldav.icloud.com`; the real host (`pNN-caldav.icloud.com`) is
  discovered, never hard-coded.
- **Passwords:**
  - only an app-specific password works (two-factor must be on), so a 401 with the right Apple ID
    password means the Apple ID password was typed;
  - changing the Apple ID password revokes every app-specific password, and the account then asks
    to be connected again.
- **Recurrences:** iCloud doesn't expand them on the server; Sunroom never asks it to.
- **Rate limits:** iCloud answers busy periods with undocumented 503s, and Sunroom backs off.
- **UIDs and lookups:** the same UID can't exist in two calendars, and looking an event up by UID
  doesn't work, so Sunroom reads by href (`calendar-multiget`).
- **Reminders** aren't reachable over CalDAV.
- **Colors** come as `#RRGGBBAA`.
- **Checked on a real account** with 0.3.0, from the wall screen: an event added on the wall
  reached Apple Calendar within seconds, and Apple Calendar's events came to the board.

### Google

- **The secret address** can lag the calendar by hours. It's read-only.
- **Sign-in:** Google refuses sign-in redirects to plain-http, raw-IP and local addresses, except
  `localhost`. The device-code flow doesn't allow Calendar.
- **Testing status:** an OAuth app left in "Testing" gets refresh tokens that last 7 days; publish
  it (no verification is needed for personal use).
- **The helper:** a service account sees a shared calendar only after it's added by its ID
  (`calendarList.insert`).
- **Sync tokens:** they can't be combined with a time window, so Sunroom keeps every series and
  expands it itself. An expired sync token (410) means a full listing.

### Other CalDAV servers

- **Radicale 3.8** decodes a path before checking it and refuses `:` `'` `"` `*` `?` `,` and
  names starting with a dot, escaped or not. A new event's file name is its UID when that's plain
  (`[A-Za-z0-9._@-]`, at most 120 characters), else its plain characters plus a hash of the UID.
  The same UID always gets the same name, so a retried create meets If-None-Match instead of
  making a duplicate.
- **Spelling of hrefs:** Radicale writes `@` in hrefs as `%40`; sabre (Nextcloud, Baïkal) leaves
  it raw. Sunroom spells every href one canonical way, so they match.
- **Namespaces:** Radicale and iCloud answer in a default XML namespace; elements are matched by
  namespace, never by prefix.
- **Discovery:** Radicale redirects `/.well-known/caldav` to `/`.
- **Forgotten sync tokens:** Radicale answers 409, sabre 403; either way Sunroom lists the
  calendar once and carries on.
- **Without sync-collection:** some servers lack it. Sunroom notices from `supported-report`, 405,
  415 or 501, and compares the ctag and each event's etag instead.
- **iCloud's home set:** it's an absolute URL with an explicit `:443`.

### Google: what Sunroom does about it

- **Pushes:** Sunroom reads Google's copy, lays its own fields on top, and PUTs with If-Match. A
  bare PUT would clear guests, reminders, colors, video links and attachments. A title, note or
  place Sunroom read but didn't change keeps Google's own text (its HTML, its length).
- **Changed occurrences:** Google calls them exceptions. Each has its own id
  (`<series id>_YYYYMMDDTHHMMSSZ`, the original start in UTC, or `_YYYYMMDD` for an all-day
  series) and its own etag.
  - A cancelled one carries only its id, the series' id and its original start.
  - One that changes on its own arrives without its series; Sunroom looks the series up once
    per sync and applies just that occurrence.
- **A changed series** is read again whole (listed by its iCalUID), so its exceptions stay right.
- **Sync tokens:** an expired token (410), or a 400 on one Google can't read, means one full
  listing.
- **Putting back an event** Google still holds as deleted (same iCalUID) gets a 409 on insert;
  Sunroom restores it instead.
- **Occurrences from another calendar:** an invitation to one occurrence of someone else's series
  shows as an event of its own.
- **Skipped:** `workingLocation` events, and the helper's own empty calendar.
- **Errors:**
  - `rateLimitExceeded`, `userRateLimitExceeded`, `quotaExceeded` and `dailyLimitExceeded` back
    off;
  - `accessNotConfigured` says to turn the Calendar API on;
  - a JWT turned down for clock skew says to fix the server's clock.
- **Tokens:** they stay on Google's hosts; Sunroom never follows a redirect with one. Tokens are
  kept for their hour and refreshed one request at a time.
- **Not yet checked against a real Google account** (the helper and Sign in with Google are
  tried live once the app is complete; the owner chose to wait): editing
  an unmodified occurrence by its instance id, listing a series' exceptions by iCalUID, the 409
  for a deleted event's iCalUID and restoring it, and whether changing an exception changes the
  series' etag. If it does, the next push meets one harmless extra 412 and pulls.

### Calendar addresses

- Outlook's published calendars use Windows zone names ("Eastern Standard Time"); `tzmap.py` maps
  them to IANA zones.
- Google's feeds write UTC times plus an `X-WR-TIMEZONE` header; `x-wr-timezone` turns them into
  local times so repeats keep their hour across daylight saving.
- **An address that stops working** (401, 403, 404 or 410: a feed taken down, or Google's secret
  address after a reset) asks to be connected again, like a refused password. The pill says so,
  the events stay, and Connect again (in the account's sheet) takes the new address. The calendar keeps its person and
  color, because its row follows the new address.
- **Public or secret:** Google's public address works only once the calendar is made public to
  everyone; the secret address doesn't need that, so it's the one the steps ask for. A calendar
  that's public already (a school's, a team's) can use its public address.

## Measured freshness

- **Google's secret address:** not measured yet. The owner's M2 check records how long a change
  in Google Calendar takes to reach the address, here.

## Testing

- **Engine tests:** run against a scripted server (`providers/fake.py`), covering changes both
  ways, the newer-local-change rule, the 412 retry, a refused password and backing off
  (`backend/tests/sync/test_engine.py`).
- **CalDAV and Google clients:** tested against scripted servers behind the real guarded client.
- **`just smoke-caldav`:** runs the CalDAV client against a real Radicale server in Docker, with
  the ICS fixtures imported. It's opt-in.
- **The test server** (`SUNROOM_TEST_MODE=1`) offers the scripted server for end-to-end runs:
  `POST /api/calendar-sync/_test/fake` and `PUT /api/calendar-sync/_test/fake/{account}`.
