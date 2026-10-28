# Releasing

The owner says **deploy**; the `deploy` skill ([`.claude/skills/deploy/SKILL.md`](../.claude/skills/deploy/SKILL.md))
does the rest. This page explains the pieces, and how to release without Claude.

## What a release is

- A version bump in `VERSION`: patch by default, minor when the household can see something new,
  major only when the owner asks. Each milestone is a minor release.
- The same version in the installers (`KIOSK_VERSION` in `kiosk/install.sh`, `$KioskVersion` in
  `kiosk/install.ps1`), which are fetched from main, and in Sunroom Screen (`kiosk/agent/pyproject.toml` and its entry in
  `kiosk/agent/uv.lock`), whose wheel is named for it.
- A plain-English `CHANGELOG.md` section.
- An annotated git tag `vX.Y.Z` that is never moved.
- A GitHub Release `vX.Y.Z` with that section as its notes, and its files, which
  `.github/workflows/release-assets.yml` builds on GitHub when the tag is pushed: Sunroom
  Screen's wheel (`sunroom_kiosk-X.Y.Z-py3-none-any.whl`, its pages built in), Sunroom's server
  wheel (`sunroom-X.Y.Z-py3-none-any.whl`, the app built in and the version stamped in by
  `scripts/server_wheel.py`, as `just server-build` does) with its constraints
  (`sunroom-X.Y.Z-constraints.txt`, from `backend/uv.lock`) for Sunroom run as a program on a
  computer (ADR 0038), `install.sh` and `install.ps1`, and `SHA256SUMS`, uploaded last. The
  installers and Sunroom Screen's own updates take the wheels from there and check them against
  `SHA256SUMS`; nothing is uploaded from the Mac. Sunroom's own update check stays on tags (ADR 0032).
- A multi-arch image (`linux/amd64`, `linux/arm64`), `scopexl/sunroom:X.Y.Z`, also tagged `X.Y`
  and `latest`. Version tags are immutable on Docker Hub.

## The pipeline

| Step | Command | Stops the release when |
|---|---|---|
| Gate | `just preflight` | Not on main, uncommitted changes, behind origin, a dry-run push to GitHub fails, the newest migration has no fixture database, any check/e2e/scan failure, smoke-test failure, Docker not ready |
| Version | `just bump <level>` | `[Unreleased]` is empty |
| Tag | `just release-tag ["Co-Authored-By: …"]` | Anything besides `VERSION`, `CHANGELOG.md`, `released.lock`, the installers (`kiosk/install.sh`, `kiosk/install.ps1`) and Sunroom Screen's `pyproject.toml` and `uv.lock` changed since preflight. If only the push fails, run it again: it resumes |
| GitHub Release | `just github-release` | The tag isn't on GitHub, or `gh` isn't signed in. It makes the Release (or publishes the draft the workflow made) and prints its URL; run it again any time |
| Smoke | `just smoke-image vX.Y.Z` | The image from the tag doesn't start healthy on an empty volume with no settings, fails a probe or setup through the API, or starts on a bad volume |
| Push | `just image` | The version already exists on Docker Hub |
| Verify | `just image-verify` | Platforms missing, tags disagree, the pulled image fails a probe or setup on either architecture, or the image scan finds a private term |
| CI | `gh run watch` on the run the push started | Never: the release is out by then. Its result goes in the report, green or the failing jobs with the run's link, and a red run is fixed in a working session, never from the deploy |
| The Release's files | `gh run watch` on the tag's release-assets run, then `gh release view` | Never, as CI. It waits up to 10 minutes for the Release, then makes a draft of its own; until its files are up, installers and screens can't install or update to this version |

Without Claude: `just release patch` runs all of it.

## GitHub's checks

The release gate is local (`just preflight` runs everything on the Mac), and GitHub runs the
same checks as jobs when the release is pushed, plus the end-to-end suite on Linux browsers and
a secrets scan. Its e2e job failed on every release from 0.5.0 to 0.9.1 without anyone seeing
it: the two long accessibility journeys took longer than Playwright's default 30 seconds on
GitHub's 4-CPU runner. They have the time they need now (ADR 0032), the job caches its browsers
and stops after 45 minutes, and the deploy skill waits for the run and reports it.

## One-time setup on the build Mac

- **OrbStack** running, with Docker on its context (`docker context use orbstack`) and the
  containerd image store.
- **Docker Hub:**
  1. Create the repository `scopexl/sunroom` (public).
  2. Create a personal access token: Read & Write, no Delete, with an expiry.
  3. Run `docker login -u scopexl` and paste the token at the prompt. It's kept in the macOS
     keychain, never in a file in this repo.
  4. In Docker Hub: **Repository → Settings → Immutable tags**, with the rule `^\d+\.\d+\.\d+$`.
- **Private-terms list:** `just setup` walks you through creating
  `~/.config/sunroom/private-terms.txt`. Preflight refuses to release without it.
- **GitHub:** pushes go over SSH; see *Pushing to GitHub* below. The GitHub CLI signed in
  (`gh auth login`, then `gh auth status`) makes the Release and watches the runs.
- **The release workflow, once:** push a throwaway pre-release tag (for example
  `git tag v0.13.1-rc.1 && git push origin v0.13.1-rc.1`), or run it by hand on one (Actions →
  Release assets → Run workflow). It makes a draft pre-release with the files; check them, then
  delete the draft and the tag. (Sunroom OS's card image was built here too until 0.16.1; it is
  retired, ADR 0042.)

## Pushing to GitHub

A release pushes without a terminal, so git must reach GitHub without asking for a password.
Preflight checks this with a dry-run push before anything is tagged.

- This repo's remote uses SSH: `git remote get-url origin` shows
  `git@github.com:ScopeXL/sunroom.git`, and `ssh -T git@github.com` answers
  "Hi <your GitHub name>!".
- To switch a clone that uses HTTPS, run
  `git remote set-url origin git@github.com:ScopeXL/sunroom.git`.
- An HTTPS remote works only with a saved login whose token has the `workflow` scope, because
  releases include `.github/workflows/`.
- If a release's push fails anyway, the release commit and tag stay on this Mac. Fix access, then
  run `just release-tag` again: it pushes them without re-tagging.

## Rolling back

- **If the release didn't change the database** (no new migration), set the previous version
  in `docker-compose.yml` (`image: scopexl/sunroom:X.Y.Z`) and run `docker compose up -d`.
- **If it did,** restore the pre-upgrade copy ([RESTORE.md](RESTORE.md)), then deploy the
  previous tag.

Migrations are forward-only: a released migration is listed with its checksum in
`backend/src/sunroom/migrations/released.lock`, and a test fails if one changes.

## The fixture database

A release whose newest migration is new needs `backend/tests/fixtures/db/<revision>.sql` for
that revision, or the first migration written after the release fails its test. Build the
fixture for the released revision in the task that adds the migration, before the release: add
the revision's synthetic rows to `SEEDS` in `backend/tests/fixtures/db/build.py`, run
`cd backend && uv run python -m tests.fixtures.db.build <revision>`, and commit the file.
`just preflight` refuses a release whose newest migration has no fixture (0.9.0 shipped without
one, and a line here hadn't stopped it).
