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

## Consequences

- One request a day from each install, which GitHub can see. The tests keep the check off unless they
  are about it (`tests/support.py`), so no test reaches for GitHub by accident.
- Phase A's later tasks add to this record as they're built.
