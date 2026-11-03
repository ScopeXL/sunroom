# M6, batch 6: the owner's sixth notes, as tasks

Sunroom 0.11.0 is on the owner's wall and phones. The sixth set of notes is the widest yet (the
list is in "The owner's notes, mapped to tasks"). This file turns them into tasks for the Opus 5.5
session that builds them (PLAN §15, M6 → **0.12.0**). It was written on 2026-10-15 from a read of
the code at `30ba6fd` (v0.11.0); line numbers are from that commit and may have drifted a little.

The owner answered three questions while this was planned, and those answers are decisions here:
**no proxy setting, any address by default, `APP_ALLOWED_HOSTS` as an optional lock** (T13); the
two optional features (remote control, a photo frame) are in **`docs/M6-batch-7.md`**, not here;
and with "Return to the calendar after" on Never, **Settings on the wall stays open and only the
parent PIN relocks** (T5).

**Where this file lives.** `docs/M6-batch-6.md`, beside the earlier batches, committed as
`docs: M6 batch 6, the owner's sixth notes as tasks`.

## How to work through this file

- Read `CLAUDE.md` first: the priorities, the hard rules, the gotchas (and `docs/GOTCHAS.md`
  whole: this batch touches every area). Then UX §2 (words), §3, §4 (the Week board, Add, the
  Settings table), §6 (first run), §8 and §10, PLAN §6 (plugins), §7, §12, §13.4–13.7 and §14.7,
  and `docs/M6-batch-5.md` (the same shape as this file; its "As built" notes say what surprised
  the last session).
- The tasks are in five phases. **Phase 1, words and setup** (T1–T4): no schema. **Phase 2,
  settings and display** (T5–T9): one migration (T5). **Phase 3, the calendar** (T10–T12): two
  migrations (T10, T11). **Phase 4, the server and the data** (T13–T16): one migration (T15).
  **Phase 5** (T17) wraps up. Do them in order: the migrations chain, and later tasks build on
  earlier words. Inside a phase the tasks are independent unless a task says otherwise.
- **The gate is in two tiers, and only the quick tier runs between tasks** (CLAUDE.md "Definition
  of done", PLAN §14.7). Each task ends with the *quick gate*: `just quick`, the unit tests of what
  it touched (`just test-fe …`, `just test-py …`), its one end-to-end spec on one project
  (`just e2e e2e/<spec> --project=<name>`), then docs, a CHANGELOG line under `[Unreleased]`,
  `just scan` (the hook runs it), one commit per task (or per lettered part), subject
  `area: summary` plus the `Co-Authored-By` trailer. Tick the task's box here and note the commit,
  so a session that stops early can be resumed. **Never run the whole `just e2e`, `just check` or
  `just screenshots` between tasks.** The *full gate* runs once, in T17, and whatever it finds is
  fixed there.
- Read test output only when it fails: the recipes use the terse reporters.
- Every pydantic change ends with `just api-types`; check `frontend/src/api/schema.d.ts` for a
  shape named twice across the app (CLAUDE.md's `WeekOut` gotcha).
- Never deploy, bump, tag or push: the owner does that with the deploy skill when they ask. The
  release will be 0.12.0 (minor: the family sees most of this); the skill decides.
- When something here turns out to be wrong about the code, fix the task in the smallest way that
  keeps its intent, say so in the commit message and in the final report. Don't stop to ask unless
  the owner's intent is genuinely unclear.
- Never skip a failing check. Stop and report.
- Seed and fixtures stay synthetic (Ana, Sam, Mia, Leo; Sample Town). Nothing private, ever. The
  owner's name goes into About (T3), and the private-terms scan flags it everywhere but LICENSE's
  copyright line: T3 says what the owner decides first, and a hit is never allowlisted.

## The owner's notes, mapped to tasks

| Note | Task |
|---|---|
| Assign an event to the people its title names, on import and on add; keep the calendar's owner; several colors on a chip | T10, and "Answers" |
| Reminders don't save, or don't show when the event is reopened; a Default reminder setting | T11, and "Answers" |
| Remove TRUSTED_PROXIES; APP_ALLOWED_HOSTS defaults to any host; set up at `http://<HOST>:7867` with nothing to configure | T13, and "Answers" |
| A "Support Sunroom" section with a fun emoji: not for profit, donations welcome, crypto addresses, Patreon, a Feedback button that posts to GitHub | T9, and "Answers" |
| Refreshing the page after an update still shows the old version | T14, and "Answers" |
| Backup: the description; a switch, on by default, with how many daily and weekly copies to keep | T15 |
| Backup: a list of copies, newest first, each downloadable or removable; Back Up Now in the header; one Download with a choice; Export explained and named Export | T15 |
| Backup: restore from an uploaded .db or zip | T16 |
| Display → "Return to the calendar after: Never" still returns after 2 minutes | T5, and "Answers" |
| Remove "Only from a phone or computer."; don't isolate paired screens; tips that devices can do more; "phones or computers" → "devices" | T1 |
| Household → Location: the description | T4 |
| Show tips on by default | T5 |
| Where are the tips stored? | T5, and "Answers" |
| Four more colors | T6 |
| Tasks → Stars: several children, a Custom amount | T7 |
| Are errors surfaced? | T12, and "Answers" |
| The selected person's border is cramped | T8, and "Answers" |
| Setup: the password step's words and 8 characters; Home first and Family; You're Set for any screen; choose the theme | T2, and "Answers" |
| About: URL, no "Sunroom sees it as", Updates, the words, no "Not affiliated", the author | T3 (and T13 for "sees it as") |
| Optional: remote control of paired screens; a photo-frame screensaver | `docs/M6-batch-7.md` |

## Answers to the owner's questions

**Where the tips are stored.** One list, `frontend/src/features/tips/tips.ts`: `TIPS`, each tip
an `id`, its `text` and, for a tip about a feature, `needs` (the plugins that must be on for it to
show). `pickTip` (`tips.ts:103-113`) draws one at random among the tips whose features are on,
never the same twice in a row; `TipsBar.tsx` shows it under the board on the wall and on laptops
(never phones), a new one every half hour and on Next tip. `tips.test.ts:54-62` checks each tip:
at most 90 characters, a capital or a quote first, a period last, no emoji, unique ids. To change
a tip, edit that list; T5 writes this at the top of the file and adds two tips about what devices
can do. Twenty-five tips exist today; three of them say "phone or computer" (T1 rewrites them).

**Are errors surfaced?** Only in pieces, and mostly in Settings. A synced account that stops
working shows a quiet pill above the days (`features/sync/SyncPill.tsx`: "Google signed Sunroom
out.", "Apple needs its password again.", "Apple hasn't answered since 9:10 AM. Showing what we
had."), but only in the wall's Calendar room, never on a phone, in another room, in the header or
in the Today panel, and only once the account's status is `error` or `needs_reconnect`: a wrong
password says so at once; a server that doesn't answer is reported after three failed syncs in a
row (`plugins/calendar_sync/engine.py:50`, `ERROR_AFTER`), with the back-off between tries. The
rest each report in their own corner: a failing photo source in Settings → Photos & Screensaver,
a failed or week-old backup on the Backup page, the update check's problem on About, a feature
that crashed in Features ("Tasks stopped working."), the weather by hiding itself. The plugin
manifest even declares a `sync_error` banner that nothing reads. T12 builds one place for all of
them: a **Needs Attention** icon at the header's right end (beside the live-updates icon, drawn
only while something is wrong, as that icon is), on every room of the wall and on a phone's Today,
whose sheet lists each problem in a sentence with a button to the Settings page that fixes it.

**Several colors on one chip.** Yes. Today a chip belonging to one person has that person's tint
and a 6 px bar at the left in their color; a chip for several people has a neutral tint and up to
three small avatars (`features/calendar/EventChip.tsx:40-66`, `202-211`). T10 keeps the neutral
tint and the avatars and draws the bar in equal segments of each person's color, in household
order, up to four (so "Mia & Leo's Skate Lesson" has a two-color bar beside its two avatars).
The same bar goes on the Hours grid's blocks, the Today panel's lines, the Month cells and the
phone's lists. The tint stays neutral on purpose: mixing two tints reads as mud, and the names are
on the chip anyway (UX §10: color is never the only signal).

**Why a reminder doesn't come back.** Five things, found by reading the save and reopen paths:
(R1) the Remind row offers only None, 10 min, 1 hour and 1 day (`EventEditor.tsx:27-32`), and a
value it doesn't know shows as a blank button (`ui/ValueRow.tsx:165-169`): the seed's Soccer
practice reminds 30 minutes ahead and opens with an empty Remind. (R2) Changing "Just This One"
stores the reminder (and the title, place and notes) on the occurrence's own row, but the editor
reads them from the series (`EventEditor.tsx:148-163`), so the change saves and then doesn't show.
(R3) Saving sends one reminder, so an event with two keeps one. (R4) "All of Them" updates the
series' reminders but not the copies on its changed occurrences. (R5) A one-off exception the
server sends for a synced event is created without the people and reminders of its series. T11
fixes all five and adds **Default reminder**.

**"Return to the calendar after: Never" still returns after 2 minutes.** The setting
(`display_return_minutes`, 0 for Never) governs only the plugin rooms (Lists, Tasks, Meals,
Countdowns, Photos: `shell/DisplayShell.tsx:252-262`). Settings has its own hard-coded rule
(`:243-250`, `SETTINGS_LOCK_MS`): after 2 idle minutes it locks the parent grant **and navigates
home**, whatever the setting says, and `shell.spec.ts:631` even asserts it. Changing the setting
*in Settings on the wall* and waiting is exactly the way to see it. A second, deliberate rule is
not this bug: the board itself comes back to now after 2 minutes (this week, no filter, nothing
open; ADR 0031) and keeps doing so. T5 makes Settings follow the setting (the grant still locks
after 2 minutes; the page stays with Never) and applies Never to the one other place that sends
the wall home (a screensaver woken after 30 minutes).

**Why a refresh shows the old version.** The app is a PWA with a service worker, and the worker
answers every page load (a refresh and `location.reload()` included) from the copy of
`index.html` it cached when it installed (`frontend/src/sw.ts:26-30`); the server's `no-cache`
never gets a say while a worker is in charge. A new build is only noticed by an update check
(hourly, on a navigation, when the app becomes visible), and the new worker then *waits*
(`registerType: "prompt"`, `skipWaiting` only on a message) until every tab closes or someone taps
the phone's "New version · Refresh". On the wall that's the nightly rule (3 AM after 10 idle
minutes); open screens with a live stream refresh themselves when the server's hello names a new
version (`lib/update.ts`), which is why the wall usually catches up and a phone opened later
doesn't. The kiosk's browser treats the plain-http origin as secure, so it has a worker too. T14
makes page loads ask the server first (the server's `index.html`, with its new asset names,
whenever the server answers within three seconds; the cached copy only when it doesn't), which is
the one change that makes a refresh honest, and keeps the waiting-worker rule so an open old page
never loses its lazily loaded chunks.

**TRUSTED_PROXIES and APP_ALLOWED_HOSTS.** First a correction to the premise: `http://<HOST>:7867`
already works with nothing set for every numbered address, `sunroom.local` and the other LAN
suffixes, a bare name like `nas`, the container's own name and Tailscale's `.ts.net` names
(`web/hosts.py:27, 60-69`). What needs the two settings today is a public domain name through a
reverse proxy, and a proxy at all needs `TRUSTED_PROXIES`. What each setting guards, from a read
of `web/forwarded.py`, `web/hosts.py`, `web/csrf.py` and the rate limiters: the Host rule's single
job is DNS rebinding (a web page that points its own name at your home address, so the browser
treats it as the same site; CSRF can't stop it because the page's Origin and the Host are both the
attacker's name). Without the rule such a page could read Sunroom's public pages (`/api/version`,
`/api/setup/status`, `/api/display/state`), plant a name in About's "Recently reached at", claim a
server that hasn't been set up yet, and guess the password only within the global cap (50 tries an
hour for everyone). Believing a proxy's forwarded headers from anyone is nearly harmless: a faked
"https" changes nothing for anyone but the sender (browsers refuse a Secure cookie over http, and
HSTS over http is ignored), a faked client address only games the per-address sign-in limit (lock
a chosen address out, or dodge one's own lockout; the global cap holds), and a faked forwarded Host
only matters while the Host rule does. On a home network every connection the container sees comes
from a private address (phones reach the published port with their own 192.168.x address, a proxy
on the host from the Docker gateway, Tailscale from the same gateway), so "believe proxies on the
home network" is what makes every documented setup work with nothing set, and a connection
straight from the internet is never believed. The owner chose: **remove `TRUSTED_PROXIES`;
forwarded headers are believed from private, loopback, link-local and Tailscale addresses; any
Host is answered by default; `APP_ALLOWED_HOSTS` stays as an optional lock** that puts the strict
rule back for a household that puts Sunroom on the internet (T13). The two alternatives were
keeping the Host rule as it is (it costs one setting for a public name only), and believing every
header from anywhere (a proxy out on the internet could then fool the per-address limit).

**The Who picker's padding.** A cell (`ui/WhoPicker.tsx:73`) is `px-0.5 py-1` with a 3 px inset
ink ring when chosen; its width is a flex basis of 80 px around a 64 px avatar on the wall, so
there are 8 px either side of the avatar but only 4 px above it and under the name: the ring hugs
the top and bottom. T8 makes it `py-2` on the wall (8 px, matching the sides) and leaves phones
(56 px cells around 48 px avatars: 4 px all round already).

**Where the theme is chosen at setup.** On the "Your household" step (T2), after the week's first
day: Light / Dark / Auto with one line saying what Auto does, previewed at once on the page. Not a
step of its own (seven steps for one three-way choice), and not "Where's home" (it skips itself
with the weather off).

**The Feedback button.** It can't post to GitHub from the app: the page's security policy allows
the browser to talk to Sunroom's own server only (`connect-src 'self'`,
`backend/src/sunroom/web/headers.py:19-24`), and posting through the server would need a GitHub
token inside a public image. So Send Feedback collects the words and opens GitHub's new-issue page
in a new tab with the title, the words and the version filled in (`issues/new?title=…&body=…`);
the person signs in to GitHub there and taps Submit. On a paired screen (a full-screen browser
with no way back from another site) the sheet shows a QR code of that same link instead.

## Decisions (decided here, with the reason; the owner can overturn any at review)

| Question | Decision |
|---|---|
| Devices and screens | A phone, tablet or computer signed in with the household password is a **device**; a paired wall screen is a **screen** (its default name stays "Kitchen screen"). The app never says "phone or computer" for what any signed-in device can do, and a screen never shows what it can't do (pick a file, open another site, download) nor a line saying where to do it; two tips say devices can do more. The two exceptions keep their words: setup ("Finish setting up Sunroom on a phone or computer": no screen exists yet) and installing the app on a phone. Devices page groups: **Paired Screens** and **Signed-in Devices** (a page named Devices can't hold a group named Devices) |
| Setup | 8 characters (backend `MIN_PASSWORD_LENGTH`, `APP_PASSWORD`'s check, the seed's bound, the wizard); the name starts as **Home**, chips Home · Family · Our home; **Theme** Light / Dark / Auto on the Your household step, Auto by default, applied to the page as a preview and sent with `POST /api/setup`; the password step says devices and paired screens; You're Set says "a screen on the wall" |
| About | "URL" (no hint), "Recently reached at" stays; **Updates**, "Check for updates daily", "This is the latest version (checked at …)"; The Small Print: "Sunroom is open source, under the MIT licence.", "Made by …" with the author's name as LICENSE's copyright line has it (the private-terms scan flags it elsewhere: T3 says what the owner decides first), "Your data stays on your server…", "Weather by Open-Meteo." (UX §4 promised it; the sheet has it, About didn't); "Not affiliated…" and "Sunroom sees it as" go (the latter with T13) |
| Return to the calendar after | Governs **every room, Settings included** (2, 5 or 10 minutes, or Never). The parent grant still relocks after 2 idle minutes (viewing never needed it; a change asks the PIN again). A screensaver woken after 30 minutes goes home only when the setting is a number. The board's own return to now after 2 minutes is unchanged (ADR 0031) |
| Tips | `show_tips` defaults to **on**, and one migration turns it on for every existing household once (the owner's wish; a household can turn it off again); the list's file explains how to add one |
| Colors | Four appended after rose, so nobody's color moves: **copper** "Orange", **bark** "Brown", **slate** "Gray", **lime** "Lime"; light `#A54C00` `#7D5B40` `#50667C` `#637200`, dark `#CA7D44` `#AE8A6D` `#7B95B0` `#8B9D26` (OKLCH at the eight's lightness; the token test nudges). Twelve everywhere: backend lists and schema, `lib/colors`, tokens, pickers, docs |
| Stars | Several children at once (`member_ids`), one ledger row each; **Custom…** opens Give / Take and a Stepper 1–100; the toast names everyone |
| The Who picker | `py-2` on the wall, `py-1` on phones |
| Support Sunroom | A page before About; one constants file the owner fills (Patreon, addresses, the repo); empty entries aren't drawn; each address with a QR code and Copy where the clipboard exists (secure contexts only); **Send Feedback** opens GitHub's new-issue page with the kind, title, words and version filled in, a QR of that link on a screen. The page's heading carries the one emoji in the app's copy (💛, aria-hidden), the owner's choice; UX §2 records the exception |
| People from the title | A pure matcher `domain/people.py` mirroring quick add (whole words, case- and accent-folded, possessives, the full name and its first word, longest first, "May 5" is a date); `events.people_from_title` (one migration, backfilled true for synced events with no people) means "the title decides"; on import rows are written only when a name matched (owner + matches; owner-only events keep the read-time fallback so a changed owner still moves them); a hand-set Who turns the flag off and no sync re-adds anyone; a changed title re-matches while the flag is on; a renamed, added or archived person and a changed calendar owner re-match; R5 and P1 fixed |
| Chips in several colors | The 6 px bar in equal segments of up to four people's solids, household order; neutral tint; the avatars stay; the Hours blocks, Today panel lines, Month cells and phone rows get it too |
| Reminders | Three states per event: its own rows, explicitly none (`events.reminders_off`), or the household's **Default reminder** (`default_reminder_minutes`, Settings → Calendars & Accounts under Default calendar; one migration for both); the wall resolves the default; the Remind row offers Default (…) · None · 5, 10, 15, 30 min · 1, 2 hours · 1 day before and labels any stored value; a "this one" edit reads the occurrence's own row (a new route); All of Them reaches the one-offs; server-made exceptions copy the series' people and reminders |
| Needs Attention | A plugin hook `problems()` and core's own (a stopped feature, a failed or stale backup while nightly is on, low free space); `GET /api/problems`; the icon at the header's right end on the wall and a pill on a phone's Today, both opening one sheet with a sentence and an "Open …" button per problem; the Settings list marks the page; the board's SyncPill goes; `banners` goes from the manifest |
| Proxies and hosts | **No proxy setting.** Forwarded headers are believed from loopback, link-local, private (RFC 1918, fc00::/7) and Tailscale (100.64/10) peers, never from a public one; `X-Forwarded-For` takes the right-most hop outside those ranges, else the left-most. **Any Host by default**; `APP_ALLOWED_HOSTS` set → the strict rule as today. A leftover `TRUSTED_PROXIES` line is ignored with one warning in the log. The CSRF "https but the proxy didn't say so" branch stays, reworded. uvicorn keeps `proxy_headers=False`. Accepted residuals, written in the ADR: a page rebound from the home network can read public pages and plant a name in About; any home device can game the per-address sign-in limit |
| The service worker | Navigations are **network-only with a 3 s wait and the precached `index.html` as the fallback** (`NetworkOnly` + `PrecacheFallbackPlugin`, registered before the precache route so "/" is covered); no runtime page cache (a newer page cached offline would name files the old precache lacks); updates still wait (`prompt`); the hourly update check no longer leaks an interval. Accepted: after a refresh a phone may show "New version · Refresh" once for a build it already runs |
| Backups | Household `backups_enabled` (on), `backups_keep_daily` 1–30 (14), `backups_keep_weekly` 0–12 (8); the nightly job reads them live; Back Up Now works with nightly off; pre-migrate and pre-erase copies unaffected. The list shows four kinds (nightly, before an upgrade, before Erase Everything, before a restore), newest first; `DELETE` by name, refused on a paired screen (as Erase is) and while a copy is being written; **Data Only** is a fresh checked copy streamed and deleted after; **Data & Photos** is the zip; the sheet is **Download Which?**; the Export group explains itself and its button is **Export** |
| Restore from a file | **Stage, check, then re-exec**: the upload is streamed to `/data/restore/`, checked with the CLI's own checks (moved into `db/restore.py`), summarised; applying asks the household password (the same bar as Erase: nothing added since the copy survives, except in the pre-restore copy), writes a marker, tells every screen (`server.restarting`), and the process re-runs itself (`os.execv`; the PID and the container stay); boot applies the marker right after taking the lock and never loops on a bad one. `just dev`'s reload worker can't exec, so it touches a watched file instead |
| Verification | Two tiers (above); each task names its spec and project; T17 runs the full gate once. **0.12.0**; the deploy skill decides |
| Database | **Four migrations**, in order: T5 (`show_tips`), T10 (`people_from_title`), T11 (`default_reminder_minutes`, `reminders_off`), T15 (the backup policy). The 0.11.0 fixture `202610151730.sql` exists (checked 2026-10-15); T15 builds the 0.12.0 fixture for the newest revision |
| The ADR | **One, 0034**, in 0033's shape, with a row per decision above; it changes parts of 0017 (the Host rule and the proxy list), 0027 (no Restore button), 0028 (tips off by default; the emoji rule of 0013 as narrowed by 0028), 0029 (the eight colors in one picker), 0030 (the board's quiet pills), 0031 (Settings' 2-minute return). ADR 0034 is started in T2 and gains its rows task by task |

## Before the first task

1. `just check` must be green at the commit this file landed on (one after `30ba6fd`; confirm,
   don't assume). `CHANGELOG.md`'s `[Unreleased]` is empty there.
2. `backend/src/sunroom/migrations/released.lock` ends with `202610151730`, and
   `backend/tests/fixtures/db/202610151730.sql` exists. Four migrations come in this batch (T5,
   T10, T11, T15), in that order; only the newest needs a fixture for the release, built in T15
   (`docs/RELEASING.md`, "The fixture database").
3. `just screenshots` once, before any task, into `.screenshots/before-0.11.0/` (gitignored), the
   "before" for T17's review.
4. The Support page's links and addresses (T9) are the owner's: `support.ts` starts with empty
   values and the page hides what is empty; the owner fills it in before the release.

## Tasks

### T1 Devices, and nothing a screen can't do

- [x] Done (commit: "settings: devices and paired screens, and nothing a screen can't do")

**Owner's note.** "Remove all the 'Only from a phone or computer.' texts. If they can see the
setting it means they are on a device that supports the feature. Audit the app and make sure the
app isn't isolating 'Paired Screens'. Add tips that connected devices have more control of the
app. Rename any combination of 'phones or computers' to simply 'devices'."

**What exists.** There is no "is this a kiosk" helper: each component reads
`session?.device_kind === "kiosk"` (`features/settings/BackupPage.tsx:36-39` is the pattern), the
sync components take `kiosk` as a prop (`features/sync/AccountsSection.tsx:51`), and the shell
context is only `display | phone` (laptops are `display`). Where the kiosk is treated differently
(all of it is right, except the words): Backup hides the downloads, Export and Start Over and shows
two "from a phone or computer" lines (`BackupPage.tsx:117, 132`) plus "Only from a phone or
computer." (`:149`); `MemberSheet.tsx:188-191` hides the photo picker and says "Add a photo from a
phone: More, then Settings, then Family."; `DevicesPage.tsx:60, 165-176` hides Pair a Display on
the screen itself (right: a screen doesn't pair screens); `PhotosRoom.tsx:43-44, 74, 85, 89` shows
a QR with "Add photos from a phone: open Sunroom, then More, then Photos." where Add Photos would
be; `AddAccount.tsx:136, 172-183, 225-256` hands Google's key file and sign-in page to a phone with
a QR ("From a phone", "Do this from a phone", "Or add it from a phone", "Scan this with a parent's
phone, or open Settings → Calendars & Accounts on a phone or computer.") and `:560-576` says "On a
phone or computer, open appleid.apple.com and sign in."; `AccountSheet.tsx:228-231` hides Sign In
Again with "Sign in again from a phone: More, then Settings, then Calendars & Accounts." and
`:529-534` says "On a phone or computer, make a new app-specific password at appleid.apple.com,
then type it here."; `EventSheet.tsx:111-116, 159` asks the PIN ("Changing events on this screen
asks for the PIN."). The server refuses a kiosk only for Erase (`meta/router.py:266-267`, "Erase
everything from a phone or computer."), join codes without a parent (`auth/router.py:88`) and
child-safe event edits (`calendar/router.py:54`). Every other hit of the words, with its file and
line, is in the build list below; the tips are `features/tips/tips.ts:67, 82, 86`.

**Build.** One rule, then the list. The rule (goes into UX §2 as a paragraph "Devices and
screens", see Docs): *device* for anything signed in with the password, *screen* / *paired
screens* / *this screen* for a kiosk; a screen never shows a control it can't use and never says
where else to go; where a thing genuinely can't be done on a screen (a file, another website), the
screen shows the QR code that already exists for it, worded "from a device". The two exceptions
keep their words: setup (`DisplayEntry.tsx`'s "Finish setting up Sunroom on a phone or computer",
`auth/service.py:47`) and installing the app on a phone (`InstallScreen.tsx:112`, tip `install`).

(a) **Remove, on the kiosk, the lines that point elsewhere** (and the controls they stood in
for stay hidden): `BackupPage.tsx:117`, `:132` (T15 rebuilds this page; take the three lines out
here so the e2e and unit expectations change once), `:149` loses "Only from a phone or computer.";
`MemberSheet.tsx:190` (the Photo group is simply not drawn on a kiosk); `AccountSheet.tsx:230`
becomes the QR pattern `AddAccount.tsx` uses (`PhoneShortcut`) with the line "Sign in again from
a device:" above the code, since Google's page can't open on a screen.

(b) **Rename, everywhere the words appear** (verbatim new strings):
- `DevicesPage.tsx:159`: "No screen paired yet. Open Sunroom on the screen you want to pair and
  type its code here."; `:179` group title "Phones & Computers" → **"Signed-in Devices"** (if
  `designRules.test.ts`'s Title Case check wants "Signed-In", use that).
- `AddDeviceSheet.tsx:50-51`: "On the new device, …" for "On the new phone or tablet, …"; the
  computer sentence stays (it's about typing the address).
- `SignInScreen.tsx:126-127`: "On a device that's already signed in, open Settings, then Devices,
  then Add a Device (on a phone, Settings is under More)."
- `AboutPage.tsx:72`: "Any of these works from a device on your home network."
- `FamilyPage.tsx:173`: "Settings, approvals and changing events on paired screens ask for it.";
  `:174`: "Set a parent PIN so children can't open Settings on paired screens."; `:251`:
  "Changing or removing events on paired screens asks for the PIN. Adding and checking off never
  do."
- `CalendarsPage.tsx:76`: "Hidden on paired screens"; `:356` switch "Show on paired screens".
- `EventEditor.tsx:436`: "A reminder shows on paired screens." (T11 rewrites the row; keep the
  word).
- `CountdownsRoom.tsx:131`: "Hidden from paired screens."; `CountdownEditor.tsx:171` switch
  "Show it on paired screens".
- `screensaver/data.ts:154` toast: "Started the screensaver".
- `PhotosRoom.tsx:43`: "A code that opens Photos on a device"; `:44`: "Add photos from a device:
  open Sunroom there, then Photos."; `:83` and `PhotosTab.tsx:52`: "Photos added from any device
  show here and on the screensaver."; `Saver.tsx:217`: "Add photos from a device to see them
  here."
- `AddAccount.tsx:215`: "From a device"; `:232`, `:250`: "A code that opens Add an Account on a
  device"; `:236`: "Or add it from a device"; `:248`: "Do this from a device"; `:252-253`: "Scan
  this with a parent's phone, or open Settings → Calendars & Accounts on a signed-in device.";
  `:562-563`: "On another device, open appleid.apple.com and sign in."; `AccountSheet.tsx:532`:
  "Make a new app-specific password at appleid.apple.com on another device, then type it here."
- `PinDialog.tsx:161-162`: "Forgot it? A parent can change it on a signed-in device under
  Settings → Family."
- `DisplayEntry.tsx:239`: "On a signed-in device, open Pair a Display (under More on a phone,
  Settings → Devices on a computer) and type this code."; `:146`, `:154` keep "your phone" where
  they describe scanning the QR with a camera.
- `InstallScreen.tsx:80-82`: "…or with a code from a device that's already signed in (Settings,
  then Devices, then Add a Device; on a phone, Settings is under More)." ("Add a phone" there is
  stale.)
- `ListsTab.tsx:47`, `ListsRoom.tsx:62`: "wall" → "paired screens", "phones" → "devices", keeping
  the sentence's sense.
- Backend: `meta/router.py:267`: "Erase everything from a signed-in device, not a paired screen.";
  `auth/router.py:177`, `:253`: "A paired screen is for everyone."; `household/screen.py:125`:
  "Only a paired screen wakes itself this way."; `plugins/screensaver/plugin.py:26` (the Features
  hint): "The family's photos on paired screens while nobody's using them."; the default label
  "Kitchen screen" (`auth/schemas.py:104, 109`, `DisplayEntry.tsx:268`, `PairCode.tsx:22, 28`)
  stays: it's a name.
- Setup's lines (`SetupWizard.tsx:143-144, 183, 445`) are T2's.

(c) **Tips** (`tips.ts`): `:67` → "Photos: add them from any signed-in device, several at once.";
`:82` → "On a signed-in device, Settings → Backup → Download saves a copy of it all." (T15's
button); `:86` stays. Two new tips, no `needs`: `devices-do-more`: "Signed-in devices can do more
than this screen: downloads, photos, restore and Google's sign-in." and `devices-settings`:
"Change a setting on any signed-in device and every screen follows at once."

**Tests.** `just test-fe src/features/settings src/features/sync src/features/tips` (update
`EraseSheet.test.tsx:149`, the kiosk case: no line at all; `AccountSheet.test.tsx:244`;
`tips.test.ts` passes the new tips through its rules). `screensaver.spec.ts:124` ("Add a photo
from a phone") and `screenshots.spec.ts:393, 406` get the new words. Run
`just e2e e2e/first-run.spec.ts --project=desktop` (the wall's Backup page at `:186-240` must show
no pointer line) and `just e2e e2e/screensaver.spec.ts --project=display-1080p -g photo`.

**Docs.** UX §2: the "Devices and screens" paragraph (above) after "Time and date words"; UX §4
Settings table: Devices row ("Signed-in Devices"), Family, Backup ("The wall shows nothing it
can't do") and Photos rows; UX §8 rows 751 and 754 ("Photos, none", "Devices, no screens"); the
checklist line 859 ("on the kitchen screen it doesn't" stays true). PLAN §2 glossary: the Phone
row's "User sees" becomes "Device (a phone, tablet or computer)". ADR 0034 row.

**CHANGELOG** (Changed). "Sunroom says 'devices' for the phones, tablets and computers signed in
with the household password, and 'paired screens' for the wall. A paired screen no longer shows
what it can't do, nor lines saying to do it from a phone; two tips say what signed-in devices can
do that a screen can't."

**As built.** As planned, with these differences:
- *ADR 0034 starts here*, not in T2: this task already has a row.
- *Backup on a screen*: with its line gone, the Take Your Data with You group had nothing left on
  a screen, so it isn't drawn there (T15's layout for a screen, early).
- *A person's sheet on a screen* keeps its photo row when there is a photo, to remove it (a
  screen can do that, and the owner asked that screens not be cut off); with no photo the row
  isn't drawn. Neither says where to add one.
- *The shared QR block*: Add an Account's code-and-line block became `DeviceShortcut`, exported
  from `AddAccount.tsx`, and the account sheet shows it ("Sign in again from a device:", a code
  of Calendars & Accounts). Its words are a `lead` prop: the design-rules test reads any
  `title="…"` literal as a heading, and these are sentences.
- *The tip* `devices-do-more` as planned was 96 characters, over the list's 90, and "than this
  screen" is wrong on a laptop (laptops show tips too). It reads "Signed-in devices can do more:
  downloads, adding photos, restores and Google's sign-in." (87).
- *Words the list missed*, changed in the same spirit: the join screen ("Sign In on This
  Device", "The other device shows it too.", "Another device made this code…"), the erase
  sheet ("signs out every device and screen"), and the countdown switch's hint ("Off for a
  surprise: only signed-in devices show it.").
- `first-run.spec.ts`'s Erase case now also checks that the wall's Backup page has no export
  group and no "from a …" line; it passes on `desktop`, and the photo cases of
  `screensaver.spec.ts` pass on `display-1080p`.

### T2 Setup: 8 characters, Home, Family, the theme, and any screen

- [x] Done (commit: "setup: 8 characters, Home and Family, the theme, and any screen")

**Owner's note.** "Household password step: 'The kitchen screen never needs it.' should not define
a paired screen; say 'Paired screens don't require it.' The requirement should be 8 characters or
more, not 12. Your household step: the name should default to 'Home' and be the first button;
instead of 'The family' make it 'Family'. You're Set references 'kitchen screen' again; rephrase
for any paired screen. Add a step, or a setting to an existing step, to choose the theme; default
to Auto and say what Auto means."

**What exists.** `features/onboarding/SetupWizard.tsx`: the password step `:160-224` (lead `:183`
"Everyone at home signs in on their phone with this one password. The kitchen screen never needs
it."; hint `:199` "12 characters or more. A few words together work well."; error `:200` "Use at
least 12 characters."; the 12 checked at `:175, 190, 217`); the household step `:226-364` (`:236`
`useState("Our home")`; chips `:291` `["Our home", "Home", "The family"]`; the zone `:304-331`;
"The week starts on" `:334-345`; `POST /api/setup` `:243-251` with password, name, zone, week
start and the phone's time format); the PIN step's lead `:445` ("…keeps children out of Settings
on the kitchen screen…"); the done step `:135-156` (`:143-144` "To put Sunroom on a kitchen
screen, open More, then Pair a Display, when the screen shows its code. Or type the household
password on the screen itself."). The side list and the phone's "N of 6" are `SetupFrame.tsx`. The
minimum is `auth/password.py:29` `MIN_PASSWORD_LENGTH = 12` with `password_problem` at `:76-82`
("Use at least 12 characters. A few words together work well."), used by `meta/setup.py:95-99`
and `cli.py:165`; `core/config.py:93-96` checks `APP_PASSWORD` ("must be at least 12 characters
(use a passphrase)"); `meta/testing.py:111` bounds the seed's password at 12. Tests with the words:
`backend/tests/test_setup.py:49-52`, `test_config.py:51`. The theme: `household.theme`
(`household/models.py:34-37, 84`, `ThemeName = Literal["auto","light","dark"]`,
`household/schemas.py:15`); `SetupIn` (`meta/setup.py:51-56`) has no theme; `lib/theme.ts`
`applyAppearance` (`:94-114`) puts `data-theme` on `<html>` (a phone on Auto follows the phone)
and remembers it under `sunroom.appearance` (`:168-180`), which `public/theme-boot.js` paints
first; the wizard runs in `PhoneShell tabs={false}` with no household settings, so it paints from
that memory or the phone. The Display page's hint words: "Auto turns dark at sunset and light at
sunrise." / "Auto turns dark at 7 PM until a location is set in Household."
(`DisplayPage.tsx:29-31`).

**Build.**

(a) **Eight.** `MIN_PASSWORD_LENGTH = 8`; `password_problem`: "Use at least 8 characters. A few
words together work well."; `core/config.py:93-96`: "must be at least 8 characters (a few words
together work well)"; `meta/testing.py:111` `min_length=8`; the wizard's three checks and its hint
"8 characters or more. A few words together work well." and error "Use at least 8 characters.";
`test_setup.py:49-52` and `test_config.py:51` (a 7-character password is refused, an 8-character
one taken); PLAN §12.1 "12+ characters" → "8+"; README has no number (check with grep "12
character"); `docs/DEPLOY.md` likewise.

(b) **The password step's lead** (`:183`): "Everyone at home signs in on their devices with this
one password. Paired screens don't need it." (With `APP_PASSWORD`, `:182` stays.) The PIN step's
lead (`:445`): "It keeps children out of Settings on paired screens. Adding events and checking
off tasks never ask for it."

(c) **Home and Family.** `:236` `useState("Home")`; `:291` `["Home", "Family", "Our home"]`.

(d) **The theme row**, after "The week starts on" (`:334-345`), in the same shape:

```tsx
<div className="flex flex-col gap-2">
  <span className="text-body font-semibold">Theme</span>
  <Segmented label="Theme" value={theme} onChange={pick} options={[
    { value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "auto", label: "Auto" },
  ]} />
  <p className="text-secondary text-ink-soft">Auto is dark from sunset to sunrise once Sunroom knows where home is (the next step), and from 7 PM until then. On a phone, Auto follows the phone.</p>
</div>
```

`pick` sets the state and previews it: the same call the Display page's Theme row makes to show
its choice at once (find it: `applyAppearance` or the hook around it in `lib/theme.ts`; on a phone
Auto means the phone's own, which is what the wizard page already shows). The `POST /api/setup`
body gains `theme`. Backend `SetupIn.theme: ThemeName = "auto"` and `run_setup` writes
`home.theme = body.theme`. The step list's name "Your household" stays. (Segmented is the control:
three words on one row, as the week's first day is.)

(e) **You're Set** (`:143-144`): "To put Sunroom on a screen on the wall, open it there: it shows
a code. Type that code under More, then Pair a Display, or type the household password on the
screen itself."

(f) **ADR 0034** is started here (`docs/adr/0034-m6-batch-6-the-owners-sixth-notes.md`, in
0033's shape: Status, Date, Context: the sixth notes and this file; an empty Decision table that
each task fills; Consequences grown task by task), plus its row in `docs/adr/README.md`.

**Tests.** `just test-py tests/test_setup.py tests/test_config.py tests/test_auth.py` (add to
`test_setup.py`: a setup with `theme: "dark"` leaves `GET /api/settings` saying dark; the default
is auto); `just test-fe src/lib/theme.test.ts src/styles` (the rules test reads the new literals:
"Theme" and the options are labels, sentence case). `e2e/first-run.spec.ts:12-135` walks the
wizard on a phone: it asserts "6 of 6", "You're set" and "open More, then Pair a Display" (keep
the last words in (e) so the assertion holds, or update it). Run
`just e2e e2e/first-run.spec.ts --project=phone-chromium`. Screenshots `setup-household-*` change
(T17 reviews).

**Docs.** UX §6 "First run": step 3's words ("Everyone at home signs in on their devices with this
one password. Paired screens don't need it."; "8 characters"), step 4 (the chips Home, Family, Our
home; the field starts as Home; the Theme row and its line), step 7 (the new words). PLAN §12.1
("8+ characters", "names the family, confirms the time zone, picks the theme"). ADR 0034 rows
(8 characters: a passphrase is still the hint; the theme at setup).

**CHANGELOG** (Changed). "Setup asks for a household password of 8 characters or more (it was
12), starts the household's name as Home, offers Family as a choice, and lets you pick Light, Dark
or Auto before you finish. Its words say 'devices' and 'paired screens'."

**As built.** As planned, with three differences:
- *The preview* is a new `lib/theme.previewTheme(choice)`: the Display page's Theme row only
  saves, and the shell applies the household's theme, but the wizard has no household yet, so it
  puts the appearance on the page itself (`applyAppearance` with the phone's shell, so Auto is
  the device's own) and remembers it, so a reload mid-wizard paints it first. `theme.test.ts`
  has a case.
- *The end-to-end run* is on `display-1080p`, not `phone-chromium`: the wizard's walk in
  `first-run.spec.ts` drives its own phone context and skips itself on every other project. It
  now checks that the name starts as Home, that Auto is chosen, that Light shows on the page at
  once (`data-theme`), that the server kept it (`GET /api/settings`), and the new You're Set
  words ("under More, then Pair a Display").
- `test_setup.py` gained three cases (the theme kept, Auto by default, an unknown theme
  refused) and `test_config.py` one (`APP_PASSWORD` of 7 refused, 8 taken). `.env.example`,
  `docs/DEPLOY.md` and the kiosk installer's `.env` template said 12 too.

### T3 About: URL, Updates, the latest version, and the author

- [x] Done (commit: "settings: About says URL and Updates, and credits Open-Meteo"; the author line waits for the owner)

**Owner's note.** "'This device uses' to 'URL'. Remove 'Sunroom sees it as' (with the proxies
decision). 'New Versions' to 'Updates'. 'Check for new versions daily' to 'Check for updates
daily'. 'This is the newest version' to 'This is the latest version'. Remove 'Not affiliated with
Google or Apple.' In The Small Print, add me as the author: [the owner's name, as in LICENSE]."

**What exists.** `features/settings/AboutPage.tsx`: Connection rows `:45-78` ("This device uses"
`:52` with the TRUSTED_PROXIES hint `:56`; "Sunroom sees it as" `:64-65`; "Recently reached at"
`:71-72`); `UpdatesGroup` `:93-172` (title "New Versions" `:118`; the note `:120-122` "Once a day
Sunroom asks GitHub for the newest version. GitHub sees your server's address."; the switch "Check
for new versions daily" `:126`; the status `:110-115` "This is the newest version (checked at
…)."; "Check Now" `:166`); "The Small Print" `:80-86` ("Sunroom is open source, under the MIT
licence." / "Not affiliated with Google or Apple." / "Your data stays on your server. No
analytics, no ads, no outside scripts."). Backend words: `meta/updates.py:78-91` 409 "Turn on
Check for new versions daily first."; `LICENSE` names the owner already. UX §4's About row also
promises "Weather by Open-Meteo", which the page never had (only the forecast sheet,
`WeatherBlock.tsx:197`).

**Build.** Row label "URL", no hint (T13 removes the data behind the hint and the "Sunroom sees it
as" row; do the words here, and leave the two TRUSTED_PROXIES hints in place for T13 to delete
with their fields, so this task doesn't touch the diagnostics shape). Title "Updates"; the note
"Once a day Sunroom asks GitHub for the latest version. GitHub sees your server's address."; the
switch "Check for updates daily"; the status "This is the latest version (checked at …)."; the
backend 409 "Turn on Check for updates daily first." The Small Print, in order: "Sunroom is open
source, under the MIT licence.", "Made by <the author's name, as LICENSE's copyright line has it>.", soft "Your data stays on your server. No
analytics, no ads, no outside scripts.", soft "Weather by Open-Meteo." ("Not affiliated…" goes.)

**The scan.** `scripts/private_scan.py` treats the owner's name as a private term everywhere but
LICENSE's copyright line (`:110-130`, "the owner's intentionally public git identity"), and it
flagged this file's draft three times. Before this task the owner decides, and ADR 0034 says
which: extend that exemption to the one About line (a change to the scan script the owner
approves), take the name off the private-terms list, or drop the line. The session builds the one
the owner chose and never allowlists a hit on its own (CLAUDE.md, hard rule 1).

**Tests.** `just test-py tests/test_updates.py`; `just test-fe src/styles` (Title Case:
"Updates"); `e2e/shell.spec.ts:85-107` asserts the About page's words ("Live updates: connected",
"Free space", the switch, Check Now, "…is available. In Sunroom's folder…"): update any that name
the old title or switch, then `just e2e e2e/shell.spec.ts --project=phone-chromium -g About`.

**Docs.** UX §4 About row (the new words; "Made by…"; the Open-Meteo line now true); PLAN §13.6
("Check for updates daily"). ADR 0034 row.

**CHANGELOG** (Changed). "About says URL, Updates and 'Check for updates daily', 'This is the
latest version', and names Sunroom's author in The Small Print."

**As built.** Everything but the author's line, which waits for the owner: the scan question
above was never answered in this session, so "Made by …" isn't in the page, the docs or any
commit (ADR 0034 says so). Once the owner chooses, it is one `<Text>` after the licence line in
`AboutPage.tsx`, the matching words in UX §4's About row, and a CHANGELOG line. The rest as
planned: URL (its TRUSTED_PROXIES hint stays for T13 to delete with its field), Updates, "Check
for updates daily", "This is the latest version", the 409's words (now asserted in
`test_updates.py`), "Weather by Open-Meteo." and no "Not affiliated…". `shell.spec.ts`'s About
case also checks URL, Updates, Open-Meteo and the missing line; it passes on `phone-chromium`.
PRIVACY.md and DEPLOY.md named the switch too.

### T4 Household → Location: what it's for, and what leaves

- [x] Done (commit: "weather: the Location note says what it is for and what leaves")

**Owner's note.** "In the Location section change the description to something like 'Used for
weather and sunrise/sunset data. Selected city is sent to Open-Meteo.' Polish the text."

**What exists.** `features/weather/PlaceSearch.tsx:153-203`: the group "Location" (`:162`), its
note (`:163`): "For the weather and the sunset. The city you search for and where it is go to
Open-Meteo; nothing else does."; the value, or "Not set yet. Until it is, it gets dark at 7 PM."
(`:167`); the buttons "Change" / "Set the City" (`:176`) and "Remove" (`:187`). `PRIVACY.md:40-41`
says exactly what goes: the coordinates (rounded) hourly for the forecast, the typed words for the
search.

**Build.** The note: "Used for the weather, and for sunrise and sunset. Only your city goes to
Open-Meteo, when you search for it and for the forecast; nothing else leaves." (Honest to
PRIVACY.md: the search words and the place's coordinates are "your city".)

**Tests.** No unit test reads the note; `just test-fe src/features/weather`. No e2e covers the
Location section; `just e2e e2e/a11y.spec.ts --project=phone-chromium -g Household` if a case by
that name exists (the phone Settings loop at `:228-333`), else none.

**Docs.** UX §4 Household row: the note's words. ADR 0034: no row.

**CHANGELOG** (Changed). "Settings → Household says what the location is for, and that only your
city goes to Open-Meteo."

**As built.** As planned. No end-to-end case reads the note (the phone a11y loop opens the
page but has no case named Household), so the quick gate was `just quick` and
`just test-fe src/features/weather`.

### T5 Return to the calendar after, tips on by default, and where the tips live

- [x] Done (commit: "shell: Settings follows Return to the calendar after; tips on by default")

**Owner's note.** "'Return to the calendar after' isn't working properly. I changed it to 'Never'
and it still brings me back to the calendar after 2 minutes." "Show tips should be enabled by
default." "Where are the 'Tips' stored? I want to be able to alter them easily."

**What exists.** "Answers" has the cause. `shell/DisplayShell.tsx:58` `BACK_TO_NOW_MS`, `:60`
`SETTINGS_LOCK_MS`, both 2 minutes; `:222-228` the board's back-to-now (keep); `:243-250`:

```ts
useEffect(() => {
  if (room !== "settings") return;
  return whenIdle(SETTINGS_LOCK_MS, () => {
    if (session?.grant_expires_at) lockNow();
    void navigate({ to: home });
  });
}, [room, session?.grant_expires_at, home, navigate, lockNow]);
```

`:252-262` the plugin rooms' return (`returnMinutes = settings?.display_return_minutes ?? 5`;
`if (!inPluginRoom || returnMinutes <= 0) return;`). `features/screensaver/Saver.tsx:134-143`: a
saver woken after 30 minutes or more calls `backToNow()` and navigates home, whatever the setting.
`DisplayPage.tsx:179-193`: the row "Return to the calendar after", hint "When nobody has touched
the screen.", options Never / 2 min / 5 min / 10 min. `shell.spec.ts:631` asserts "two idle
minutes send the wall home"; `screensaver.spec.ts:42-66` relies on Never keeping the wall in Tasks.
Tips: `household.show_tips` `Boolean, default=False` (`household/models.py:105-106`), added by
`202610091752_household_week_layout_and_tips.py:24-27` with `server_default=sa.false()`; the
switch at `DisplayPage.tsx:156-157`; `test_household.py:23` asserts False; `shell.spec.ts:900-938`
"tips off by default"; the strip is 56 px under the board (`TipsBar.tsx`), mounted in
`DisplayShell.tsx:369` for every room; `/api/_test/reset` re-inserts the household row with its
defaults, so once the default is on, every wall e2e has the strip. The tips: `tips.ts` (see
"Answers").

**Build.**

(a) **Settings follows the setting.** The effect at `:243-250` keeps only the lock:
`whenIdle(SETTINGS_LOCK_MS, () => { if (session?.grant_expires_at) lockNow(); })`. The return
effect at `:252-262` takes Settings in: `const leaves = inPluginRoom || room === "settings"; if
(!leaves || returnMinutes <= 0) return;` (and `updateDisplay({ panel: null })` stays). The two
comments say so (Settings' grant locks after 2 minutes; the page leaves with the other rooms,
after the household's minutes, never with Never: ADR 0034 narrows ADR 0031). `Saver.tsx:134-143`:
after 30 minutes `backToNow()` still runs; `navigate(home)` only when
`settings?.display_return_minutes` is a number above 0 (read it the way `DisplayShell` does). The
row's hint: "How long Lists, Tasks, Settings and the other rooms stay open with nobody touching the
screen. The board itself still comes back to today after 2 minutes."

(b) **Tips on.** `household/models.py:105-106` `default=True`;
`just db-revision "household: tips on by default"` with `batch_alter_table("household")`
`alter_column("show_tips", server_default=sa.true())` and `op.execute("UPDATE household SET
show_tips = 1")` (once, for every household: the owner's wish; the CHANGELOG says a household can
turn it off again). `test_household.py:23` → True; `test_migrations.py`: a 0.11.0 household comes
out with tips on. (Four migrations chain in this batch: this one's `down_revision` is
`202610151730`; `just db-revision` sets it.)

(c) **The tips file.** Replace `tips.ts`'s header docstring (`:1-5`) with: "Tips under the board
(UX §3, ADR 0028, on by default since ADR 0034): one thing Sunroom can do, in the family's words.
To add or change one, edit `TIPS` below: an `id` nobody else uses, the `text` (at most 90
characters, a capital letter or a quote first, a period last, no emoji; `tips.test.ts` checks),
and `needs` naming the plugins it's about, so it shows only while they're on. `pickTip` draws one
at random, never the same twice in a row." The two new tips are T1's.

**Tests.** `just test-py tests/test_household.py tests/test_migrations.py`;
`just test-fe src/features/settings src/features/tips`. `shell.spec.ts:631`: the case becomes two:
with the default (5 min), after two idle minutes the rail shows the padlock again (the grant
locked) and Settings is still open; after five, the wall is home; and with
`PATCH /api/settings {display_return_minutes: 0}`, after six idle minutes Settings is still open
(use the spec's idle fast-forward helper). `shell.spec.ts:900-938`: "tips on by default" (the strip
is there on a fresh wall; turning the switch off removes it). Every wall spec now runs with the
strip; `a11y.spec.ts:377-389` already covers the board with a tip. Run
`just e2e e2e/shell.spec.ts --project=display-1080p -g "idle|tips"` (whatever the two cases are
named). By hand in `just display`: Settings → Display → Never, wait three minutes in Settings.

**Docs.** UX §3:76 ("After 5 any room returns to the Calendar room, in that same view (Settings →
Display → Return to the calendar after picks the minutes, or Never; Settings leaves with the other
rooms and its parent grant locks after 2 minutes, ADR 0034)"); UX §4:436 (the Settings paragraph's
"Settings auto-lock after 2 minutes idle" → "the grant locks after 2 minutes idle; the page leaves
with Return to the calendar after"); UX §4:445 (the Display row: "Show tips (on by default since
0.12.0…)"; "Return to the calendar after … Settings included"); UX §3:148 ("it's off until someone
turns it on" → "on by default"); PLAN §12.3's idle paragraph. ADR 0031: Status "Accepted; Settings'
own 2-minute return narrowed by ADR 0034". ADR 0034 rows (the return; tips on).

**CHANGELOG** (Fixed). "Settings → Display → Return to the calendar after now counts for Settings
too: with Never, the wall stays where it is (the parent PIN still locks after 2 minutes)." (Changed)
"Tips under the board are on for everyone; turn them off in Settings → Display → Show tips."

**As built.** As planned, plus one thing the plan didn't foresee:
- *The PIN pad on a page left open.* With Never, a Settings page stays open after its grant
  locks, and a live update (a phone signing in refreshes Devices; a reconnect's `hello`
  refreshes everything) re-reads a parent's data, which the server refuses: `asParent` would
  then have raised the PIN pad with nobody at the screen. `lib/parent.askPinOnlyWhen(rule)` lets
  the display shell say "only within 30 s of a touch" (`lib/idle`); a background refusal fails
  quietly and the page says so where it shows errors. `parent.test.ts` is new (the pad and the
  retry; no pad without a recent touch; the rule undone).
- `shell.spec.ts`: the Compact-rail case now waits five idle minutes to be sent home from
  Settings (it relied on the old two); a new case on `display-1080p` unlocks Settings, sees the
  padlock come back after two idle minutes with the page still open, goes home after five, then
  unlocks again, taps Never on Settings → Display (the owner's own steps, waiting for the
  PATCH) and stays six minutes with the padlock and no PIN pad; "tips on by default" checks the
  strip on a fresh wall and its removal when they're turned off. The plan's by-hand check in
  `just display` wasn't done: the end-to-end case drives the same steps on the page's clock.
- The migration is hand-written (Alembic's autogenerate can't see a server default change),
  `202610161454`, with `test_migrations.py`'s new case from the 0.11.0 fixture.

### T6 Four more colors

- [x] Done (commit: "colors: four more, Orange, Brown, Gray and Lime; the person's color clears")

**Owner's note.** "Add 4 more color choices for calendars/events/etc. A family of 5 with
individual colors runs out of options for shared calendars quickly."

**What exists.** Eight colors, named in `household/models.py:16-26` (`PERSON_COLORS` and the
words), `household/schemas.py:13` (`PersonColor`, imported by the calendar, countdowns and sync
schemas), `plugins/spec.py:36` (`COLORS`, validated at `:177-178`), `calendar_sync/service.py:203`
(`COLOR_ORDER`, the pick order for a synced calendar), `household/service.py:119-123`
(`next_color`); `frontend/src/lib/colors.ts:7-16` (`COLORS`: value and word, "One list for every
color picker"); `styles/tokens.css:44-61` (the solids, light and dark) and `:111-159`
(`[data-person="…"]` rules, `--p`, `--p-tint`, `--p-text`); `tokens.test.ts:117` (`PEOPLE`; four
contrast checks per color at `:177-201`; "defines the eight person colors" at `:205-210`);
`ui/ColorPicker.tsx` (a grid of 2 or 4 columns, the free ones first) and `ui/ColorDots.tsx` (a row
of dots that wraps); the UX §7 table at `:682-693` and the word list in §10:838. Tests that assume
the order: `e2e/sync.spec.ts:282`, `AccountSheet.test.tsx:198`. The values are OKLCH at one
lightness: light L 0.52–0.55 (white text ≥ 5:1), dark L 0.63–0.65 (ink ≥ 4.6:1); hues 29, 100,
150, 200, 250, 290, 330, 360. The gaps: an orange (hue ~55), and then only muted colors are far
enough from the eight (a brown, a cool gray, a yellow-green between olive and moss).

**Build.** Append four, in this order, to every list above (appending keeps everyone's color and
every picker's order; `next_color` still hands new people the first free one):

| Token | Word | Light | Dark | OKLCH (light / dark) |
|---|---|---|---|---|
| `copper` | Orange | `#A54C00` | `#CA7D44` | 0.52 0.145 55 / 0.66 0.12 55 |
| `bark` | Brown | `#7D5B40` | `#AE8A6D` | 0.50 0.06 60 / 0.66 0.06 60 |
| `slate` | Gray | `#50667C` | `#7B95B0` | 0.50 0.045 250 / 0.66 0.05 250 |
| `lime` | Lime | `#637200` | `#8B9D26` | 0.52 0.145 118 / 0.66 0.14 118 |

(Computed with the standard OKLCH → sRGB matrices; white on the light solids 5.3–6.1:1, ink on
the dark ones 5.3–5.6:1 at a flat surface.) `tokens.css`: four `--name-l` / `--name-d` pairs and
four `[data-person="name"]` blocks; `tokens.test.ts` `PEOPLE` and "the twelve person colors"; run
`just test-fe src/styles` and, if a check fails on a warm wall tint, lower that color's lightness
a step (the eight were nudged the same way in M0) and record the final hex in UX §7. Backend: the
four names and words, `COLOR_ORDER` (after rose), `PersonColor`; `just api-types`. Frontend:
`lib/colors.ts`; the docstrings of `ColorPicker` ("eight" → "twelve"; the grid gains a row) and
`ColorDots` (thirteen dots wrap to two rows in the wall's Add panel: accepted, dots aren't chips).
Fix **C1** while here: "The person's color" in an event's Color dots never clears a color already
chosen, because the form always sends `clear_color: false` (`calendar/data.ts:167, 173`) and the
backend treats `color: null` as "leave it" (`service.py:495-505`): send `clear_color: true` when
the dots' choice is none and the event had a color (countdowns do, `CountdownEditor.tsx:90`).

**Tests.** `just test-py tests/test_household.py tests/sync/test_accounts.py tests/plugins`
(`test_household.py:125` and `test_accounts.py:210-235, 250` name colors); `just test-fe src/styles
src/ui src/features/sync src/features/calendar` (`ColorPicker.test.tsx`, `AccountSheet.test.tsx`,
a case in `EventEditor.test.ts` for `clear_color`). `just e2e e2e/sync.spec.ts
--project=display-1080p -g color` (the pick-order case at `:272-300`). By hand in `just display`:
Settings → Family → a person → the twelve swatches in both themes; Add → Event → Color.

**Docs.** UX §7 table (four rows, the names explained: copper, bark, slate and lime are things
seen from a sunroom); UX §10:838 word list; UX §4 Family row ("the twelve named colors"); PLAN §2
if it says eight. ADR 0034 row (changes 0029's "eight").

**CHANGELOG** (Added). "Four more colors for people and calendars: Orange, Brown, Gray and Lime."
(Fixed) "Choosing 'The person's color' for an event that had its own color now clears it."

**As built.** As planned: the four hex values passed every contrast check in `tokens.test.ts`
at the first try, so UX §7 records them unchanged. Two differences:
- *C1* is fixed in `AddPanel.fieldsFor` (the change path, which knows the event), not in
  `calendar/data.ts`: it sends `clear_color: true` when the dots say "The person's color" and the
  event had one, at every scope; `EventEditor.test.ts` has two cases.
- *The end-to-end case* runs on `desktop`, not `display-1080p`: the pick-order case in
  `sync.spec.ts` skips itself on every other project. It now expects twelve swatches, the free
  ones first.
ADR 0013's status and 0029's picker row are annotated. The by-hand look at the twelve swatches
in both themes is left to T17's screenshots (`settings-change-a-person`).

### T7 Stars for several children, and a custom amount

- [x] Done (commit: "chores: stars for several children at once, and a custom amount")

**Owner's note.** "The 'Stars' section should allow the person to select multiple children. Also,
add a 'Custom' button that lets them choose how many to give or take."

**What exists.** `features/chores/SettingsChores.tsx:461-531` `AdjustGroup`, under Settings →
Tasks while stars are on: a `WhoPicker` of children, single (`value={kid ? [kid] : []}`,
`onChange={(ids) => setKid(ids[0] ?? null)}`); `ChipRow label="How many"` with −5, −1, +1, +5,
+10 (U+2212 minus); `TextField "What for (optional)"`; the button "Give Stars" / "Take Stars",
disabled until a child is picked; the toast "Gave Mia 5 stars" / "Took 1 star from Mia"
(`chores/data.ts:454-480`, through `asParent`). `POST /api/chores/points/adjust` takes
`{member_id, points, reason}` (`plugins/chores/schemas.py:221-224`, points −1000..1000, reason
120 chars; `service.adjust` `:595-614`, 0 refused with "Give or take at least one star."; one
`PointAdjustment` row). `WhoPicker` has `multiple` (the event's Who uses it); `ui/Stepper` is a
whole number with − and + (`label`, `min`, `max`, `words`); UX §4: "A chip that opens something is
outlined with a chevron and never filled" (`ui/Chip`'s `opener`). Tests:
`tests/chores/test_chores.py:547-556`, `helpers.py:86-95`; nothing covers the form.

**Build.**

(a) Backend: `AdjustIn.member_ids: list[str]` (1–20 items, each active, deduplicated; 422
`unknown_member` otherwise) replaces `member_id`; `service.adjust` loops, one row per child in
one transaction, returns `list[StarsOut]`; the route and `helpers.py` follow. `just api-types`.

(b) The form: `kids: string[]` with `WhoPicker multiple`; the chips gain **Custom…** (an opener
chip; when it's on, two rows appear under it: `Segmented label="Give or take"` Give / Take, and a
`Stepper label="How many stars"` 1–100, starting at the last preset's size); `points` is the
preset, or ± the stepper's value by the direction; the button says Give Stars or Take Stars by the
sign and is disabled until a child is picked; the mutation sends `member_ids`; the toast names
everyone: "Gave Mia 5 stars", "Gave Mia and Leo 5 stars", "Took 1 star from Mia, Leo and Sam"
(a `names(list)` helper: two joined with "and", more with commas and "and"). The reason clears on
success as now; the children stay picked.

**Tests.** `just test-py tests/chores` (two children → two rows and two balances; 21 ids → 422;
an archived child → 422); `just test-fe src/features/chores` (a unit test for `names()` and the
custom amount's sign). A new case in `e2e/chores.spec.ts` on `display-1080p`: a parent (PIN) opens
Settings → Tasks, picks Mia and Leo, Custom…, Take, 3, Take Stars → the toast "Took 3 stars from
Mia and Leo" and both balances on Stars & Rewards drop by 3. Run
`just e2e e2e/chores.spec.ts --project=display-1080p -g "stars"`.

**Docs.** UX §4 Tasks row: "**Stars** (give or take stars to one or more children at once: −5,
−1, +1, +5, +10 or Custom…, with a reason)". PLAN §11.3 if it lists the route's shape. ADR 0034
row.

**CHANGELOG** (Added). "Settings → Tasks → Stars gives or takes stars for several children at
once, and Custom… picks any number from 1 to 100."

**As built.** As planned, with two small differences. The route answers `PointsOut` (`{stars:
[...]}`, as `GET /api/chores/points` does) rather than a bare list. The words live in
`chores/words.ts`: `namesText` (the plan's `names()`), `starsToast` and `customPoints`, with
cases in `words.test.ts`; Custom… opens on the chosen preset's direction and size, and closing
it goes back to that preset. `test_chores.py` has two new cases (two children, a name twice,
two balances; none, 21 and an archived child refused with nothing written); the e2e case in
`chores.spec.ts` unlocks Settings with the PIN on the wall, picks Mia and Leo, Custom…, Take,
3, and checks the toast, both balances 3 lower, and the children still picked.

### T8 Room around a chosen person

- [x] Done (commit: "ui: room around a chosen person in the Who picker on the wall")

**Owner's note.** "Anywhere a person is selected, it gives them a border which is good, but there
isn't enough padding on the top/bottom so it feels scrunched. Expand the padding to match the
left/right padding, or one you recommend."

**What exists.** "Answers" has the measure. `ui/WhoPicker.tsx:73`, the cell:
`press select-fill flex min-w-0 flex-col items-center gap-1 rounded-button px-0.5 py-1
aria-pressed:bg-p-tint aria-pressed:ring-[3px] aria-pressed:ring-ink aria-pressed:ring-inset`;
the basis is 80 px (lg avatars, 64 px) or 72 px (tap, 56 px) on the wall, 56 or 48 px on phones;
the name under the avatar at caption size. Every picker of avatars with names goes through it
(Add's Who, Stars, routines, tasks, "Who did it?", rewards, lists, meals, countdowns). The other
"selected person" looks (a Chip with an avatar in the calendar and account sheets, the Filter
menu's rows, the phone's Show row, "Who's using this phone") have their own, roomier padding and
don't change.

**Build.** `py-2` when the shell is `display`, `py-1` on a phone (the cell's class is built with
`display` in scope; if not, add it from `useShell()`). The row is 8 px taller on the wall; nothing
measures it (the Who row sits inside the scrolling form). Check `wrap` mode ("Who did it?") and the
Stars picker (T7) by eye.

**Tests.** `just test-fe src/ui/WhoPicker.test.tsx` (add an assertion on the wall cell's `py-2` if
the test reads classes); `just e2e e2e/a11y.spec.ts --project=display-1080p -g "tap"` (the
tap-target journey, if a case by that name exists; else `e2e/calendar.spec.ts --project=display-1080p
-g Who`).

**Docs.** UX §4 "The Who picker": "Selected: an ink ring, the person's tint and the name in bold,
with 8 px of room above the avatar and under the name on the wall (ADR 0034)". ADR 0034 row.

**CHANGELOG** (Fixed). "Picking a person no longer squeezes the ring against their avatar and
name on the wall."

**As built.** As planned (`WhoPicker.test.tsx` checks `py-2` on the wall and `py-1` on a phone).
The plan's end-to-end fallbacks didn't exist (no a11y case named "tap", no calendar case named
"Who"), so the run was the two that do measure it on `display-1080p`: `chores.spec.ts`'s
five-people Who row (still one line) and the a11y journey "the wall screen, from first light to
Settings" (tap targets and gaps). Both pass. "Who did it?" (`wrap`) and the Stars picker get
the same cell and are left to T17's screenshots.

### T9 Support Sunroom

- [x] Done (commit: "settings: Support Sunroom, with Send Feedback to GitHub")

**Owner's note.** "Add a new setting section labeled 'Support Sunroom' with a fun emoji. A quick
about description indicating it's not for profit, but donations are welcome. Areas for crypto
addresses, Patreon, and a Feedback button that opens a modal that will post to the project's
GitHub repository."

**What exists.** Settings pages are `features/settings/pages.ts:3-13` (`SETTINGS_PAGES`, key →
title, in order: family, features, calendars, display, household, devices, removed, backup,
about) and the `PAGES` map in `SettingsScreens.tsx:25-35` (TypeScript wants one entry per key);
plugin pages slot in after calendars (`:44-56`); no router change for a new key. A page is
`Group`s (`parts.tsx:7-45`: `title`, `note`, children in a card) of `Row`s; `ui/Sheet` is the
modal (`:46-206`); `ui/QrCode` draws a QR as one SVG path (`value`, `label`, `className`); the
external-link pattern is `<a target="_blank" rel="noreferrer noopener" className="font-semibold
underline">` (`MealsRoom.tsx:349-356`, `AddAccount.tsx:568-575`), and on a kiosk the same places
show plain text, because the kiosk's Chromium runs `--kiosk` and a new tab would be a full-screen
dead end (`kiosk/sunroom-kiosk:231-249`). CSP: `connect-src 'self'` and `form-action 'self'`
(`web/headers.py:19-24`), so no fetch to GitHub and no form posting there; a link navigates freely;
`Referrer-Policy: same-origin`. The repository is `ScopeXL/sunroom`
(`core/updates.py:24`); the version and install kind come from `GET /api/admin/update` /
diagnostics (`UpdateOut`, `SUNROOM_INSTALL_KIND`). `designRules.test.ts:155-168, 237-258` checks
Title Case on `title: "…"` in `pages.ts`, on `<Group title>` and `<Sheet title>` literals, on h1–h3
text and on buttons of two to five words; the e2e lists of pages are `a11y.spec.ts:23-35`
(`SETTINGS`) and `screenshots.spec.ts:30-43` (`PAGES`). `navigator.clipboard` exists only in a
secure context (https, localhost, the kiosk's flagged origin), not on a phone over plain http.
UX §2 bans emoji in the app's copy; the owner asked for one here.

**Build.**

(a) `pages.ts`: `support: "Support Sunroom"` between `backup` and `about` (About stays last);
`SettingsScreens.tsx`: the import and `PAGES.support`; `a11y.spec.ts` `SETTINGS` and
`screenshots.spec.ts` `PAGES` gain "support".

(b) `features/settings/support.ts`, the owner's constants, documented at the top ("Filled by the
owner; an empty value hides its row"):

```ts
export const REPO_URL = "https://github.com/ScopeXL/sunroom";
export const PATREON_URL = "";
export const ADDRESSES: readonly { name: string; address: string }[] = [
  // { name: "Bitcoin", address: "" },
];
```

(c) `features/settings/SupportPage.tsx`:
- Group **"Support Sunroom"** whose heading is followed by `<span aria-hidden="true"> 💛</span>`
  (the text literal stays plain for the rules test and the screen reader); note: "Sunroom is free
  and open source, and not for profit: no ads, no accounts, no subscription. If it has earned a
  place on your wall, a donation helps it keep growing." Rows: **Patreon** (when set: on a device
  a `ListRowLink`-style row opening the URL in a new tab; on a screen the row shows the URL and a
  QR code of it, `size-40`); one row per address: the name, the address (`break-all`, selectable,
  `font-mono` if a mono class exists, else as is), a QR code of the address (`size-40`; wallets scan
  these), and **Copy** (quiet button) only when `navigator.clipboard?.writeText` exists; its toast
  "Copied the Bitcoin address". With nothing set, the group shows only the note.
- Group **"Feedback"**, note: "Found a problem, or have an idea? Feedback goes to Sunroom's page
  on GitHub, where everyone can see it. It needs a GitHub account; nothing from your calendar is
  sent." Button **Send Feedback** → `FeedbackSheet` (title "Send Feedback"): `Segmented label="What
  is it?"` "Something's wrong" / "An idea"; `TextField label="In a few words"` (max 80);
  `TextField multiline label="What happened, or what would help"` (max 1,500; if `TextField` has no
  multiline, a plain `<textarea>` with the field's classes); a soft line "Sunroom {version} on
  {install kind} is added for you. Nothing else is."; the footer: on a device **Open GitHub** (an
  `<a target="_blank" rel="noreferrer noopener">` styled as the primary button, href from
  `feedbackUrl()`; disabled look until the title has words) and **Cancel**; on a screen, a QR code
  of the same link under "Scan this with your phone to finish on GitHub." (the title only in the
  link there, so the code stays readable) and **Done**. `feedbackUrl({kind, title, body, version,
  install})` builds `${REPO_URL}/issues/new?title=…&body=…` with `encodeURIComponent`, the body
  "{words}\n\n---\nSunroom {version}, {install kind}", the kind as the title's prefix ("Problem: " /
  "Idea: "), and caps the whole URL at 2,000 characters (GitHub's page accepts longer, QR codes
  don't).

(d) `PRIVACY.md` "Contact": "Settings → Support Sunroom → Send Feedback opens GitHub's new-issue
page in your browser with Sunroom's version filled in; the server sends nothing."

**Tests.** `just test-fe src/features/settings src/styles` (a `support.test.ts` for `feedbackUrl`:
the encoding, the prefix, the cap; the rules test on the new literals: "Support Sunroom",
"Feedback", "Send Feedback", "Open GitHub", "Copy", "Cancel", "Done"; the page's h3 with the
aria-hidden span passes because the literal is the plain title). `just e2e e2e/a11y.spec.ts
--project=phone-chromium -g Settings` (the phone loop opens every page in `SETTINGS`, the new one
included; it's one of the two long journeys, `test.slow()`). By hand in `just display`: the page
on the wall with a sample address in `support.ts` (don't commit it): the QR codes, Copy present;
on a phone over http, no Copy.

**Docs.** UX §4 Settings table: a "Support Sunroom" row before About; UX §2 "What never appears":
"…emoji in the app's own copy (one exception: the heart beside Support Sunroom, ADR 0034)"; UX §5
Settings (phone). ADR 0034 row (the page, the GitHub link and why, the emoji).

**CHANGELOG** (Added). "Settings → Support Sunroom: what Sunroom is (free, open source, not for
profit), how to support it, and Send Feedback, which opens a GitHub issue with the version filled
in."

**As built.** As planned, with these differences:
- *Copy* shows on every device, not only where `navigator.clipboard` exists: `lib/copy`
  (Add an Account's Copy) falls back to a hidden textarea and works over plain http, so the
  plan's premise didn't hold. A paired screen has no Copy (nowhere to paste) and no links.
- *The words box* is a plain `<textarea>` on devices only. The wall's keyboard types into
  `<input>`s only (`lib/keyboard`), and the screen's link carries the title only anyway.
- *New small pieces*: `ui/ButtonLink` (a link with the button's look, no address while
  "disabled"), `ui/ListRow`'s `ListRowAnchor` (the row as a plain link to another site),
  `Group`'s `mark` (drawn after the title, hidden from screen readers) and a `Group` with
  `null` children drawing no empty card (the support group before the owner fills it in).
- *The link's cap* cuts the words by halving (a letter can take one character of the link or
  nine), with an ellipsis, never the title or the version.
- Tests: `support.test.ts` (the link's encoding, prefixes, the cap, the install's words) and
  `SupportPage.test.tsx` (with the constants mocked: Patreon as a link or a code, an address
  with Copy or without, an empty one hidden, the sheet on a device and on a screen). The plan's
  `-g Settings` matches only the wall's journey; the phone loop is "a phone, signed in", run on
  `phone-chromium`, and the wall's journey on `display-1080p` too. Both pass.
- `support.ts` is still empty: the owner fills in Patreon and the addresses before the release.

### T10 Whose event it is: the people a title names, and chips in their colors

- [x] Done (commit: "calendar: the people a title names, and chips in their colors")

**Owner's note.** "When a calendar event is imported from a connected account, or added manually,
we need to automatically assign who it belongs to if the event has any data indicating such. An
event on my calendar called 'Mia & Leo's Skate Lesson' should still be imported owned by the
person the calendar belongs to, but also assign Mia, Leo to the event so it shows up in the
Person view, and any audits in the future. Also, is there a way to use multiple colors on the event
to indicate who it belongs to if multiple people are assigned?"

**What exists.** Who an event is for is `EventMember` rows (`calendar/models.py:129-137`; no rows
means Everyone); a calendar has `owner_member_id` (`:60`); a synced event with no rows is shown as
its calendar's owner at read time only (`calendar/occurrences.py:90-97`, sync calendars only; a
local calendar's owner means nothing). The People view takes a multi-person event into each
person's column (`PeopleView.tsx:32-41`). Sync writes through `engine.pull` → `ctx.calendar
.upsert_synced` (`plugins/context.py:227-262`) → `calendar/sync_merge.merge_chunk` (`:173-223`) →
`_merge_one` (`:247-303`): a created event is `_new_row` + `_content` then `flush` (`:263-264`),
an updated one `_content` (`:292`) then `_rule` and `_set_overrides`; `_content` never touches the
people or reminders, so a hand-set Who on a synced event survives a re-import today, and nothing
records whether people were set by hand. `_upsert_override` (`:391-415`) creates a server-made
exception with no people and no reminders (**R5**). `merge_chunk` already imports
`household.models.Household`; `household/service.py:105` `active_members` lists the people. Manual
paths: `calendar/service.py` `create_event` (`:530-560`, `members = _check_members(body.member_ids,
ctx) or []`), `update_series` (`:563-641`), `update_occurrence` (`:644-791`); the editor always
sends `member_ids` (`EventEditor.tsx:105, 154`), so after any save of a synced event its owner
becomes an explicit row and a later owner change won't move it (**P1**). Quick add already reads
names when a *new* event is typed (`features/calendar/quickAdd.ts` `readPeople` `:319-343`,
`inTitle` `:606-614`: longest name first, possessives, "with", "&" and "and", a month word beside a
number is a date, a possessive name stays in the title) and never on edit; `domain/` has no text
matching but allows `re` and `unicodedata` (`tests/test_purity.py:13-28`); names are unique
case-insensitively (`household/service.py:136`). The chip: `EventChip.tsx:40-66` `chipTone` (one
person: `bg-p-tint` and a `border-l-[6px] border-p` bar; several or Everyone: `bg-line/60` and up
to three xs avatars, `PeopleMarks` `:202-211`); the same rule in `MonthView.tsx:126-142`,
`PhoneLists.tsx:52` and its `Dots` (`:196-206`, already several colors), `TodayView.tsx:48-55`,
`TodayPanel.tsx:212-218`, `HoursGrid.tsx:457, 471-477`. Colors are custom properties
(`tokens.css:44-61`, `[data-person]` `:111-159`, `--p` via `light-dark()`); React's `style={{}}`
goes through the CSSOM, which the CSP nonce allows and the rules test permits (it bans hex and
injected `<style>`). `calendar/revisions.py` `_fields()` (`:27-36`) rebuilds an `Event` from a
snapshot's keys, so a new NOT NULL column needs a default there or Undo of a pre-upgrade revision
fails.

**Build.**

(a) **The matcher**, `backend/src/sunroom/domain/people.py`: `people_named(title: str, names:
Sequence[str]) -> list[str]`, the matched names as given, in the order of `names`. Rules, the same
as quick add's so both sides agree: fold per character (`unicodedata.normalize("NFKD", ch)[0]
.lower()`, length-preserving, so Zoë and Zoe meet); candidates are each full name and, for a name
of several words, its first word unless that word is another member's whole name (Ana and Ana
Sofia: "Ana Sofia's recital" → Ana Sofia; "Ana's recital" → Ana); a candidate under two letters
never matches; longest first, whole words (`(?<!\w)…(?!\w)`, spaces as `\s+`, an optional
`'s`/`’s`), the matched span masked so a shorter name can't match inside it (Samba, Leopard);
MONTH_WORDS (quick add's list) beside a digit, or after "5th of", is a date. Cases in
`tests/domain/test_people.py`: "Mia & Leo's Skate Lesson" with Mia, Leo, Ana → Mia,
Leo; "Dentist" → nothing; "May 5 picnic" with May → nothing; "Swim with May" → May; the Ana
Sofia pair; "Take Leo to soccer" → Leo; "Zoe's party" with Zoë and the reverse; "Samba class" with
Sam → nothing; "Mia’s" (curly); "mia leo" → Mia, Leo in household order; a one-letter name never
matches. `tests/test_purity.py` passes as is.

(b) **The column.** `Event.people_from_title: Mapped[bool] = mapped_column(Boolean,
default=False)` after `created_by_member_id`, with the comment "True while the title decides the
people (set on import, or by a title with names on add); a Who set by hand turns it off; with no
rows and True, the read-time owner fallback applies." Migration `just db-revision "events: people
from the title"`: `add_column(... nullable=False, server_default=sa.false())`, then `UPDATE events
SET people_from_title = 1 WHERE source = 'sync' AND id NOT IN (SELECT event_id FROM
event_members)` (a synced event with no rows was never a hand choice: the owner fallback applied
anyway). `revisions.py` `_fields()`: a key missing from a snapshot takes the column's Python
default. `test_migrations.py`: from the 0.11.0 fixture, synced rows without people come out
flagged, the rest not. `EventOut` gains `people_from_title` (not `OccurrenceOut`: cached per
calendar version, and the frontend doesn't need it).

(c) **Core helper** `backend/src/sunroom/calendar/people.py`: `matched_ids(title, members)`
(`people_named` over the names, back to ids); `async assign(session, row, calendar, members) ->
bool`: `wanted = ([owner] if calendar.kind is SYNC and calendar.owner_member_id else []) +
matched`; writes rows **only when a name matched** (otherwise removes any rows so the fallback
applies), sets the flag true, replaces rows only when they differ; `async rematch(session,
calendar_ids=None) -> list[str]`: every non-deleted event with the flag → `assign`. Called from
`sync_merge.update_calendar` and `service.update_calendar` when the owner changes, from
`household/router.py` after a person is added, renamed, archived or restored (same transaction),
and once in `app.py`'s lifespan after `manager.boot()` (so the backfilled events get their people
without waiting for a change; writes only on change, cheap).

(d) **Sync.** `merge_chunk`: `members = await active_members(session)` once per chunk, handed
down. `_merge_one`: created → after the flush, `await people.assign(...)`; updated → after
`_content`, `if existing.people_from_title: await people.assign(...)` (`kept_local` untouched: the
local change wins). `_set_overrides` / `_apply_partial` / `_upsert_override` take `calendar` and
`members`; **R5:** a new override copies the master's `EventMember` and `EventReminder` rows and
the two flags (`people_from_title`, and T11's `reminders_off`); an existing override with the flag
re-runs `assign` on its own title. `upsert_synced` and the plugin don't change (core side; the
plugin never learns names).

(e) **Manual.** `create_event`: `member_ids` non-empty → rows as sent, flag false; empty or absent
→ `matched_ids(body.title, members)`, rows = (owner for a sync calendar) + matched, flag
`bool(matched)`. `update_series`: `member_ids` sent and different from the rows → flag false; else
a changed title with the flag → `assign`; when `member_ids` or `reminders` are sent, apply them to
the series' surviving override rows too (**R4**, shared with T11). `update_occurrence` "this":
the same two rules on the override's own row and title (a new override inherits the flag through
`_copy`, `:508-515`).

(f) **P1 and parity.** `EventEditor.tsx`: `whoTouched` state set by the Who picker's `onChange`;
`draftToFields` sends `member_ids` only when the Who row was touched, or when a new event's quick
add found people (those names were cut out of the title, so they must be sent); `draftFromEvent`
keeps showing `occurrence?.member_ids ?? event.member_ids`. `quickAdd.ts` `folded()` folds per
character; its candidates gain the first-word and two-letter rules; cases after
`quickAdd.test.ts:500` ("Ana's recital" with only Ana Sofia; "Zoe swim" with Zoë; a one-letter
name).

(g) **The bar in several colors.** `chipTone` returns a third field, `edge: PersonColor[] | null`:
the first four people's colors in household order when there are two or more people, the event
has no color of its own and the chip is neither on nor past; that case keeps `bg-line/60 text-ink`
and pads `pl-[18px]` (12 px plus the bar). `export function PeopleEdge({ colors, className =
"w-1.5" })` draws `<span aria-hidden="true" className={`edge edge-${n} ${className}`}
style={{"--seg-1": "light-dark(var(--rose-l), var(--rose-d))", …}}>`. `tokens.css`, after the
`[data-person]` block:

```css
/* Several people on one chip: the 6 px bar in equal segments of their solids (UX §4, ADR 0034). */
.edge { position: absolute; inset-block: 0; inset-inline-start: 0; }
.edge-2 { background: linear-gradient(to bottom, var(--seg-1) 0 50%, var(--seg-2) 50%); }
.edge-3 { background: linear-gradient(to bottom, var(--seg-1) 0 33.34%, var(--seg-2) 33.34% 66.67%, var(--seg-3) 66.67%); }
.edge-4 { background: linear-gradient(to bottom, var(--seg-1) 0 25%, var(--seg-2) 25% 50%, var(--seg-3) 50% 75%, var(--seg-4) 75%); }
```

Where it draws: `EventChip` (the button is already `relative overflow-hidden`), `HoursChip`
(`HoursGrid.tsx:471-477`, add `relative` to the inner span), `TodayPanel.tsx` `Line` (`:218`: the
`w-1.5` pill becomes `<PeopleEdge className="static mt-1.5 h-[1.25em] w-1.5 shrink-0
rounded-full"/>` when `edge`), `PhoneLists.tsx` `PhoneRow` (`:73`, `w-1 self-stretch
rounded-full`), `MonthView.tsx` `MonthEntry` (`:135-141`: `border-l-4` → `relative pl-2.5` with a
`w-1 rounded-sm` edge when several). The week strip's `Dots` and `TodayView` rows stay; the avatars
stay.

**Tests.** `just test-py tests/domain tests/calendar tests/sync tests/test_migrations.py`: in
`tests/sync/test_merge.py`, a calendar owned by Ana: "Mia & Leo's swim" → `[Ana, Mia, Leo]` and
`people_from_title` true; "Dentist" → `[Ana]` by the fallback with no rows, flag true; a server
rename to "Dentist Mia" → `[Ana, Mia]`; after `PATCH member_ids=[Sam]` a server update keeps
`[Sam]` and the flag off; the same ids sent again keep the flag; a server-made exception carries
the series' people and reminders (R5); `update_synced_calendar(owner=Sam)` moves the Ana row to
Sam on matched events. In `tests/calendar/test_api.py`: `POST` "Take Leo to soccer" without
`member_ids` → Leo, flag true; `PATCH title="Take Mia to soccer"` → Mia; `PATCH member_ids=[]`
(Everyone by hand) then a title edit stays Everyone; a one-off edit with a new title re-matches
that occurrence only; Undo of a pre-upgrade revision JSON (no `people_from_title` key) works.
`just test-fe src/features/calendar src/styles` (`quickAdd.test.ts`; a new
`EventChip.test.tsx`: `edge` null for one person, an explicit color, on, past; 2–4 colors in
household order; five people → four; `PeopleEdge` renders `edge edge-3` and `--seg-1…3`;
`EventEditor.test.ts`: `member_ids` omitted when Who is untouched). In `e2e/sync.spec.ts`: script
an event "Mia & Leo's swim" (Thursday) in the School calendar mapped to Ana; on the wall's People
view (`region` named per person) the chip is in Ana's, Mia's and Leo's columns, and the Week chip
has `.edge-3`. Run `just e2e e2e/sync.spec.ts --project=display-1080p -g "title"`.

**Docs.** UX §4 Week board (`:226`): "several people: a neutral tint, the bar in their colors and
up to three avatars"; UX §4 Event sheet / Add: "An event whose title names people is theirs (Mia
& Leo's Skate Lesson), on top of its calendar's person for a synced calendar; set Who by hand
and Sunroom stops guessing for that event"; PLAN §7.5 "Merging synced events" (the people rule);
PLAN §10.1 (the column). ADR 0034 rows (the matcher and its parity; the flag; owner-only events;
the bar). A follow-up noted: a per-calendar switch if a family's names are common words (Will,
Grace, Mark).

**CHANGELOG** (Added). "An event whose title names people in the household is theirs: 'Mia &
Leo's Skate Lesson' shows in Mia's and Leo's columns, on top of its calendar's person, on
import and when it's added. Set Who by hand and Sunroom stops guessing for that event." "A chip
for several people shows a bar in each of their colors." (Fixed) "A one-off change the server sends
for a synced event keeps the series' people and reminders; saving a synced event no longer pins
its calendar's person to it."

**As built.** As planned, with these differences:
- *A first word two people share* (Ana Sofia and Ana Maria) is nobody's, on both sides: the
  plan's rule would have given "Ana's recital" to whichever came first.
- *The fallback* (a synced event with no rows shows its calendar's person) now applies only
  while `people_from_title` is on, so Everyone set by hand on a synced event stays Everyone;
  before, no rows always meant the owner.
- *On add*, an explicit `member_ids: []` is a hand choice (Everyone), not "nobody picked": the
  new editor sends people only when Who was touched, so `[]` means someone chose Everyone. With
  nobody picked in a synced calendar the flag is on even when no name matched, so the event
  behaves like an imported one (its person by the fallback; a later rename re-matches).
- *Where the re-match runs*: `calendar/people.py` (`assign`, `rematch`, a small `Person`
  dataclass: pyright strict won't match SQLAlchemy's mapped attributes to a protocol) and
  `calendar.service.rematch_people`, which announces what changed with `bump` (people can't
  import service without a cycle). A local calendar's owner never takes part, so only a synced
  calendar's new person re-matches. People's changes and the start re-match every flagged
  event, in batches, writing only what differs.
- *R4* (All of Them reaching the one-offs) is built here for people and reminders, in
  `update_series`'s loop; T11 uses it.
- *The bar* is `w-[6px]` on chips (the single person's bar is a 6 px border at every text
  size), and the `.edge` rules sit in tokens.css's components layer, so a `static` or a width
  utility still wins (the Today panel's pill, the phone's row).
- Tests: `tests/domain/test_people.py` (16 cases), `tests/sync/test_people.py` (new: names on
  top of the owner, the fallback, a server rename, a hand choice that outlasts the server and
  the same people sent again, R5's exception, a new owner, a person added and renamed),
  `test_api.py` (four cases: add and rename, Everyone by hand, one occurrence's own title, R4,
  Undo of a snapshot without the key), `test_migrations.py`, `quickAdd.test.ts`,
  `EventEditor.test.ts` (P1), a new `EventChip.test.tsx`. The e2e case in `sync.spec.ts`
  scripts the swim for today, since the People view shows today; it passes on `display-1080p`.
  The whole backend suite ran once here too (1,157 passed), since the start-up re-match runs
  in every app test.

### T11 Reminders that come back, and a default reminder

- [x] Done (commit: "calendar: reminders that come back, and a Default reminder")

**Owner's note.** "Reminders are either not saving to an event, or not showing up after saving
with one and re-opening the event. Can there be a 'Default Reminder' setting in the app, where all
events get a reminder at the default time interval?"

**What exists.** "Answers" lists R1–R5 with lines. Reminders are `EventReminder` rows (PK
`event_id`, `minutes_before`; the API accepts 0–10080, `calendar/schemas.py:19`); `EventOut
.reminders` comes from the series (`service.py:262-269, 302`), `OccurrenceOut.reminders` from the
series or the override row (`occurrences.py:122, 165-175`); `OccurrenceOut` has no `description`.
The Remind row: `EventEditor.tsx:27-32` `REMINDERS` (None/10/60/1440), `:434-442` `ChoiceRow
label="Remind"` inside More…, `:163` `reminder: event.reminders[0] ?? null`, `:106` `reminders:
draft.reminder === null ? [] : [draft.reminder]`; `ui/ValueRow.tsx` `ChoiceRow` shows `""` for an
unknown value (`:165, 169`). Delivery is the wall only: `features/calendar/reminders.ts`
`remindersOf()` over today's and tomorrow's occurrences from calendars shown on the wall, a
10-minute grace, all-day at 8:00. No household default; `settings.changed` refreshes the wall's
settings at once. The seed's Soccer practice has `reminders=[30]` (`meta/testing.py:222-230`).

**Build.**

(a) **Columns.** `Household.default_reminder_minutes: Mapped[int | None]` (null: none);
`Event.reminders_off: Mapped[bool]` (default False: "explicitly none, ignore the household's
default"). One migration, `just db-revision "household: default reminder; events: reminders
off"` (`down_revision` is T10's): `household.default_reminder_minutes` Integer nullable;
`events.reminders_off` Boolean NOT NULL `server_default=sa.false()`. `revisions.py` `_fields()`
default (T10's rule covers it). Test: a 0.11.0 household comes out with no default and every event
`reminders_off` 0.

(b) **Settings.** `SettingsOut.default_reminder_minutes: int | None`;
`SettingsUpdate.default_reminder_minutes: Literal[5, 10, 15, 30, 60, 120, 1440] | None`; the
update loop (`household/router.py:87-97`) skips `None` for every key, so `default_reminder_minutes`
joins the keys whose explicit null is written (sending null clears it). The row: `CalendarsPage
.tsx`, a `DefaultReminder` under `DefaultCalendar` (`:168-215`) in the same group: `ChoiceRow
strong label="Default reminder"`, choices None · 5 min · 10 min · 15 min · 30 min before · 1 hour ·
2 hours · 1 day before, hint "Events with no reminder of their own remind on paired screens this
long before. Calendars that only show events (holidays, a calendar address) don't." Saves through
`useUpdateSettings()` with `SavedMark`.

(c) **The event contract.** `EventFields.reminders_off: bool | None`; `EventOut.reminders_off`;
`OccurrenceOut.reminders_off` (per row). Three states, one encoding: the household's default =
`reminders: []`, `reminders_off: false` (or neither on create); explicitly none = `[]` and `true`;
its own = `[10, 60]` (the server forces `reminders_off` false; `true` with a non-empty list → 422
"Pick reminders, or none, not both."); `None` for either means "leave it". `_set_people` takes
the row and sets the column (rows replaced when `reminders` is sent; `reminders_off` as sent,
forced false whenever rows are written); every caller follows (create, series and its overrides for
R4, occurrence, the "following" sibling, `_upsert_override` for R5). **R2:** a new route `GET
/api/calendar/events/{event_id}/occurrences/{recurrence_id}` → `EventOut` of the override row when
one exists, else the series (404 for a `recurrence_id` that isn't an occurrence); the alternative
(`description` on `OccurrenceOut`) would put every synced invite's text into the cached week.
The default is **resolved on the wall**, not by the server: occurrences are cached per calendar
version, and a changed default would leave them stale.

(d) **The wall.** `reminders.ts`: `Remindable` adds `reminders_off` and `read_only`;
`effectiveReminders(o, defaultMinutes)` = its rows if any, else `[]` if off, else `[default]` when
set and the calendar isn't read-only, else `[]`; `remindersOf` and `dueNow` take the default;
`useReminders()` reads `useSettings().data?.default_reminder_minutes ?? null`. The toast's words
don't change.

(e) **The editor.** `features/calendar/reminderWords.ts`: `minutesLabel(m)` ("5 min before",
"1 hour before", "1½ hours before", "1 day before", "2 days before"; `lengthWords` from
`ui/LengthField` under a day), `remindersLabel([10, 60])` → "10 min and 1 hour before",
`reminderChoices(defaultMinutes, stored, storedOff)`: with a default, `{value: "default", label:
"Default (10 min before)"}` first, then "none", then the presets; without one, "None" first; a
stored value that isn't a preset (45, or several) is appended as one choice labelled by
`remindersLabel`, so nothing shows blank. `Draft.reminder` becomes `reminders: number[]`,
`remindersOff`, `remindChanged`; the row's value is `remindersOff ? "none" : reminders.length ?
reminders.join(",") : "default"`; a pick replaces the set (R3); `draftToFields` sends
`reminders`/`reminders_off` only when `remindChanged`; More… opens when `reminders.length ||
remindersOff`; Add starts on "Default (…)" when one exists. **R2:** `draftFromEvent(event,
occurrence, at, weekStartsOn)` takes title, location, notes, color, reminders, `reminders_off` and
the shown people from `at` (the new route, `useEventAt(eventId, rid)` in `data.ts`) when editing
one occurrence that is an override; series fields from the master. `AddPanel.tsx:147-167` passes
it; `EventSheet.tsx` shows an override's own place and notes. The hint under Remind: "A reminder
shows on paired screens."

**Tests.** `just test-py tests/test_household.py tests/calendar tests/sync tests/test_migrations.py`
(the default null, 10, null again, 7 → 422; create with `[10, 60]` → both on `EventOut` and
`OccurrenceOut`; `{reminders: [], reminders_off: true}` → off; `[15]` → on; `[15]` with off → 422;
a "this" change with a new title and `[15]` → the new route returns the override's words and `[15]`
while the series keeps its own; All of Them with `[5]` reaches the override (R4); a server-made
exception copies the series' reminders (R5)). `just test-fe src/features/calendar src/ui
src/features/settings` (`reminderWords.test.ts`; `reminders.test.ts`: the effective list with a
default, with off, with own rows, read-only excluded, `dueNow` at the default; `EventEditor.test
.ts`: untouched → nothing sent, None → `{reminders: [], reminders_off: true}`, a pick → `{reminders:
[60]}`, `draftFromEvent` prefers `at`). In `e2e/calendar.spec.ts`, two cases on `display-1080p`:
set the server clock to `2026-10-07T12:50:00Z` *before* `seed()` (the seed's Vet lands Wednesday
9:00; GOTCHAS' rule), `PATCH /api/settings {default_reminder_minutes: 10}`, pair the wall, open
`/display`, expect the toast "Vet starts in 10 min"; and the seed's Soccer practice opens with
Remind reading "30 min before". Run `just e2e e2e/calendar.spec.ts --project=display-1080p -g
"remind"`.

**Docs.** UX §4:314 (the Remind row: "Default (10 min before) when the household has one, None,
5, 10, 15, 30 min, 1 hour, 2 hours, 1 day before; a reminder shows on paired screens"); UX §4
Calendars & Accounts row (the Default reminder row after Default calendar); UX §5:546; PLAN §7
(reminders: three states, the wall resolves the default), §10.1 and §11.1 (the route). ADR 0034
rows.

**CHANGELOG** (Added). "Settings → Calendars & Accounts → Default reminder: events with no
reminder of their own remind on paired screens this long before." (Fixed) "A reminder now comes
back when an event is reopened: the row knows 30 minutes and any other value, a change to one
occurrence shows on that occurrence, two reminders stay two, and 'All of Them' reaches the changed
occurrences too." "The Remind row offers 5, 15 and 30 minutes and 2 hours as well."

**As built.** As planned, with these differences:
- *R4 and R5* were built in T10 (the same loops carry people and reminders); T11 adds the
  `reminders_off` flag to them.
- *With no Default reminder in the household*, an event that holds none reads "None" on the
  row (there is no "Default" to show), and picking None stores it as explicitly none, so a
  default set later doesn't reach it. `reminderValue` and `reminderPick` in
  `reminderWords.ts` hold the three states; `reminderChoices` adds a held value the presets
  don't have (45 minutes, two reminders) as one more choice in its own words.
- *The sheet* shows a changed occurrence's own notes through the new route (its place was
  already the occurrence's); the editor waits for that row, and opens on the series' words if
  it won't load, never blank. "Just This One" clearing a color reads that occurrence's own.
- *The settings row* sits in one group with Default calendar (`DefaultCalendar` now draws its
  row only), with `SavedMark` after each.
- Tests: `test_household.py` (the default set, kept, cleared with null, 7 refused),
  `test_api.py` (two reminders on the event and the occurrence, none, own, both refused, back
  to the default; the new route: an override's own words and reminders, an unchanged one the
  series', a time that isn't one 404), `test_migrations.py`, `test_birthdays.py` (the new
  field), `reminders.test.ts` (the default, none, read-only, due at its minute),
  `reminderWords.test.ts` (new), `EventEditor.test.ts` (nothing sent untouched, the three
  states, `draftFromEvent` reading the override). The two e2e cases in `calendar.spec.ts` pass
  on `display-1080p`; the Vet's case pairs the wall first and moves the clock to 8:50 after the
  seed (the seed at 10 AM puts the Vet on the same Wednesday, so moving the clock first wasn't
  needed).

### T12 Needs Attention

- [x] Done (commit: "problems: Needs Attention, one place for what needs a parent")

**Owner's note.** "Are errors surfaced in the app at all? If a connected Apple account can't
retrieve a calendar for some time (error communicating with Apple, invalid password, etc.) or any
number of warnings/errors, the user should be able to see on the calendar view that something
isn't working properly in the app and needs to be investigated."

**What exists.** "Answers" has the survey. The account's status, `last_error`, `last_success_at`
(`plugins/calendar_sync/models.py:44-70`; `engine.py` `_failed` `:456-480`, `ERROR_AFTER = 3`); the
pill's sentences in `features/sync/SyncPill.tsx` (`pillText`), rendered only through `BoardPills`
(`BoardControls.tsx:95-98`, `CalendarRoom.tsx:61-63, 227`), registered as `boardPill` in
`features/sync/index.ts` and `features/registry.ts:115-116`; the photo sources' `last_error`
(`plugins/screensaver/service.py:227-245` `tally.problem()`); the backup status (`state.backups
.status()`: `last_error`, `stale`, `last_success_at`); a crashed plugin (`state.plugins.status(id)
is ERRORED`, Features says "{name} stopped working."); free space (`diagnostics`). The plugin
protocol (`plugins/base.py` `Plugin` `:113-150`, `PluginBase` `:151-175`); `Contributions.banners`
(`:79`) and `ContributesOut.banners` (`plugins/router.py:57, 141`) with `calendar_sync/plugin.py:56`
declaring `("sync_error",)`, unread. The hub broadcasts named events; `lib/eventRouter.ts` maps
them to query keys. The header's right end (`shell/Header.tsx:173-176`) holds the Today panel's
button and `LiveStatusButton`, drawn only while something is wrong (ADR 0030). Settings lists:
`SettingsScreens.tsx` `SettingsIndex` (`:59-79`), `DisplaySettings` nav (`:135-147`). The phone's
Today header: `features/phone/TodayScreen.tsx:88-90`. `PluginManager` has an idle context for a
plugin that isn't running (`manager.py:327`, the `validate_settings` precedent).

**Build.**

(a) **The hook.** `plugins/base.py`: `@dataclass(frozen=True, slots=True) class Problem: id: str;
title: str; detail: str | None = None; since: datetime | None = None; page: str | None = None`
(`id` stable per cause, "sync:<account id>"; `title` one sentence in the family's words, no ids or
secrets; `detail` a quiet second line for parents; `page` the Settings page key). `Plugin` and
`PluginBase` gain `async def problems(self, ctx) -> list[Problem]` (default `[]`). `banners` goes
from `Contributions`, `ContributesOut`, the sync manifest and PLAN §6.2/§6.5.
`PluginManager.problems()`: for each enabled plugin, its hook with the runner's context or the idle
one, each in `try/except Exception` (log `plugin.problems_failed`, contribute nothing), on the
request path (a read, like validation).

(b) **The plugins.** `calendar_sync/service.py`: `account_name(account)` (the frontend's
`sourceName` rule: holidays → "Holidays", google → "Google", icloud.com → "Apple", else the label)
and `problem_sentence(account)`: needs_reconnect → google "Google signed Sunroom out.", ics
"{name}'s calendar address stopped working.", else "{name} needs its password again."; error →
"{name} hasn't answered. Showing what we had." `problems(ctx)`: live accounts in `needs_reconnect`
or `error` → `Problem(id=f"sync:{id}", title, since=last_error_at or last_success_at,
page="calendars")` (the "since 9:10 AM" moves to the frontend, which knows the 12/24-hour choice).
`screensaver/plugin.py` → `service.problems(ctx)`: enabled sources with `last_error` →
`Problem(id=f"photos:{id}", title=the line `tally.problem()` already writes, page="screensaver")`.

(c) **Core.** `backend/src/sunroom/problems/` (`schemas.py`, `service.py`, `router.py`; mounted
in `app.py` beside the plugins router): `ProblemOut(id, title, detail, since, page, source)`,
`ProblemsOut(problems)`; `service.collect(state, actor)`: a stopped plugin first ("{name} stopped
working.", page "features"), then the plugins' own, then the backup ("The last backup didn't
complete." with `detail` "The last try failed: {last_error}", page "backup"; else "The newest
backup is over a week old." with `since`, only while nightly backups are on after T15), then low
space (under 2 GiB free: "The server has 1.3 GB free. Sunroom needs room for photos and backups.",
page "about"); `detail` is dropped for a non-parent actor. `GET /api/problems` (`ActorDep`): a
kiosk and a child's device see the titles (no secrets by construction). The update check's problem
stays on About (informational).

(d) **Fresh.** No new server event: `lib/eventRouter.ts` invalidates `qk.problems()` (new key) on
`sync.changed`, `screensaver.changed`, `photos.changed`, `plugins.changed` and `settings.changed`;
`useProblems()` refetches every 5 minutes for the two causes with no event (a backup at 3:30 AM,
disk space).

(e) **The frontend**, `features/problems/`: `data.ts` (`useProblems`, `attentionWords(n)`: "1
thing needs attention" / "2 things need attention", `pageTitle(page)` from the settings pages);
`AttentionButton.tsx`: in the header's right end between the Today toggle and the live icon, a
56 px quiet icon button (lucide `TriangleAlert`, `text-ink-soft`), name "Needs attention: 2
things", drawn only while there are problems; `AttentionSheet.tsx`: `<Sheet title="Needs
Attention">`, one item per problem: the sentence (semibold), "Since 9:10 AM" (soft; the date too
when not today) and `detail` (soft) when present, then a secondary button "Open {page title}"
("Open Calendars & Accounts"); on a kiosk without a grant it asks the PIN first (the gate
`DisplayShell.openSettings` applies), then navigates and closes; `AttentionPill.tsx` on a phone's
Today, under the header: a quiet pill (`rounded-full border-2 border-line bg-surface
text-ink-soft`) reading `attentionWords(n)`, opening the same sheet. Settings lists: a row whose
key is a problem's `page` gets a small `bg-alert` dot with an sr-only ", needs attention". Remove
`SyncPill.tsx`, `SyncPill.test.ts`, `boardPill` from `features/sync/index.ts` and the registry,
`BoardPills` from `BoardControls.tsx` and `CalendarRoom.tsx`; the account rows' red status lines
in Settings stay.

**Tests.** `just test-py tests/test_problems.py tests/sync/test_engine.py tests/screensaver
tests/plugins` (a stale backup → `backup:stale` with page and `since`; a `last_error` → `detail`
for a parent and none for a kiosk; `SamplePlugin(fail_in="job")` → "Sample stopped working."; a
disabled plugin's hook is never called; after `remote.fail_next(ErrorKind.AUTH)` the route lists
"Test server needs its password again." with page "calendars", after three unreachables "Test
server hasn't answered. Showing what we had." with `since`, and a reconnect clears it; a source's
`last_error` → `photos:<id>`; the contract test: every registered plugin's `problems(idle ctx)` is
a list of `Problem` whose titles end in a period and whose `page` is None or a known key).
`just test-fe src/features/problems src/lib src/features/settings` (the sheet's sentences and
buttons; the icon only with problems; `attentionWords`; `sync.changed` invalidates `["problems"]`;
the Settings dot). `e2e/sync.spec.ts:154-177` becomes "a refused password shows the attention icon,
and the sheet names the account": after the AUTH failure the button `/^Needs attention/` is
visible, its sheet holds "Test server needs its password again.", "Open Calendars & Accounts" lands
on `/settings/calendars`. `screenshots.spec.ts:270-299`: the sheet instead of the pill
(`display-attention`). Run `just e2e e2e/sync.spec.ts --project=display-1080p -g "attention"`.

**Docs.** UX §8 rows 763, 772-776 (the pills → "the Needs Attention icon at the header's right
end, on the wall in every room and on a phone's Today; a tap opens the sheet") and the live-updates
row 777 (its neighbour); UX §3 header (the icon beside the live one); UX §4 Settings (the dot);
PLAN §6.2 (the hook in the protocol listing), §6.5, §11.1 (the route). ADR 0030's "only the plugins'
quiet pills remain above the days" → changed by ADR 0034. ADR 0034 rows.

**CHANGELOG** (Added). "When something needs a parent (a calendar that stopped syncing, a photo
source that fails, a backup that didn't complete or is a week old, a feature that stopped, a full
disk), a Needs Attention icon shows at the top of every room on the wall and on a phone's Today; a
tap lists what's wrong and opens the settings that fix it. The pill above the days is gone."

**As built.** As planned, with these differences:
- *"Since"* for an account that hasn't answered is its last success (when it stopped), and for
  one that needs a new password the refusal's time; the plan had the latest failure first for
  both, which would have said "since" the most recent retry.
- *A stopped plugin* isn't asked for its own problems (its hook may be what broke); core reports
  it, "{name} stopped working.", page Features.
- *The Settings dot*: the flagged link is named "Calendars & Accounts, needs attention" by an
  `aria-label` (a hidden span inside the link came out as "Calendars & Accounts , needs
  attention"). `screenshots.spec.ts`'s Settings loops accept either name, since its failing
  account stays failing into them; its shot is now `display-attention` (the sheet), not
  `board-sync-pill`.
- *The PIN on a paired screen*: "Open …" asks it only on a kiosk without a grant; on a phone
  the Settings route's own gate applies (`PinDialog` is the wall's; see the follow-ups).
- Tests: `tests/test_problems.py` (new: nothing on a new household; a week-old backup and a
  failed one, the detail for a parent and not a PIN-gated wall; low space; a feature's own
  problems only while it's on, a broken hook adding nothing; a stopped feature; the contract
  over every registered plugin), `test_engine.py` (a refused password, three unreachables and
  their "since", and the reconnect clearing it), `test_inbox.py` (a failing source), the
  router's invalidations, `problems.test.tsx` (new). The e2e case in `sync.spec.ts` passes on
  `display-1080p`: no icon while all is well, the icon and its name after the refusal, the
  sheet's sentence, Open Calendars & Accounts, and the marked page.

### T13 Any reverse proxy, with nothing to set

- [x] Done (commit: "web: any reverse proxy with nothing to set; APP_ALLOWED_HOSTS an optional lock")

**Owner's note.** "Remove TRUSTED_PROXIES from the app. The goal is to be easy for anyone to set
up and use. They shouldn't have to set up a proxy address allowlist. And APP_ALLOWED_HOSTS should
default to any host unless the setting is specified. That way as soon as the docker container is
started, they can go to http://<HOST>:7867 and set up the app." The owner chose the recommended
design ("Answers").

**What exists.** `core/config.py:57-59` (`app_allowed_hosts`, `trusted_proxies`; `_split_list`
`:114-119`; `_check_allowed_hosts` `:121-132`; `_check_proxies` `:134-146`); `cli.py:78-89`
(`proxy_headers=False`, the comment `:82-83`); `app.py:311-317` (the middleware order:
`ForwardedHeaders(trusted_proxies=…)` → log → headers → `HostGuard(rule=HostRule(…))` → CSRF);
`web/forwarded.py` (trust by TCP peer `:41-49`; Proto `:55-63`; For via `_last_untrusted` `:23-33`
→ `:64-68`; Host `:69-72`); `web/hosts.py` (`LAN_SUFFIXES` `:27`; `HostRule.allows` `:60-69`;
`HostGuard` `:72-122`, the 421 message `:98-101`); `web/csrf.py` (`proxy_not_trusted` `:59-74`);
`meta/router.py:55-61, 142-149` (`ClientInfo`: `resolved_ip`, `x_forwarded_for`,
`x_forwarded_proto`, `trusted_proxies_configured`); `AboutPage.tsx:50-69`. Tests: `test_config
.py:27, 64, 69`; `test_web.py:144, 150, 155, 171, 184, 218`; `test_auth.py:45, 72, 91, 109`;
`tests/support.py:25`; `scripts/image_common.sh:52-53` (421 for `Host: evil.example`). Every doc
that names the two settings: `.env.example:10-14`, `docker-compose.example.yml:13-15`,
`README.md:66`, `SECURITY.md:21-22`, `PRIVACY.md:28-29`, `docs/DEPLOY.md:35-36, 75-91, 102,
149-150`, `docs/REMOTE-ACCESS.md:49-76, 110-111, 138, 170-176, 204, 221-225, 231-241`,
`docs/PLAN.md:140, 549, 572, 606, 633, 686-687, 742`, ADR 0017, ADR 0018:17, `docs/M6.md:773-774`
(history, leave), `kiosk/install.sh:1085-1089` (the `.env` template). The owner's own compose
keeps `APP_ALLOWED_HOSTS` (strict mode as today) and a `TRUSTED_PROXIES` line (ignored with a
warning; the proxy's Docker peer is private, so nothing changes for them).

**Build.**

(a) `web/forwarded.py`: no options. `HOME_NETWORKS` = `127.0.0.0/8`, `10.0.0.0/8`,
`172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `100.64.0.0/10` (Tailscale: a proxy on
another tailnet machine, say Caddy on the NAS, reaches Sunroom from a `100.x` address, and CGNAT
space is never the open internet), `::1/128`, `fc00::/7`, `fe80::/10`; explicit ranges, not
`is_private` (which counts the test ranges differently). `from_home_network(address)` parses,
unwraps `ipv4_mapped`, checks membership. Headers apply when the peer is from home;
`X-Forwarded-For` takes the right-most hop outside those ranges, else the left-most (today's
rule with `HOME_NETWORKS` as the trusted tuple). Docstring rewritten.

(b) `web/hosts.py`: `HostRule(allowed)` sets `strict = bool(allowed)`; `allows()` starts with
`if not self.strict: return True`; the strict path is today's rule exactly; the 421 and its words
stay (they fire only in strict mode, where the fix is still the setting); `HostGuard` notes only a
non-empty Host. `core/config.py`: `trusted_proxies` and `_check_proxies` go; the
`app_allowed_hosts` comment says "Optional lock (ADR 0034): set, the Host rule accepts only
LAN-style names plus these; unset, any Host"; `Settings.warnings()` adds "TRUSTED_PROXIES is no
longer needed and is ignored: Sunroom believes a reverse proxy on the home network by itself
(docs/REMOTE-ACCESS.md)" when the variable is set (`extra="ignore"` already keeps the container
starting). `app.py`: `add_middleware(ForwardedHeaders)`. `cli.py:82-83`: the comment ("…from
private addresses only; uvicorn's own handling would trust 127.0.0.1 alone and miss a proxy in
Docker"). `web/csrf.py`: the branch stays (a proxy that doesn't send `X-Forwarded-Proto`, or one at
a public address), code `https_not_forwarded`, message "Sunroom is reached over https, but the
proxy didn't say so. Make it send X-Forwarded-Proto: https from the home network
(docs/REMOTE-ACCESS.md), then try again.", the once-per-process log `csrf.https_not_forwarded`
with the peer's address. `meta/router.py` `ClientInfo` keeps `scheme` and `host` only; `just
api-types`; `AboutPage.tsx`: the "URL" row loses its hint, "Sunroom sees it as" goes.

(c) Tests: `test_config.py` (drop the proxies case; `TRUSTED_PROXIES=10.0.0.1` loads and warns;
`test_cli.py`: `check-config` with it exits 0 and prints the warning); `test_web.py`: keep
`:144, 150` (strict, since they pass a list); `:155` builds its app with
`app_allowed_hosts="calendar.example.com"` and keeps every 421 assertion; new
`test_any_host_is_answered_by_default` (`Host: evil.example` → 200 and the name in a parent's
`recent_addresses`) and `test_any_name_passes_without_a_list`; `:184` becomes a direct middleware
test over a recording ASGI app (peers `127.0.0.1`, `192.168.1.20`, `172.18.0.1`, `100.64.0.5`,
`fe80::1`, `::ffff:10.0.0.9` apply all three headers; `203.0.113.9` applies none; XFF
`"198.51.100.7, 10.0.0.2"` → `198.51.100.7`; `"100.101.102.103"` from `172.18.0.1` → that; garbage
leaves the client; a websocket scope → `wss`); `:218` drops `trusted_proxies=` and `resolved_ip`,
keeps the `__Host-` cookie and host, and gains its public-peer mirror (cookie `sunroom`, scheme
http, host unchanged). `test_auth.py:45` drops the proxies setting; `:109` asserts
`https_not_forwarded` and "X-Forwarded-Proto" for both a home peer without the header and a public
peer with it. `tests/support.py:25` drops the name. `scripts/image_common.sh:52-53`: the default
container answers `Host: evil.example` (200) and believes `X-Forwarded-Proto: https` from Docker's
gateway (`strict-transport-security` present); `scripts/smoke_image.sh` adds a short strict run
(`-e APP_ALLOWED_HOSTS=calendar.example.com` on a second volume and port: `evil.example` → 421,
`calendar.example.com` → 200; both names in `cleanup()`).

(d) Docs, with the new wording: `.env.example` (one optional setting, two lines gone);
`docker-compose.example.yml:13-15` ("Optional. Behind your own HTTPS reverse proxy nothing is
needed. To make Sunroom answer only to the names you list (a lock against DNS rebinding,
docs/REMOTE-ACCESS.md): APP_ALLOWED_HOSTS …"); `README.md:65-67` ("Your own HTTPS proxy, Tailscale
or Cloudflare work with nothing to set; docs/REMOTE-ACCESS.md shows each way, and when to lock
Sunroom to a name with APP_ALLOWED_HOSTS."); `SECURITY.md:21-22` ("Sunroom believes a reverse
proxy's forwarded headers only when the connection comes from the home network, never from the
internet. APP_ALLOWED_HOSTS can lock it to the names you choose, so a web page that points its own
name at your home address is refused."); `PRIVACY.md:28-29` (the proxy's address is logged once
when it doesn't say https; About no longer shows the phone's own address); `docs/DEPLOY.md`: the
table row (optional), §3 "Set TRUSTED_PROXIES" → "Check the proxy's headers" (`X-Forwarded-Proto:
https` from a home address; a hand-written nginx needs `proxy_set_header X-Forwarded-Proto
$scheme;`), `:102` ("URL"), `:149-150` (the 421 only with the lock set);
`docs/REMOTE-ACCESS.md`: "The two settings" → "The one setting (optional)" (when the lock is worth
it; "to turn it on without a public name, list the name you use, for example sunroom.local"),
the proxies table gone, Tailscale's "Trust it" step gone and the rest renumbered, Caddy's and
Cloudflare's steps ("recommended, the name is public"), "Check that it worked" (URL; no "sees it
as"), "When something isn't right" (the 421 bullet, the https bullet with the log's name, the
exit-78 bullet without the setting, "A TRUSTED_PROXIES line from an earlier version is ignored;
the log says so"); `docs/PLAN.md:140, 549, 572, 606, 633, 686-687, 742` (as above); UX §4 About
row ("URL"); ADR 0017 Status "Accepted; the default Host rule and the proxy list changed by ADR
0034"; ADR 0018:17 a parenthesis; `kiosk/install.sh:1085-1089` template comment ("Optional lock…
Not needed for a proxy or Tailscale"; `just kiosk-lint`). ADR 0034 row (the design, the ranges and
why 100.64/10, the residuals: a page rebound from home can read public pages and plant a name in
About; any home device can game the per-address limit; the strict mode's `X-Forwarded-Host`
weakness to GETs).

**Tests.** `just test-py tests/test_web.py tests/test_auth.py tests/test_config.py
tests/test_cli.py`; `just test-fe src/features/settings`; `just e2e e2e/shell.spec.ts
--project=phone-chromium -g About`; after the commit, `just smoke-image` once (it builds the image
from git: the one task in this batch that needs it between tasks, because the probe changed).

**CHANGELOG** (Changed). "Sunroom works behind any reverse proxy (Tailscale, Caddy, Cloudflare,
your own) with nothing to set: it believes a proxy on the home network about https and the phone's
address, and answers to any name. TRUSTED_PROXIES is gone (an old line is ignored, with a note in
the log). APP_ALLOWED_HOSTS is now an optional lock: set it and Sunroom answers only to those
names and local ones. About says URL and no longer shows the phone's own address."

**As built.** As planned. `web/forwarded.py` has no options: `HOME_NETWORKS` (the nine ranges),
`from_home_network()` (unwraps `ipv4_mapped`), and `_client_of()`, which takes the right-most
`X-Forwarded-For` hop outside home, else the left-most, and leaves the connection's own client
when any hop isn't an address; a websocket scope gets `wss`/`ws`. `HostRule.strict =
bool(allowed)`; `HostGuard` notes a name for About only when the Host is not empty. The config
warning, the CSRF code and message (`https_not_forwarded`, logged once with the peer), `ClientInfo`
down to `scheme` and `host`, and About's URL row without its hint, all as written. Tests: the
middleware is tested directly over a recording ASGI app (six home peers apply all three headers,
a public one none, the XFF cases, garbage, websocket); `test_web.py` keeps every strict 421
assertion on an app built with `app_allowed_hosts`, and gains the any-Host cases; `test_auth.py`
checks `https_not_forwarded` for a home peer without the header and a public peer with it.
`image_common.sh` expects 200 for `Host: evil.example` and HSTS for a forwarded https;
`smoke_image.sh` adds a `-locked` container on the next port with
`APP_ALLOWED_HOSTS=calendar.example.com` (421 and 200), cleaned up with the first. Docs as listed,
plus PLAN §12.5's Tailscale and Caddy sentences (the plan's `:633`), which still told the reader to
set the proxy list; ADR 0017's body stays as history under its new Status line. The ADR row adds
one residual the plan didn't list: without the lock, a rebound page could also finish setup on a
server nobody has set up yet (the window between starting the container and the wizard; the
family would find it set up and reset it with the CLI).

### T14 A refresh shows the new version

- [x] Done (commit: "web: a refresh asks the server for the page; the wall waits out a server outage")

**Owner's note.** "Ensure refreshing the page doesn't download cached assets after an update.
I've had to clear the cache to see new versions."

**What exists.** "Answers" has the cause. `frontend/src/sw.ts`: `precacheAndRoute(self
.__WB_MANIFEST)` (`:22`), `cleanupOutdatedCaches()` (`:23`), `clientsClaim()` (`:25`), a
`NavigationRoute(createHandlerBoundToURL("/index.html"), {denylist: [/^\/api\//, /^\/photos\//]})`
(`:26-30`), `skipWaiting` only on a `SKIP_WAITING` message (`:32-41`). `vite.config.ts:19-49`:
`injectManifest`, `registerType: "prompt"`, `injectRegister: false`, the glob keeps `index.html`
in the manifest. Registration `ui/StatusLayer.tsx` `useAppUpdate()` (`:45-76`): `useRegisterSW`,
`registration.update()` hourly through an interval that is never cleared (the wall remounts its
shell on every room change, so they pile up) and on `visibilitychange`; the phone's "New version ·
Refresh" pill (`:78-96`); the wall's 3 AM apply (`DisplayShell.tsx:264-268`). The hello path:
`lib/update.ts` (`useServerUpdate` `:81-101`, `reloadFresh` `:54-68`). The server: `web/spa.py`
renders `index.html` `no-cache` with a fresh nonce per response (`:51-56`), `sw.js` `no-cache`
(`:85-88`), `/assets` immutable (`web/headers.py:64-69`). `e2e/first-run.spec.ts:159-166` asserts
that a reload served by the worker keeps a consistent nonce; `shell.spec.ts:1183-1230` tests the
hello-driven refresh; `lib/update.test.tsx` has five cases. Verified against Workbox 7.4.1 (the
installed `node_modules`, not memory): routes match in registration order and the precache route's
matcher answers `/` through its directory index, so the navigation route must be registered first;
`NetworkFirst` writes a runtime cache and reads it back before any fallback, which in the window
this fix creates (a new page under the old worker) would cache a page whose assets the old precache
doesn't have and break offline; `NetworkOnly` with `networkTimeoutSeconds` plus
`PrecacheFallbackPlugin` is Workbox's own offline-fallback pairing; the install fetch stores the
full response, headers and CSP included, so the cached copy's nonce matches its own CSP;
`workbox-strategies` is only a transitive dependency under pnpm's strict layout and must be added.

**Build.**

(a) `cd frontend && pnpm add workbox-strategies@^7.4.1` (already locked at that version).

(b) `sw.ts`, whole:

```ts
/// <reference lib="webworker" />
/**
 * Service worker (PLAN §5.1, ADR 0034). The page itself comes from the server whenever it answers
 * (within 3 s), so a refresh after an update shows the new version at once; the copy precached at
 * install answers only when the server can't be reached, so the app still opens offline. The
 * build's hashed files are precached. No route for /api or /photos: cookie-gated data is never
 * cached here. Updates wait (registerType "prompt"): phones tap Refresh and the wall reloads at
 * night, so an open page built from the old version keeps its lazy chunks until then. The cached
 * index.html keeps the CSP header it was fetched with, whose nonce matches its own meta (ADR 0007).
 */
import { clientsClaim } from "workbox-core";
import { cleanupOutdatedCaches, PrecacheFallbackPlugin, precacheAndRoute, type PrecacheEntry } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { NetworkOnly } from "workbox-strategies";

declare let self: ServiceWorkerGlobalScope & { __WB_MANIFEST: (PrecacheEntry | string)[] };

/** How long a navigation waits for the server before the cached page answers instead. */
const SERVER_WAIT_S = 3;

// Registered first: routes match in order, and the precache route would otherwise answer "/" from
// the cache. No runtime cache for pages: a newer index.html cached offline would name files the
// precache doesn't have.
registerRoute(
  new NavigationRoute(
    new NetworkOnly({
      networkTimeoutSeconds: SERVER_WAIT_S,
      plugins: [new PrecacheFallbackPlugin({ fallbackURL: "/index.html" })],
    }),
    { denylist: [/^\/api\//, /^\/photos\//] },
  ),
);
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
clientsClaim();
// (the SKIP_WAITING listener as today)
```

(c) `StatusLayer.tsx` `useAppUpdate()`: the hourly check moves into one effect with cleanup
(`setInterval` + `visibilitychange` → `navigator.serviceWorker.getRegistration().then(r =>
r?.update())` while visible; cleared on unmount); `onRegisteredSW` goes. `vite.config.ts` and the
backend don't change.

**Tests.** `just test-fe src/lib/update.test.tsx src/ui` (an optional `StatusLayer.test.tsx` with
`virtual:pwa-register/react` mocked: the check runs after an hour and not after unmount).
`e2e/first-run.spec.ts:159-167` flips: wait for `navigator.serviceWorker.controller`, read the
nonce, `const response = await screen.reload()`, expect `response?.fromServiceWorker()` true, the
new nonce well-formed and **different** from the last (a fresh render from the server), the CSP
header containing it, then the toast step as today (the real proof that header and meta agree).
A new case in the same spec, Chromium only (`setOffline` reaches a worker's fetch in Chromium, not
WebKit): pair, open `/display`, wait for the controller, `context.setOffline(true)`, reload →
`fromServiceWorker()` and `ok()`, `#root` not empty, the nonce present, the offline pill visible
within 10 s (assert whatever `/display` renders when the session fetch fails: check
`DisplayEntry.tsx` during the run); `setOffline(false)`, reload → "This Week". Run
`just e2e e2e/first-run.spec.ts --project=display-1080p` and `just e2e e2e/shell.spec.ts
--project=display-1080p -g "container is updated"`. By hand, with your own Chrome (not `just
display`, which keeps no profile): `pnpm build`; run the server the way `scripts/e2e-server.sh`
does with a `DATA_DIR` you keep; `just seed 4173`; sign in; About says 0.11.0; edit `VERSION` to
0.11.1 (don't commit), `pnpm build`, restart the server; refresh: About says 0.11.1 at once and
DevTools shows the new worker waiting; DevTools → Network → Offline, refresh: the app still
opens; `git checkout VERSION`, `pnpm build`.

**Docs.** PLAN §5.1 (one sentence on the worker's navigation rule); ADR 0007's worker consequence
("changed by ADR 0034: the worker asks the server for the page, so the nonce is per request
whenever the server answers; the cached copy, per install, only when it doesn't"); CLAUDE.md's
`/photos` gotcha line ("since ADR 0034 it asks the server first…"); ADR 0034 row (the strategy,
the order, no runtime page cache, the accepted one-time "New version" pill after a refresh, the
residuals: a rebuild without a VERSION bump reaches an *open* page only through the pill or 3 AM;
a proxy that caches `index.html` against `no-cache`).

**CHANGELOG** (Fixed). "After an update, refreshing a paired screen or a phone that installed
Sunroom shows the new version at once. Before, the old page stayed until the screen's 3 AM reload
or the browser's cache was cleared. Offline, the screen still opens from its saved copy."

**As built.** As planned, with three changes. (1) The fallback is a two-line plugin,
`handlerDidError: () => matchPrecache("/index.html")`, which is what `PrecacheFallbackPlugin`
does: that class's typing fails `exactOptionalPropertyTypes`. (2) Beyond the plan, a plugin turns
a 5xx into no answer, so a proxy's 502 while the container restarts opens the saved page instead
of a dead end on the wall; the e2e checks it with a route on the worker's own fetch, counting that
it was hit. (3) The first-run case reloads twice and expects two different nonces, each in its
own CSP header: one reload's nonce would differ from the first page's even from the precache (the
install fetch is its own request), so only the second proves a fresh render. The new offline
case asserts the wall's frame (`main[data-shell="display"]`: `DisplayEntry` shows it while the
setup status is unknown, and has no offline pill). `useAppUpdate()` catches a failed update
check; `StatusLayer.test.tsx` gains the hourly-and-unmount case. The by-hand check ran scripted
(Playwright, a kept profile, a server on 4175 with its own data folder, VERSION set to 0.11.1 for
the rebuild and put back): the refresh loaded the new build's script at once, the new worker
waited, and offline the old copy opened (at `/`, after the router's few seconds of waiting for the
session request; unchanged). That check also found an older bug, fixed here: a paired screen
reloaded while the server was down (the network up) gave its session request two tries, then
showed Pair This Screen once the server came back. `DisplayEntry`'s session query now retries
until the server answers anything but a 4xx, and the offline case reproduces it (it failed
before the fix).

### T15 Backup: the policy, the copies, one Download, Export

- [x] Done (commit: "backup: the policy, every copy listed, Data Only, and Export")

**Owner's note.** "Polish 'A checked copy of everything is made every night and kept on the
server: 14 daily and 8 weekly.' Make Backups a setting they can turn on or off (on by default);
if enabled, how many daily and weekly to keep. Add a list of all backups with the ability to
download or delete a specific one, most recent on top. Move 'Back Up Now' to the header of that
section. One button 'Download' with a confirmation modal to choose which ('Data Only' or 'Data &
Photos'). A better definition of what Export does; name the button 'Export'."

**What exists.** `db/backup.py`: `KEEP_DAILY = 14`, `KEEP_WEEKLY = 8`, `KEEP_PRE_MIGRATE = 5`,
`STALE_AFTER` 7 days, `NIGHTLY_AT = (3, 30)` (`:30-39`, none configurable); `take_backup`
(`:104-149`: the online backup API, `journal_mode=DELETE`, `verify_problems`, `os.replace`,
`NoRoomError`); `rotate_nightly` (`:175-189`: the newest 14 days plus the newest day of each of
the 8 earlier weeks); `due()` (`:317-324`: after 03:30 when today's file is missing, not within an
hour of a failure); `run_now` (`:278-300`); the job `app.py:251` every 600 s; `BackupService` is
built at `app.py:205-210`. Files: `backups/sunroom.YYYY-MM-DD.db`, `pre-migrate/sunroom.<rev|
empty>.<stamp>.db`, `pre-erase/sunroom.<stamp>.db`; a restore moves the old database aside as
`sunroom.pre-restore.<stamp>.db` in the data dir. Routes (`meta/router.py`, all `ParentDep`): `GET
/api/admin/backups` (`:164`; status with the nightly files), `POST …/run` (`:169`), `GET
…/full.zip` (`:202-235`, streamed through `full_backup.make_database_copy()` into
`backups/.download/`, 507 `storage_full`), `GET …/{name}` (`:238-250`, nightly names only), `POST
/api/admin/erase` (`:261-285`, 403 `not_on_a_screen` for a kiosk), `GET /api/export` (`:288-297`).
`BackupPage.tsx` (strings at `:17, 79-80, 83-84, 90, 102, 105-112, 121, 127-128, 141, 148-149,
158`; `own = session && !kiosk`); `parts.tsx` `Group({title, note, children})`; `ui/Stepper`;
`ScopeChooser.tsx:10-52` (a sheet of block buttons: the "choose one" pattern); `EraseSheet.tsx`
(the typed-password sheet and its "The download has started…" line). `state.household` is the
in-memory `HouseholdCache` (`state.py`), refreshed by `PATCH /api/settings` (`household/router
.py:99` refreshes the zone the same way) and reset by `erase.forget`. Tests: `tests/test_backup
.py`, `test_full_backup.py`, `test_household.py`, `test_migrations.py`; `EraseSheet.test.tsx`
covers the page by device kind; `e2e/first-run.spec.ts:186-240` (the wall's Backup page has
Backups and Back Up Now and no Start Over; a computer downloads and erases; `:208` asserts a
"Download Everything" link).

**Build.**

(a) **The policy.** `Household.backups_enabled` (Boolean, default True), `backups_keep_daily`
(Integer, 14), `backups_keep_weekly` (Integer, 8); `SettingsOut` the three; `SettingsUpdate`
`backups_enabled: bool | None`, `backups_keep_daily: Annotated[int, Field(ge=1, le=30)] | None`,
`backups_keep_weekly: Annotated[int, Field(ge=0, le=12)] | None` (one daily at least, so the
newest copy is always kept; the caps keep a Stepper usable). Migration `just db-revision
"household: backup policy"` (`server_default=sa.true()`, `'14'`, `'8'`). `db/backup.py`:
`@dataclass(frozen=True, slots=True) class BackupPolicy(enabled=True, keep_daily=KEEP_DAILY,
keep_weekly=KEEP_WEEKLY)`; `rotate_nightly(..., keep_daily=…, keep_weekly=…)`; `BackupService`
gains `policy_of: Callable[[], BackupPolicy]` (after `clock`, defaulting to `BackupPolicy`, so
existing constructions still work); `due()` is False while `not policy_of().enabled`; `run_now`
rotates with the policy's numbers; `status()` adds `enabled`, `keep_daily`, `keep_weekly` and
words `retention` from them. `HouseholdCache.backups: BackupPolicy`; `load_household` fills it;
`app.py:205-210` passes `policy_of=lambda: holder["state"].household.backups`; `update_settings`
refreshes it after the loop; `erase.forget` resets it. The job line stays. **The fixture:**
`_v0_12_0` in `tests/fixtures/db/build.py` (`UPDATE household SET backups_keep_daily = 21,
backups_keep_weekly = 4`) under this revision; `cd backend && uv run python -m
tests.fixtures.db.build <revision>`; commit the SQL (the newest migration of the release needs it,
`docs/RELEASING.md`).

(b) **The copies.** `db/backup.py`: `KIND_NIGHTLY`, `KIND_PRE_MIGRATE`, `KIND_PRE_ERASE`,
`KIND_PRE_RESTORE`; strict patterns `PRE_MIGRATE_RE` (`sunroom.(\d{12}|empty).(\d{8}T\d{6}Z).db`),
`PRE_ERASE_RE` (`sunroom.(\d{8}T\d{6}Z).db`), `PRE_RESTORE_RE` (`sunroom.pre-restore.(\d{8}T
\d{6}Z)(?:-\d+)?.db`); `Copy(name, kind, path, made_at, bytes)`; `list_copies(backup_dir,
data_dir, zone)` newest first by mtime, never a `.partial`; `locate(backup_dir, data_dir, name)`:
full-match exactly one pattern, then stat `(folder, name)`, so no traversal (`../x`,
`sunroom.2026-10-07.db/..`, `data.db`, `full.zip` → None); `BackupBusyError`. `BackupService
.status()["files"]` = the copies as `{name, kind, made_at, bytes}`, plus `busy` (`self._lock
.locked()`); `async remove(name)`: `LookupError` for an unknown name, `BackupBusyError` while a
copy is written, else unlink the file and any `-wal`/`-shm` sibling under the lock. Routes:
`BackupFileOut`; `BackupStatusOut` gains `enabled, keep_daily, keep_weekly, busy, files`; `GET
…/{name}` uses `locate` (404 "That backup doesn't exist." as now); `DELETE /api/admin/backups
/{name}` → 204; a kiosk → 403 `not_on_a_screen` "Remove backups from a signed-in device." (as
Erase: irreversible, never urgent, and a parent's 10-minute grant outlives the parent at the
wall); 404; 409 `backup_busy` "A backup is being written. Try again in a moment." (Removing
today's nightly means the job writes a new one at its next tick after 03:30: fine.)

(c) **Data Only.** `GET /api/admin/backups/data.db` (declared before `/{name}`, like `full.zip`):
`full_backup.make_database_copy()` (a verified `take_backup` into `backups/.download/`) served by
a `FileResponse` subclass that unlinks the copy however the response ends; the same 507/500
mapping as `full.zip` (lift it into one `_fresh_copy(state)` helper both use); media type
`application/vnd.sqlite3`, `Content-Disposition: attachment; filename="sunroom-YYYY-MM-DD.db"`,
`Cache-Control: no-store`. `make_database_copy`'s six-hour sweep already clears a copy a killed
download left.

(d) **The page** (`BackupPage.tsx` rewritten; `parts.tsx` `Group` gains `action?: ReactNode`
drawn at the heading's right). On a device (`own`):

1. **Backups** — action **Back Up Now** (secondary, `pending`, toast "Backed up"); note "A
   checked copy of the data is kept on the server. Photos are files beside it: only Data & Photos
   has them."; Row "Last backup" with the stale line and the `last_error` hint as today; `Switch`
   **Nightly backups**, hint "A copy every night at 3:30."; while on, Row **Daily copies to keep**
   (`Stepper` 1–30, `words` "14 days") and Row **Weekly copies to keep**, hint "The newest copy of
   each earlier week." (`Stepper` 0–12, "8 weeks"); all through `useUpdateSettings` (optimistic,
   "Not saved — …" on refusal, no Save button).
2. **Copies on the Server** — one row per copy: "Wed, Oct 7, 3:30 AM" and "Nightly · 4.2 MB" /
   "Before an upgrade" / "Before Erase Everything" / "Before a restore"; **Download** (an `<a
   download href="/api/admin/backups/{name}">`) and **Remove** (opens **Remove This Copy?** with
   **Remove** (danger) / **Keep It**; toast "Removed the copy from Oct 7"; it asks once because no
   Undo exists). Empty: "No copies yet. The first nightly copy comes tonight." While `busy`, Remove
   is disabled with "A backup is being written."
3. **Download** — note "Save a copy on this device."; **Download…** opens **Download Which?** (the
   ScopeChooser shape): **Data Only** → `/api/admin/backups/data.db`, "A checked copy of the data
   made now: people, calendars, events, lists, tasks, meals, countdowns and settings. A few MB.";
   **Data & Photos** → `/api/admin/backups/full.zip`, "Everything, photos included: this can take
   a while and be large."; after a tap, "The download has started. It's saved when your browser
   says so." and Close.
4. **Restore from a File** — T16 (its group is built there; leave the slot).
5. **Take Your Data with You** — note "One file anyone can open and read: everything you added
   (people, calendars and events, lists, tasks, meals, countdowns and settings) as plain text
   (JSON), for your own records or for moving on. Sunroom can't restore from it; Download is for
   that."; button **Export**.
6. **Start Over** — as today (T1 took its last line).

On a paired screen: groups 1 and 2 only, the list without buttons, no lines pointing elsewhere.
Every new literal is Title Case where the rules test looks ("Back Up Now", "Download…", "Data
Only", "Data & Photos", "Keep It", "Download Which?", "Remove This Copy?", "Export").

**Tests.** `just test-py tests/test_backup.py tests/test_household.py tests/test_migrations.py
tests/test_backup_api.py` (new: the status lists every copy with its kind and the policy; a parent
removes a copy and a wall screen can't; removing is refused while a copy is written; Data Only is
a fresh checked copy that leaves nothing behind; nightly off → nothing due, `run_now` still
writes; the counts in range: 0 daily and 31 → 422, 0 weekly fine; a 0.11.0 household comes out
on with 14 and 8). `just test-fe src/features/settings` (`BackupPage.test.tsx`, the page cases
moved out of `EraseSheet.test.tsx`: the device's groups and buttons; the screen's two groups with
no file buttons and no pointer lines; nightly off hides the counts and PATCHes `backups_enabled`;
Remove asks once then DELETEs; `DownloadSheet.test.tsx`). `e2e/first-run.spec.ts:208` ("Download
Everything" is now behind Download…); a new `e2e/backup.spec.ts` on `desktop`: "Backup on a
computer: nightly on with its counts, Back Up Now in the heading, a Data Only download and a copy
removed", and on `display-1080p`: "a paired screen sees the backups switch and the copies, and
nothing that saves or sends a file". Run `just e2e e2e/backup.spec.ts --project=desktop -g
"computer"` and the first-run spec's Erase case on desktop.

**Docs.** UX §4 Backup row (the six groups, the words, the screen's two); UX §5:579; PLAN §11.1
(the routes), §11.4 (`nightly-backup` reads the policy), §13.7, §14.4 (the counts are the
household's); `docs/RESTORE.md`'s table ("Nightly copies … as many daily and weekly as Settings →
Backup keeps (14 and 8 unless changed)"; Download Backup → Download → Data Only; Download
Everything → Data & Photos); `docs/DEPLOY.md`'s Backups section if it names 14 and 8. ADR 0034 rows
(the policy and its caps; the four kinds; a screen can't remove; Data Only is fresh).

**CHANGELOG** (Added). "Settings → Backup: Nightly backups can be turned off, and you choose how
many daily and weekly copies to keep; every copy on the server is listed, newest first, to download
or remove; one Download button offers Data Only (a fresh copy) or Data & Photos." (Changed) "Back
Up Now sits in the Backups heading; Export says what it is for and is named Export."

**As built.** As planned (migration `202610161644`, fixture `tests/fixtures/db/202610161644.sql`
from `_v0_12_0`), with these differences. `list_copies` and `locate` take the household's zone,
and a copy's `made_at` is the time in its name for the three kinds that carry one, the file's
time only for a nightly copy: a restore moves the old database aside without touching it, so its
file time is the old database's, not the restore's. `remove()` looks the name up first (404
before 409) and unlinks in a thread; `status()` is never `stale` while the nightly copies are off
(Needs Attention already gated on that). Fewer copies to keep takes effect with the next backup,
never at the tap. Beyond the plan: the test server's reset (`/api/_test/reset`) now clears every
copy and what the service remembers, so `e2e/backup.spec.ts` starts like a new server; it would
otherwise list other tests' copies. The page: the Backups note's second sentence ("Photos are
files beside it: only Data & Photos has them.") is on a device only, since a paired screen has no
Data & Photos; "Not yet." and "No copies yet. Back Up Now makes one." while the nightly copies are
off; Weekly copies at 0 reads "None"; each row's Download and Remove are named for their copy
("Remove the copy from Wed, Oct 7, 3:30 AM"); "A backup is being written." is the Copies group's
note; Remove This Copy? says "The copy from … goes for good." over its detail line. Download
Which?'s Close sits beside the sheet's own ✕, also named Close (the tests take the last). The
Erase sheet keeps its Download Everything link. The page tests moved from `EraseSheet.test.tsx`
to `BackupPage.test.tsx`; `DownloadSheet.test.tsx` is new; the first-run Erase case opens
Download Which? instead of the old link. Docs: also PRIVACY.md (Export, Download, Remove a
backup, and Settings → Devices, a name T1 missed) and RESTORE.md's steps ("Download Data &
Photos", the list in Settings).

### T16 Restore from a file

- [x] Done (commit: "backup: restore from a file, applied as Sunroom runs itself again")

**Owner's note.** "Add the ability to restore from backup by uploading a backed up db file, or
compressed zip of everything including photos."

**What exists.** Restore is a CLI only, `cmd_restore` in `cli.py:247-371`: the checks (a file;
`check_data_dir`; the instance lock, "Sunroom is running. Stop it first…" `:265-268`;
`backup_kind` `:404-410`; `read_archive` `:418-453` for a zip; free space; extract or copy to
`sunroom.restore.partial.db`; `_checked_database` `:218-244`: `quick_check`, a revision the image
knows), then: bump `auth_epoch` in the copy (`:322-326`, the backup's + 1, which can collide with
live cookies), move the live database with its `-wal`/`-shm` aside as `sunroom.pre-restore
.<stamp>.db*` and swap the copy in (`:336-343`), photos back keeping what's there (`:344-348`),
release the lock. `db/instance_lock.py`: a flock for the process's life; `acquire()` returns early
when this process already holds it (`:23-24`), so the CLI's "is Sunroom running" check would pass
inside the server and its `finally: release()` would drop the server's lock: the CLI code can't be
called as is. `boot.py` `prepare()` (`:204-216`): the lock, `check_known`, `pre_migration_backup`
(`:130-144`), `upgrade`, `verify`, `reconcile_app_meta`. The engines (`db/engine.py`) are captured
by closures all over `app.py` (`:147-149, 164, 174, 187, 221-249`) and every plugin context, the
hub epoch is per process, and the swapped-in database may need migrating: ADR 0027 rejected an
in-process swap for these reasons, and they still hold. Every documented install restarts the
container on exit (`docker-compose.example.yml:10`, `kiosk/install.sh:1049`, `README.md:82`
`--restart unless-stopped`); `just dev` (`--reload`) and `scripts/e2e-server.sh` have no
supervisor. `cli.py` runs `uvicorn.run(app, proxy_headers=False, timeout_graceful_shutdown=10)`
(`:78-89`); the process is PID 1 in the container (`ENTRYPOINT ["sunroom"]`); `sys.orig_argv` is
`['…/bin/sunroom', 'serve']` or `['-m', 'sunroom', 'serve']`; Python's sockets, `os.open` files
and SQLite's handles are close-on-exec. Sessions: cookies checked against an in-memory
`AuthState`; "sign everyone out" is a bumped `app_meta.auth_epoch`, which `load_household` reads at
start. Uploads: `photos/router.read_upload` reads a raw body (no `python-multipart` is installed).
Photos: `store.reconcile` runs at startup. The frontend: `lib/update.ts` `reloadFresh`,
`lib/upload.ts` (error mapping), `lib/events.ts handleMessage` (`session.expired` stops the
stream), `router.tsx:35, 48-57` (a 401 sends a phone to sign-in; an unpaired screen shows its
code).

**Build.**

(a) **`db/restore.py`**, the CLI's checks and moves as functions, and `cmd_restore` re-implemented
on them with every printed and refused sentence kept (`tests/test_restore.py` asserts them):
`RestoreError`; `Summary(file_name, kind, bytes, app_version, schema_revision, needs_upgrade,
created_at, row_counts, photo_files)`; `backup_kind_or_refuse`, `prepare(source, partial,
photos_dir, data_dir)`, `check_database(partial)`, `swap_in(settings, prepared, now)` (the epoch
becomes `max(live, backup) + 1`; the moved-aside copy gets its WAL folded in, `PRAGMA
journal_mode=DELETE`, so it is one file that T15's list can show, download and remove), `aside_
stamp`. Then the stage: a folder `/data/restore/` with `upload.partial`, `staged.db`, `staged.zip`
(zips only), `staged.json` (the Summary), `apply.json` (the marker), `last.json` (the last
outcome); `stage(upload, …) -> Summary` (discards any earlier stage, prepares into
`staged.db.partial` then `os.replace`), `staged()`, `discard()`, `arm(requested_at, device_id)`
(a `quick_check` again, then the marker with fsync), `apply_armed(settings, clock) -> Outcome |
None` (**boot**: no marker → None; the marker present → check `staged.db` again (`quick_check`,
the revision known, room); on any doubt move `restore/` to `restore/failed-<stamp>/`, write
`last.json {ok: false, problem}`, log `boot.restore_set_aside` and return, so a bad stage never
loops; else rewrite the marker as `{"step": "swapping", "aside": "<name>"}` with fsync, `swap_in`
(the live database, `-wal` and `-shm` aside together, `os.replace(staged.db, db)`, `fold_wal`,
photos from `staged.zip` with the existing restore of photos, an `OSError` there recorded, not
fatal), remove the marker and the stage, write `last.json {ok: true, …}`, log `boot.restored`; a
boot that finds a marker at step "swapping" and no `sunroom.db` renames the aside back and reports
it), `last_outcome()`. `boot.prepare()` calls `apply_armed` right after taking the lock and before
`check_known`; `pre_migration_backup`, `upgrade`, `verify` and `reconcile_app_meta` then run as
always, so an older database is upgraded after its pre-migrate copy and `APP_PASSWORD` still wins.

(b) **Routes** (`meta/restore.py`, mounted in `app.py`; all `ParentDep`; a kiosk → 403
`not_on_a_screen` "Restore from a signed-in device."): `GET /api/admin/restore` → `{staged:
RestoreSummaryOut | null, last: RestoreOutcomeOut | null}`; `POST /api/admin/restore`: a raw body
streamed chunk by chunk to `restore/upload.partial` (never into memory), headers `X-Filename`
(shown back, sanitised) and `Content-Length` (411 `length_required` without it; browsers always
send it for a File body), free space checked up front (`free < 2 × length + 64 MB` → 507
`storage_full`), `state.restore_lock` (409 `restore_busy` while another upload or apply runs), then
`asyncio.to_thread(restore.stage, …)`; `RestoreError` → 422 with a code by cause (`not_a_backup`,
`backup_damaged`, `backup_newer`, `zip_not_ours`) and RESTORE.md's sentences; returns the Summary.
`DELETE /api/admin/restore` → 204. `POST /api/admin/restore/apply {password}`: rate-limited and
checked exactly as Erase (`meta/router.py:268-276`; the same bar: nothing added since the copy
survives except in the pre-restore copy), 409 `nothing_staged`; `restore.arm(...)`;
`state.hub.publish("server.restarting", {"reason": "restore"})`; answers `{ok: true}` with a
background task `_restart_soon(state)`: `state.started = False` (health says "starting" from now
on, so the waiter below sees the server go away), `sleep(0.2)` (the answer and the frame leave
first), `plugins.stop_all()` and `jobs.stop()` with bounded waits, then under `db.write_lock` (no
commit mid-flight) `state.restart()`. `AppState.restart` is injected: `create_app(..., restart=)`;
`cli.cmd_serve` passes `boot.reexec` (`os.execv(sys.executable, [sys.executable, *sys.orig_argv
[1:]])` after flushing stdout and stderr; on `OSError`, log and `os._exit(0)` for the restart
policy); the dev server passes `devserver.reload` (uvicorn's `--reload` worker is a spawned child
whose argv is multiprocessing's bootstrap, so it touches a watched `.py` file and the reloader
respawns it, which runs `prepare()`); tests pass a recorder (the default is a logged no-op, so
`openapi` and tests never exec). Why re-exec: the PID and the container stay (Docker sees no exit),
the kernel closes the socket and the flock, and the new process runs boot's own sequence (the
marker, the pre-migrate copy, migrate, verify, reconcile) with no second implementation of it.

(c) **The frontend.** `lib/restart.ts`: a `restarting` store, `announceRestart(reason)`,
`waitForServer({afterGoingAway, everyMs: 1000, forMs: 180_000})` polling `GET /api/health` with
`cache: "no-store"` (first until it isn't `ok` or fails, then until `ok`), `useServerRestart()`
mounted beside `useServerUpdate()` in both shells: on `server.restarting` it shows "Sunroom is
restarting… Sign in again in a moment." and, once health is back, `reloadFresh()`.
`eventRouter.ts`: `server.restarting` → `onRestarting`; `events.ts`: on that frame
`forgetStreamPosition()` and stop (as `session.expired` does) so the stream doesn't churn while
the server is away. `lib/restoreUpload.ts`: `uploadBackup(file, onProgress)` over
`XMLHttpRequest` (progress for a GB zip on a phone; `fetch` has none), headers `X-Sunroom: 1`,
`X-Filename`, `Content-Type: application/octet-stream`; errors mapped like `lib/upload.ts:39-50`,
plus a non-JSON 413 → "The file is bigger than your proxy allows. Raise its upload limit
(docs/DEPLOY.md), or restore from the home network." The group **Restore from a File** on the
Backup page (devices only): note "Put back a copy you downloaded: a .db, or a zip with photos.
Everything on the server is replaced, and every phone and screen signs in again."; **Choose a
File…**, a `<label>` styled as a secondary button over a hidden `<input type="file"
accept=".db,.zip,application/zip,application/vnd.sqlite3">`; the sheet **Restore from a File?**
with `step`: `sending` (a progress bar, "Sending… 42%"), `summary` ("sunroom-2026-10-07.zip, made
Wed, Oct 7, 3:00 PM by Sunroom 0.11.0. It holds 4 people, 12 events, 3 lists, 6 photos…"; "This
copy is older than this Sunroom: it will be brought up to date." when `needs_upgrade`; for a .db
"Photos on the server stay as they are."; always "The data on the server now is kept as a copy
before the restore; anything added since this copy was made is only in that copy."), `password`
("Type the household password to restore it.", **Restore** (danger) / **Keep Everything**),
`restarting` ("Restoring… Sunroom restarts with the copy. Every phone signs in again, and wall
screens show a pair code."; then `waitForServer({afterGoingAway: true})` → `reloadFresh()`; after
three minutes "Sunroom hasn't come back yet. Reload this page in a minute; if it stays away, look
at the server's log."). Closing at `summary` or `password` calls `DELETE /api/admin/restore`. A
`last` outcome with `ok: false` shows above the button: "The last restore didn't go through:
{problem}". What each device sees: the phone that pressed Restore reloads fresh and lands on
sign-in (401: the epoch moved); other phones get the frame, the toast, the wait, the reload,
sign-in; wall screens the same, then `/display` shows the pair code (the normal unpaired screen,
never a dead end); a phone that was asleep hits 401 on its next request and goes to sign-in as
today.

**Tests.** `just test-py tests/test_restore.py tests/test_restore_api.py tests/test_boot.py
tests/test_devserver.py` (`test_restore.py` unchanged plus the epoch above both databases and the
aside being one file; `test_restore_api.py` with `create_app(restart=recorder)`: a zip and a .db
are checked and summarised; what isn't a backup is refused and nothing is staged; damaged or newer
→ RESTORE.md's words; a wall screen and a child's phone can't; no room → the plain answer;
discarding removes the files; apply needs the password and a staged file; apply arms the restore,
`StreamProbe` sees `server.restarting`, the plugins stop, the marker is on disk, the recorder was
called, health says 503 meanwhile; `test_boot.py`: an armed restore is applied before migrations
and signs everyone out; an armed older database (stage `fixtures/db/202610141930.sql`) is
upgraded after a pre-migrate copy; a bad staged file is set aside and the current database boots,
twice; a restore interrupted mid-swap puts the database back; `boot.reexec` runs the same command
line again and frees the lock (a `python -c` child that takes the flock, records its pid, calls
`reexec()`, and on its second life exits 7 with the same pid); `test_devserver.py`: the dev
server's restart touches a watched file). `just test-fe src/features/settings src/lib`
(`RestoreSheet.test.tsx`: sent → summary → password → waits → `reloadFresh`; closing discards; a
refusal's words; `restart.test.ts`: `waitForServer` treats a 503 and a thrown fetch as not yet,
gives up at the limit, `useServerRestart` reloads once; the event router and events additions).
`e2e/backup.spec.ts`, "Restore from a file: a zip made here brings the data back, Sunroom
restarts and every device signs in again" on `desktop` (`test.setTimeout(120_000)`; a wall context
paired first; the zip from `page.request.get("/api/admin/backups/full.zip")`; `setInputFiles
({name, mimeType: "application/zip", buffer})`; expect `/sign-in`, the wall's "Pair This Screen",
`signInPhone` again, the event back, a "Before a restore" copy listed). The e2e server re-execs
in place (the PID bash waits on is unchanged; Playwright checks the URL only at start). Run
`just e2e e2e/backup.spec.ts --project=desktop -g "Restore"`.

**Docs.** `docs/RESTORE.md`: a first section "From the app" (choose the file, the summary, the
password, the restart; the pre-restore copy in the list; the CLI stays for a server that won't
start; the "-wal comes along" sentence goes); `docs/DEPLOY.md` §2's proxy table gains "Uploads
(Restore from a file)" (nginx `client_max_body_size 0;`, Caddy `request_body max_size`,
Cloudflare's 100 MB limit on the free plan) and the 413 sentence; PLAN §11.1 (the routes, the
`server.restarting` frame), §13.7 (restore from the app; the CLI for a stopped server), §14.4 (an
armed restore applied after the lock); UX §4 Backup row (the group and the sheet); CLAUDE.md
gotcha: "An in-app restart can't `exec` under `uvicorn --reload`: the worker is a spawned child
with multiprocessing's argv. The dev server touches a watched file instead." ADR 0034 rows (stage
and re-exec, why not in-process (ADR 0027's reasons still hold), the marker consumed at boot, the
password, screens can't restore or remove).

**CHANGELOG** (Added). "Settings → Backup → Restore from a File: choose a copy you downloaded
(Data Only, or Data & Photos), see what it holds, type the household password, and Sunroom
restarts with it; every phone signs in again and wall screens show a pair code. The data from
before is kept on the server as a copy."

**As built.** As planned, with these differences. `db/restore.py` has the plan's pieces; `swap_in`
takes the stamp so the marker can name the moved-aside file before anything moves, and
`prepare` closes the zip again (the photos come back through `photos_back`, which reads it once
more). `full_backup.ArchiveError` gained a `code`, so the API names each cause. The summary's
photo count comes from the zip's own entries (pictures, not thumbnails), not the manifest.
`apply_armed` handles three interrupted cases, not one: the database moved aside and nothing in
its place (put back), the copy in place (finish the photos and the tidying), neither moved (swap
again). `boot.reexec` exits 1, not 0, if `execv` itself fails, so an `on-failure` restart policy
starts it too. `devserver.reload` writes its own file's bytes back. The upload also answers 400
for a body longer or shorter than its `Content-Length`, and `X-Filename` is percent-decoded. The
summary step's button is **Restore This Copy…** (the plan didn't name it), and a refused file
gets its own step with the server's words and Close. The sheet doesn't reload itself: the
shells' `useServerRestart` does, for every page alike (one wait per page however often the wall
remounts its shell; no toast on the page that asked, which sets `askingHere` before the apply
because the frame can come before the answer; a server seen "ok" for 15 s counts as having
restarted between two looks); the sheet keeps its three-minute line. The stream's status reads
"connecting" after the frame. `ui/Button.tsx` gained `FileButton`. Found by the e2e case:
`.then(refresh)` handed the waiter's `true` to `reloadFresh` as its reload function; it is
`() => refresh()` now, and the unit test checks the call. Also ADR 0027's status (a T17 item)
and PLAN §11.5's `server.restarting`. Tests: `test_restore.py` (one more), `test_restore_api.py`
(9), `test_boot.py` (5 more, the re-exec in a child process), `test_devserver.py`,
`restart.test.tsx`, `RestoreSheet.test.tsx`, the router, stream and Backup page tests, and the
e2e case, which restarts the test server in place.

### T17 Wrap up the batch

- [x] Done (commit: "docs: M6 batch 6 wrapped up")

1. **The full gate.** `just check`; the whole `just e2e`; `just screenshots`. Fix what fails;
   a failure is traced by running the failing spec at each task's commit. Review, against UX §10
   and `.screenshots/before-0.11.0/`: on `display-1080p` and `display-portrait`:
   `board-standard-{light,dark}-{0940,1610,2130}` (the tips strip under every board now; the
   attention icon absent while nothing is wrong), `board-hours-zoomed-*` (the strip and the
   multi-color bars on the seed's shared events), `view-people`, `settings-display` (the hint),
   `settings-backup`, `settings-support`, `settings-about`, `settings-calendars` (Default
   reminder), `settings-chores` (Stars), `settings-change-a-person` (twelve swatches),
   `display-attention`; on `desktop`: `setup-household` (the theme row), `setup-done`,
   `settings-backup`; on the phones: `setup-*`, `settings-backup-*`, `settings-support-*`,
   `settings-about-*`, `today-*` (no pill without problems).
2. **ADR 0034**: every row filled as built; its README row; the annotations in ADR 0007 (T14),
   0017 and 0018 (T13), 0027 (T16), 0029 (T6), 0030 (T12), 0031 (T5).
3. **PLAN §15.** The M6 heading "→ 0.7.0 … 0.11.0" → "… 0.12.0"; a batch 6 paragraph after
   batch 5's: "Batch 6 (the owner's notes of 2026-10-15) is in `docs/M6-batch-6.md`, built in
   0.12.0 (ADR 0034): devices and paired screens in every sentence; setup with 8 characters, Home,
   Family and the theme; About's words and its author; the Location note; Return to the calendar
   after honoured by Settings; tips on by default; four more colors; stars for several children
   with a custom amount; room around a chosen person; Support Sunroom with Send Feedback; the
   people a title names and chips in their colors; reminders that come back and a default
   reminder; Needs Attention; any reverse proxy with nothing to set; a refresh that shows the new
   version; the Backup page rebuilt with a policy, the copies, one Download and Export explained;
   and Restore from a file." Every PLAN line the tasks name.
4. **UX.** Every line the tasks name; read §2's words, §4's Settings table and §8 once more as a
   whole.
5. **CLAUDE.md.** The status line: "batch 6 (docs/M6-batch-6.md, ADR 0034) for 0.12.0"; the
   architecture map gains `problems/` and `db/restore.py`; the gotchas from T14 and T16. Under
   15 KB: move lines to `docs/GOTCHAS.md` if needed.
6. **GOTCHAS.** Everything that cost time in this batch.
7. **CHANGELOG.** `[Unreleased]` reads as one list in plain English: Added, Changed, Fixed. No
   version heading: the deploy skill writes it.
8. **This file.** Every task's box ticked with its commit, and "As built" filled in where the
   build differed from the plan.
9. **The report to the owner.** What was built and what differs, in a few lines each; the
   database changes (four migrations, forward-only, the 0.12.0 fixture built in T15); the things
   to look at on the wall and a phone: the header (no icon until something is wrong; cut an
   account's password to see it), a shared event's bar, Settings → Backup, Settings → Support
   Sunroom, the Remind row, setup on a fresh volume (the theme); `support.ts` still to fill; the
   owner deploys. Mention that the deploy's `smoke-image` now probes both Host modes.

**As built.** The full gate, and what it found. `just check` failed first on two backend tests
(countdowns, meals) whose expected occurrence lacked T11's `reminders_off` (traced to `056472c`:
T11's quick gate ran only the tests it touched); then green (1,211 backend and 696 frontend
tests, API types, the migration checks, release metadata). The whole `just e2e` failed 4 of 123:
three expectations T1's words left behind (`sync.spec`'s "From a phone" and its QR label "on a
phone", `lists.spec`'s empty-room line, `shell.spec`'s "On the new phone or tablet"; one of the
first was a negative check that had become vacuous and now looks for "From a device"), and a
race in T14's own offline case (with only the page refused, the board replaces the waiting
frame, so the 502 step now expects the board). Run again whole: 123 passed. `just screenshots`
timed out on the wall: T12 names a page that needs attention "…, needs attention", and that
test's account had stopped answering, so its two Calendars & Accounts links take the flag, as
the spec's loops already did. Reviewed against 0.11.0's own set, kept as
`.screenshots/before-0.12.0/` (`before-0.11.0` is older): the boards with the tips strip and no
attention icon, the two-color bar on Movie night, Needs Attention, the wall's Backup page with
its two groups, the laptop's and phones' Backup, the twelve swatches, setup's theme row, Support
Sunroom, the Default reminder, Today with no pill. The screenshot spec captures only the top of
Backup, so the lower groups and both sheets were checked in full-page shots from a scratch
server (not kept). Docs: ADR 0034's consequences for T13 to T16 and its README row; PLAN §15;
UX §8 (the restart, no copies yet); CLAUDE.md's status and map, with one gotcha moved to
GOTCHAS.md (14.8 KB); GOTCHAS.md's new sections; the CHANGELOG as one list; more follow-ups
below. `just scan` clean.

## Follow-ups noticed but not in this batch

- A per-calendar switch for "people from the title" if a family's names are common words (Will,
  Grace, Mark); the fix today is setting Who by hand on that event.
- The "New version · Refresh" pill shows once on a phone after a refresh that already loaded the
  new build (T14); a `GET_VERSION` message from the worker would let the pill compare versions.
- `lib/events.ts:164-170`: by the EventSource spec, `lastEventId` carries forward onto frames
  without an `id:` (pings, `session.expired`), which the client may read as a gap and reconnect;
  the unit tests' fake sends an empty id, so they can't catch it. (Checked in T16: the
  `server.restarting` frame goes through the hub, so it has an `id:` in sequence and isn't
  affected.)
- `PinDialog` is mounted only in the display shell; on a child's phone an `asParent` call waits
  for a dialog that never appears (seen while reading `SettingsScreens`).
- A backup failure shows in Needs Attention within five minutes (the poll), not at once; a
  `publish` from `BackupService` would make it immediate.
- `KEEP_PRE_MIGRATE = 5` stays a constant; the list shows those copies and lets a parent remove
  them, which is enough.
- The owner's "any audits in the future": `people_from_title` on `EventOut` says whether Sunroom
  guessed; an "assigned by title" line in the event sheet would make it visible.
- Found while building: the restore's refusals keep the CLI's words, which name "Download
  everything" (the button is Data & Photos now), and the Erase sheet's link still says Download
  Everything. One rename across `full_backup`, `db/restore`, `tests/test_restore.py` and
  RESTORE.md's table would settle it.
- Without `APP_ALLOWED_HOSTS`, a page rebound from the home network could finish setup on a
  server nobody has set up yet (accepted in ADR 0034); `POST /api/setup` could keep the strict
  Host rule even without the lock.
- A wall reloaded while the server is down shows its empty frame, with no offline pill, until the
  server answers (the pill lives in the shells); and a phone with no network at all waits a few
  seconds on a blank page before the saved app opens (the router waits for the session request
  to give up, since TanStack's online manager starts online).
- Still open from batch 5: the header's worst-case row with a three-digit temperature; night icons
  in the forecast's hours; "Tonight" after 6 PM; sunrise and sunset never shown; the phone's
  weather block; a per-screen Rolling week; and batch 4's and 3's lists.
