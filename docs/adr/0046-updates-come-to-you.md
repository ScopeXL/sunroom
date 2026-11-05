# ADR 0046: Updates come to you

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

- A Sunroom in Docker on a server never updated itself, and a family heard of a new version only if a
  parent found a switch that was off by default. 1.0 promises that the install command is typed once
  and every install hears about a new version the day it comes out (docs/V1.md, Phase A).
- The check read GitHub's list of tags, so a version counted the moment its tag was pushed, about ten
  minutes before its image and files were out (docs/RELEASING.md).

## Decision

- **The daily check is on by default**, with **Tell me about new versions** in About to turn it off and
  `SUNROOM_UPDATE_CHECK=0` to keep it off. PRIVACY.md says what it sends. Setup doesn't ask.
- **Every household gets it**, by a data migration. Nothing ever recorded a choice of Off, and a new
  column couldn't tell who had made one, so the plan's "a household that chose Off keeps Off" isn't
  buildable. Only the owner's install exists yet; the CHANGELOG says so and the switch is in About.
- **Nothing goes out before setup:** jobs run at start, and a server nobody has set up has no reason
  to tell GitHub its address.
- **It reads `sunroom.day/version.json`, then the latest Release**: the site writes that file when a
  Release is published, and the deploy skill publishes the Release last, so a version counts once its
  image and files are out. A draft or a pre-release never counts. Uptime Kuma, Immich and Home
  Assistant do the same: no rate limit, and the only address that sees a household's request is the
  project's own. GitHub stands behind it when the site doesn't answer, and `SUNROOM_UPDATE_URL`
  points at a self-hoster's own copy. Sunroom Screen reads the same way; its files still come from
  GitHub, checked against `SHA256SUMS`.
- **A new version reaches the family in Needs Attention** (`update:available`, page About; how to
  update is a parent's, as other details are), announced by `update.available` on the live stream.
- **The test server answers only when a test asks** (Check Now), or a version it made up would stand
  in every test's Needs Attention.
- **Every install kind has true words** (`api.update.how.*`, each sent with its key): Compose,
  Portainer, Unraid, CasaOS, Synology, any other app, a Pi, a computer, and Home Assistant's add-on
  to come. The compose example sets `SUNROOM_INSTALL_KIND` from a variable, so a Portainer stack can.

- **The updater companion in the compose example** (Watchtower's maintained continuation, pinned by
  digest) installs new versions overnight, a day after they come out. It's the only thing that
  touches Docker, watches Sunroom alone by its label, and publishes no port. From its source at 1.24.0:
  `HTTP_API_ENDPOINTS` replaces the deprecated `HTTP_API_UPDATE`, and `HTTP_API_PERIODIC_POLLS` must be
  on, because the HTTP API alone turns the schedule off: a compose file without it would never install
  anything overnight, and say nothing.
- **Update Now waits out a version's first day, as the companion does.** Its cooldown gates `/v1/update`
  as well as the schedule, and no request can ask it not to. A button there would do nothing, so About
  says "It installs itself overnight, a day after it comes out." instead. The day is the point: a bad
  release can be pulled back before any household takes it. By hand, `docker compose pull` still works.
- **Sunroom asks before it promises** (`/readyz`, hourly, every minute while it's missing). About and
  Needs Attention say "It installs itself tonight" only while the companion answers and can reach
  Docker: it may have been deleted from the file, or have stopped.
- **The call doesn't wait** (`?async=true`). Waiting would hold a request open in Sunroom while the
  companion is trying to stop Sunroom. Every page hears `server.updating`, shows the quiet pill, and
  reloads when the server is back; if it never goes (a failed pull), the pill goes after three minutes.
- **About says "overnight", not the hour.** The hour is in the compose file, where a household can
  change it, and it reads `TZ`, which may be unset.
- **Images gain a major tag from 1.0**, so a household can pin how far an update goes.

- **A Pi with Sunroom in Docker looks after itself** (`update.sh`, kept for `--with-sunroom` and
  `--server-only`, which leave the README): a failed pull is tried again within the hour; a version
  that never turns healthy goes back by itself, restoring the pre-migration copy when the old version
  refuses the database, and is held until something newer than what failed is out, so it doesn't
  fail nightly or stay stuck. A version the family pinned stays. `--server-only` gets a morning timer.
  `update.sh` says how it ended in a file beside it, so the screen can say so without touching the
  root helper.

- **A NAS's own app keeps it up to date.** A CasaOS and ZimaOS store (`deploy/casaos`, their v2 format,
  built by their own action and published to GitHub Pages with each release, with the `main.zip` older
  clients read), an Unraid template for Community Applications (`deploy/unraid`), and the compose file
  in Synology's Container Manager. CasaOS gets a named volume rather than an AppData folder: Sunroom's
  user must be able to write there. `just deploy-check` keeps them all saying the same thing, and fails
  a compose file whose updater would lose its schedule.

- **A screen says why Sunroom is away.** Can't Reach says "Sunroom is updating. This screen comes back
  by itself." for five minutes after it hears so, from the wall's page (`server.updating`) or its own
  update, and otherwise "The computer that runs Sunroom may be off or restarting."

- **The install line never changes.** `curl -fsSL https://sunroom.day/install.sh | bash` and `irm
  https://sunroom.day/install.ps1 | iex`: the site redirects them to the newest Release's own copies,
  so nobody runs a branch and the line outlives every release. `github.com/…/releases/latest/download/`
  is the fallback, and the same files. A Release serves them with no charset, which Windows PowerShell
  reads as Latin-1, so install.ps1 stays plain ASCII. **Running it again keeps what the screen has:**
  an option given this time wins, and whatever's left out stays: rotation, connector, dimming, the
  screen helper, the morning update (so those last two got their way back, `--screen-helper` and
  `--auto-update`). A kept connector gives way only when a screen is plugged in elsewhere and none is
  on it. **What the installer downloads is checked before it's used:** the kiosk folder is now a file
  of the Release (`kiosk-X.Y.Z.tar.gz`, in `SHA256SUMS`, instead of GitHub's generated archive, whose
  bytes GitHub doesn't promise), and uv's installer against a pinned sum.

- **Sunroom run as a program goes back as a Pi's Docker Sunroom does.** It's kept once it answers as
  the new version; one that never does, within ten minutes on a Pi and five elsewhere because a long
  migration isn't a failure, goes. The version before comes back with `sunroom restore` of its
  pre-migrate copy when the database's revision moved (each migration run is one transaction, and the
  server never answered, so nothing can be lost), without which it would refuse to start (exit 65);
  that version isn't tried again by itself. What Sunroom is at comes from what Sunroom Screen
  remembered it installing, not from asking it, so a computer's restart that starts Sunroom Screen
  first can't leave it behind (the plan's `health_tick` idea wasn't needed); a download that failed is
  tried again within the hour, and the wall shows **Updating Sunroom…** for it, as on a Pi.

## Consequences

- One request a day from each install, which GitHub can see. The tests keep the check off unless they
  are about it (`tests/support.py`), so no test reaches for GitHub by accident.
- Phase A's later tasks add to this record as they're built.
