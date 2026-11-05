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

## Consequences

- One request a day from each install, which GitHub can see. The tests keep the check off unless they
  are about it (`tests/support.py`), so no test reaches for GitHub by accident.
- Phase A's later tasks add to this record as they're built.
