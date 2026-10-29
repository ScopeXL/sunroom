# Privacy

**Status:** current as of version 0.17.0. Each release that changes what Sunroom stores or sends
updates this page.

Each Sunroom installation is run by the household that deploys it. The authors of this project
receive no data from any installation, except feedback someone there chooses to send (below).

## What Sunroom stores

Everything is kept on the server's `/data` volume: a SQLite database, its nightly backups and
photo files.

- The household's name, time zone and settings, and the place you give for the weather (a place
  name and its coordinates), which also times the screen's sunrise and sunset theme.
- Household members' names, whether each is a parent or a child, their color, and optionally a
  birthday and a photo.
- What the family adds: calendars and events (with their places, notes, people and reminders),
  lists, tasks, stars, rewards and routines, meals, and countdowns. Removed things wait in
  Recently removed before they're deleted, and an event's earlier versions are kept for 30 days,
  for Undo.
- Copies of the events in calendars you connect (below), so the screen works when they can't be
  reached.
- Photos you upload or put in the photos inbox, resized, with their location and other EXIF data
  removed (the date taken is read first); and copies of the photos a photo library you connect
  picks out (its previews, resized the same way, up to the number you choose), with which of
  its people, albums and tags you picked and the names it offered to pick from.
- Signed-in phones and paired screens: a short label, whose phone it is, and when it was last
  used. Phones' IP addresses are not stored or logged: the server keeps them in memory only for a
  few minutes, to slow down password guessing. (Behind a reverse proxy that doesn't say the
  browser is on https, the proxy's address is logged once, to help fix it.) About shows the
  address this device used (its URL), not the phone's own.
- The household password and the parent PIN, only as one-way hashes.
- "Add a phone" and pairing codes, as one-way hashes, usable once, for a few minutes.
- The passwords, keys and sign-ins of calendars you connect, and the key of a photo library you
  connect, encrypted with the server's secret key (`secret.key` in the volume, or
  `APP_SECRET_KEY`). Backups never include that key.

The server's log records each request's method, address path, result and duration, never what
was in it.

## What leaves the server

Only what the features below need, and only while they're in use. Turning a feature off in
Settings → Features stops it.

| What | Sent to | When | What they see |
|---|---|---|---|
| **The weather** | Open-Meteo (`api.open-meteo.com`) | About once an hour, once you've set where home is | The place's coordinates (rounded to about 10 m), the time zone and the units, and the server's internet address |
| **Finding your place** for the weather | Open-Meteo's place search (`geocoding-api.open-meteo.com`) | When a parent searches for a place | The words typed into the search |
| **Calendars you connect** | iCloud, Google, or the calendar server or address you add | Every 5 minutes or so (a calendar address as often as you chose) | Those calendars' events, both ways for iCloud, Google and other calendar servers; the sign-in you gave for them |
| **Photo libraries you connect** | The Immich server you add | Every 30 minutes, and when you check | Your API key for it, to that server only; copies of the photos it picks are kept on this server, resized, as uploaded photos are |
| **Check for updates daily** (off unless you turn it on) | GitHub (`api.github.com`) | Once a day | The server's internet address and Sunroom's version |
| **Send Feedback** (off unless the server's `SUNROOM_FEEDBACK_URL` names an address) | The address whoever runs the server chose, such as their own Discord channel | Only when someone taps Send Feedback, at most five times an hour | What they wrote (a problem or an idea, its title and words, and how to reach them if they gave it), Sunroom's version and how it's installed, and the server's internet address. Nothing from the calendar, the household or its people |

Holidays calendars are made on the server from a built-in list; nothing is sent for them.

Installing and updating download Sunroom from Docker Hub and GitHub (and, on a Raspberry Pi,
software from Raspberry Pi OS's own servers), as any software install does.

If you reach Sunroom through a service such as Cloudflare Tunnel, that service decrypts the
traffic on its way through and can see everything that passes, including the household password
when someone signs in. Tailscale doesn't: it's encrypted from end to end
([docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md)).

## What Sunroom does not do

- No analytics, tracking, advertising or telemetry.
- No third-party scripts or CDNs. Fonts are served by the app itself.
- No selling or sharing of data with anyone.

## Your control

- **Export** as JSON: Settings → Backup → Take Your Data with You → Export, on a phone or computer.
  It leaves out every password and key: the household password, the PIN, calendar passwords,
  and Google's client secret, which shows only as set (`***`).
- **Download** (Data Only, or Data & Photos: the database and every photo, to restore from):
  Settings → Backup. Keep it somewhere safe: it holds everything the family added.
- **Remove a backup:** Settings → Backup → Copies on the Server → the copy's Remove, from a
  parent's phone or a computer. The nightly copies, and the ones before an upgrade, Erase
  everything or a restore, are all listed there.
- **Remove a person:** Settings → Family → the person's row → Remove (with Undo).
- **Remove a synced account:** Settings → Calendars & Accounts → the account's row → Remove
  account. Its sign-in is deleted at once.
- **Sign out a device or unpair a screen:** Settings → Devices.
- **Erase everything:** Settings → Backup → Start Over → Erase everything, from a parent's phone
  or a computer, with the household password. Every person, calendar, event, list, task, meal,
  countdown, photo and setting is removed, and every phone and screen is signed out. One copy of
  the database from just before stays on the server in `backups/pre-erase`, so a mistake can be
  put right (docs/RESTORE.md); earlier nightly copies stay too. Remove them in Settings → Backup
  (or delete the files) to be rid of them as well.
- **Delete all data, backups included:** whoever runs the server removes the `sunroom_data`
  volume.

## Contact

Report security issues privately through the repository's GitHub security advisories (private
vulnerability reporting). Other questions can go in a GitHub issue, or in the Sunroom Discord.
Settings → Support Sunroom → Send Feedback opens GitHub's new-issue page in your browser with
what you typed and Sunroom's version filled in; you send it from GitHub, signed in there, and
Sunroom's server sends nothing. Where the server's `SUNROOM_FEEDBACK_URL` names an address,
Send Feedback sends what you typed there instead, as the table above says.
