# Sunroom: every command lives here (CLAUDE.md "Commands"). `just` lists them.
set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := false

# OrbStack's docker CLI may not be on PATH in every shell.
export PATH := env_var("HOME") + "/.orbstack/bin:" + env_var("PATH")

# Repo scripts run on a modern Python via uv (the system python3 may be old).
py := "uv run --quiet --no-project --python 3.14"
shellcheck := "uvx --quiet --from shellcheck-py shellcheck"

default:
    @just --list --unsorted

# ---- setup and development ------------------------------------------------------------------

# Install tools and dependencies, git hooks, a local .env and the private-terms list
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in uv pnpm gitleaks jq; do
      command -v "$tool" >/dev/null || { echo "Missing $tool: brew install $tool"; exit 1; }
    done
    (cd backend && uv sync --locked)
    (cd frontend && pnpm install --frozen-lockfile && pnpm exec playwright install chromium webkit)
    git config core.hooksPath .githooks
    if [ ! -f .env ]; then
      cp .env.example .env
      echo "Created .env (development settings; the server makes its own secret key)."
    fi
    {{py}} scripts/private_scan.py setup

# Run the backend (auto-reload) and the Vite dev server together
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    (cd backend && uv run --env-file ../.env sunroom serve --reload --host 127.0.0.1) &
    (cd frontend && pnpm dev) &
    wait

# Load the synthetic "Sample Family" into the running dev server (fake data only)
seed PORT="8080":
    curl -fsS -X POST "http://127.0.0.1:{{PORT}}/api/_test/seed" \
      -H 'X-Sunroom: 1' -H 'Content-Type: application/json' -d '{}' \
      && echo "Seeded the Sample Family. Household password: e2e-household-passphrase"

# Open the built app's wall screen in Chromium, paired, with sample data (--portrait, --unpaired, --fresh)
display *ARGS: build
    cd frontend && node scripts/display.mjs {{ARGS}}

# ---- checks (CI runs `just check`) -----------------------------------------------------------

# Format everything
fmt:
    cd backend && uv run ruff format . && uv run ruff check --fix .
    cd frontend && pnpm exec prettier --write .

# Lint and format checks: backend, frontend and the kiosk scripts
lint: kiosk-lint
    cd backend && uv run ruff check . && uv run ruff format --check .
    cd frontend && pnpm exec eslint . && pnpm exec prettier --check .

# shellcheck on the installer and its helpers; the labwc rule and the root helper compile; Sunroom
# Screen's agent (kiosk/agent) passes ruff and pyright strict
kiosk-lint:
    {{shellcheck}} -x kiosk/install.sh kiosk/uninstall.sh kiosk/update.sh
    {{py}} -m py_compile kiosk/labwc-rule.py kiosk/files/sunroom-kiosk-root
    @if command -v pwsh >/dev/null 2>&1; then pwsh -NoProfile -Command 'if (-not (Get-Module -ListAvailable PSScriptAnalyzer)) { "PSScriptAnalyzer is not installed here; CI runs it on Windows."; exit 0 }; $found = Invoke-ScriptAnalyzer -Path kiosk/install.ps1 -Severity Warning,Error -ExcludeRule PSAvoidUsingWriteHost; $found | Format-Table -AutoSize RuleName,Line,Message; if ($found) { exit 1 }'; else echo "install.ps1: no pwsh here; CI runs PSScriptAnalyzer on Windows."; fi
    cd kiosk/agent && uv run --quiet ruff check . && uv run --quiet ruff format --check . && uv run --quiet pyright

# Sunroom Screen's pages in development: the pretend agent on 7800 (finding `just dev`'s Sunroom on
# 8080) and Vite's screen shell on http://127.0.0.1:5174
kiosk-dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    (cd kiosk/agent && uv run sunroom-kiosk run --fake pi --dev --fake-sunroom http://127.0.0.1:8080) &
    (cd frontend && pnpm dev:screen) &
    wait

# Sunroom Screen's wheel, with its pages built in (frontend/src/screen into the package's static/)
kiosk-build:
    cd frontend && pnpm exec vite build --config vite.screen.config.ts
    cd kiosk/agent && rm -rf dist && uv build --wheel --out-dir dist

# Sunroom as a program (ADR 0038): the server wheel, with the built app inside and VERSION stamped
# in, and its constraints from backend/uv.lock, in backend/dist
server-build:
    cd frontend && pnpm exec vite build
    {{py}} scripts/server_wheel.py

# Try this checkout's installers on another computer or a virtual machine on this network before a
# release: both wheels, then the installers served with them and each system's one line
kiosk-serve PORT="8765": kiosk-build server-build
    {{py}} scripts/kiosk_serve.py {{PORT}}

# Sunroom Screen's agent: its tests, on the pretend platform (no network, no machine changes)
[positional-arguments]
kiosk-test *ARGS:
    cd kiosk/agent && uv run --quiet pytest -q "$@"

# Type checks: pyright strict, tsc
typecheck:
    cd backend && uv run pyright
    cd frontend && pnpm exec tsc -b

# Unit and API tests (no network)
test:
    cd backend && uv run pytest -q --disable-socket --allow-unix-socket
    cd frontend && pnpm exec vitest run

# The per-task gate (CLAUDE.md "Definition of done"): lint and type checks, about a minute
quick: lint typecheck

# Vitest, quietly, for a file, a folder or `related src/ui/Sheet.tsx` (nothing: all of it)
[positional-arguments]
test-fe *ARGS:
    cd frontend && pnpm exec vitest --run --reporter=dot "$@"

# pytest, quietly, for a file or a folder such as `tests/countdowns` (nothing: all of it)
[positional-arguments]
test-py *ARGS:
    cd backend && uv run pytest -q --disable-socket --allow-unix-socket "$@"

# Regenerate the frontend's API types from the backend's OpenAPI schema, and the screen agent's
api-types:
    cd backend && uv run sunroom openapi --out ../frontend/src/api/openapi.json
    cd frontend && pnpm exec openapi-typescript src/api/openapi.json -o src/api/schema.d.ts
    cd kiosk/agent && uv run --quiet sunroom-kiosk openapi --out ../../frontend/src/api/screen-openapi.json
    cd frontend && pnpm exec openapi-typescript src/api/screen-openapi.json -o src/api/screen-schema.d.ts

# Fail if the committed API types are stale
api-types-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    (cd backend && uv run sunroom openapi --out "$tmp/openapi.json")
    (cd frontend && pnpm exec openapi-typescript "$tmp/openapi.json" -o "$tmp/schema.d.ts" >/dev/null)
    diff -u frontend/src/api/openapi.json "$tmp/openapi.json"
    diff -u frontend/src/api/schema.d.ts "$tmp/schema.d.ts"
    (cd kiosk/agent && uv run --quiet sunroom-kiosk openapi --out "$tmp/screen-openapi.json")
    (cd frontend && pnpm exec openapi-typescript "$tmp/screen-openapi.json" -o "$tmp/screen-schema.d.ts" >/dev/null)
    diff -u frontend/src/api/screen-openapi.json "$tmp/screen-openapi.json"
    diff -u frontend/src/api/screen-schema.d.ts "$tmp/screen-schema.d.ts"
    echo "API types are up to date."

# Migrations: upgrade an empty database, compare with the models, run the migration tests
migrations-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    cd backend
    DATA_DIR="$tmp" uv run alembic upgrade head
    DATA_DIR="$tmp" uv run alembic check
    uv run pytest -q tests/test_migrations.py --disable-socket --allow-unix-socket

# VERSION is the only version; CHANGELOG has an Unreleased section
release-meta-check:
    {{py}} scripts/check_release_meta.py

# Everything a commit must pass
check: lint typecheck test kiosk-test api-types-check migrations-check release-meta-check

# ---- build, end-to-end, screenshots ------------------------------------------------------------

# Production frontend build
build:
    cd frontend && pnpm build

# End-to-end tests: the wall screen (1080p, portrait), phones (WebKit, Chromium) and a laptop.
# Arguments pick a spec, a project or a test: `e2e/hours.spec.ts --project=display-1080p -g zoom`
[positional-arguments]
e2e *ARGS: build
    cd frontend && pnpm exec playwright test "$@"

# Capture key screens at every size, light and dark, into .screenshots/ for review
screenshots: build
    cd frontend && SCREENSHOTS=1 pnpm exec playwright test screenshots
    @echo "Review every image in .screenshots/ against docs/UX.md §10 before calling UI work done."

# The real CalDAV client against a throwaway Radicale container, with the ICS fixtures (opt-in)
smoke-caldav:
    #!/usr/bin/env bash
    set -euo pipefail
    NAME="sunroom-caldav-smoke"
    PORT=15232
    cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
    trap cleanup EXIT
    cleanup
    # A random password for a container that lives a minute. It travels by environment only.
    CALDAV_SMOKE_PASSWORD="$(openssl rand -hex 16)"
    export CALDAV_SMOKE_PASSWORD
    docker run -d --name "$NAME" -p "127.0.0.1:$PORT:5232" -e CALDAV_SMOKE_PASSWORD \
      python:3.14-slim sh -c '
        pip install --quiet --disable-pip-version-check --root-user-action=ignore "radicale>=3,<4" &&
        printf "ana:%s\n" "$CALDAV_SMOKE_PASSWORD" > /tmp/users &&
        exec python -m radicale --server-hosts 0.0.0.0:5232 --auth-type htpasswd \
          --auth-htpasswd-filename /tmp/users --auth-htpasswd-encryption plain \
          --storage-filesystem-folder /tmp/collections' >/dev/null
    echo "Starting Radicale…"
    for _ in $(seq 120); do
      curl -fs -o /dev/null "http://127.0.0.1:$PORT/.web/" && break
      sleep 1
    done
    curl -fs -o /dev/null "http://127.0.0.1:$PORT/.web/" \
      || { echo "Radicale didn't start:"; docker logs --tail 20 "$NAME"; exit 1; }
    cd backend
    CALDAV_SMOKE_URL="http://127.0.0.1:$PORT/" CALDAV_SMOKE_USER=ana uv run python scripts/caldav_smoke.py

# ---- privacy -----------------------------------------------------------------------------------

# gitleaks (history + working tree) and the private-terms scan (tree + unpushed commits)
scan:
    #!/usr/bin/env bash
    set -euo pipefail
    gitleaks git --redact --no-banner .
    # The working tree as git sees it (tracked + untracked, not ignored). `gitleaks dir` alone
    # would also read ignored files such as .env, which can hold real secrets on purpose and can
    # never reach git or the image (images are built from `git archive`).
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    git ls-files -co --exclude-standard -z | while IFS= read -r -d '' file; do
      [ -f "$file" ] || continue
      mkdir -p "$tmp/$(dirname "$file")" && cp "$file" "$tmp/$file"
    done
    gitleaks dir --redact --no-banner --config .gitleaks.toml "$tmp"
    {{py}} scripts/private_scan.py tree
    {{py}} scripts/private_scan.py history

hook-pre-commit:
    gitleaks git --pre-commit --staged --redact --no-banner .
    {{py}} scripts/private_scan.py staged

hook-commit-msg FILE:
    {{py}} scripts/private_scan.py msg {{FILE}}

hook-pre-push RANGE:
    {{py}} scripts/private_scan.py range {{RANGE}}

# ---- release (run by the deploy skill; see .claude/skills/deploy) --------------------------------

# Build an amd64 image from git, run it and probe it (setup through the API on an empty volume)
smoke-image REF="HEAD":
    scripts/smoke_image.sh {{REF}}

# The full release gate; stamps the tree it passed on
preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "Release from main."; exit 1; }
    [ -z "$(git status --porcelain)" ] || { echo "Commit or discuss uncommitted changes first."; exit 1; }
    if git rev-parse --verify --quiet origin/main >/dev/null; then
      git fetch --quiet origin main
      [ "$(git rev-list --count HEAD..origin/main)" = 0 ] || { echo "main is behind origin/main."; exit 1; }
    fi
    # The release pushes without a terminal, so prove that works before anything is tagged.
    # A dry run sends nothing, so it skips the pre-push hook; `just scan` below covers those commits.
    GIT_TERMINAL_PROMPT=0 git push --dry-run --no-verify --quiet origin main \
      || { echo "The dry-run push to GitHub failed (above). See docs/RELEASING.md, Pushing to GitHub."; exit 1; }
    # The next migration is tested against this release's data, so its fixture must ship with it.
    head="$(cd backend && uv run --quiet python -c 'from sunroom.db import migrate; print(migrate.head_revision())')"
    [ -f "backend/tests/fixtures/db/$head.sql" ] \
      || { echo "Build the fixture database for migration $head first (docs/RELEASING.md, The fixture database)."; exit 1; }
    just check
    just e2e
    just scan
    {{py}} scripts/private_scan.py context HEAD
    just smoke-image HEAD
    [ "$(docker context show)" = orbstack ] || { echo "Switch Docker to OrbStack: docker context use orbstack"; exit 1; }
    docker info --format '{{{{json .DriverStatus}}' | grep -q io.containerd.snapshotter.v1 \
      || { echo "Docker needs the containerd image store for multi-arch builds."; exit 1; }
    jq -e '.auths["https://index.docker.io/v1/"]' ~/.docker/config.json >/dev/null \
      || { echo "Log in to Docker Hub first: docker login -u scopexl"; exit 1; }
    git rev-parse 'HEAD^{tree}' > .git/sunroom-preflight
    echo "Preflight passed."

# Bump VERSION (patch|minor|major), roll the CHANGELOG, lock released migrations
bump LEVEL:
    {{py}} scripts/release.py bump {{LEVEL}}

# Commit the release files, tag vX.Y.Z, push branch + tag together (run again to resume a push)
release-tag TRAILER="":
    {{py}} scripts/release.py tag --trailer {{quote(TRAILER)}}

# The tag's GitHub Release, its CHANGELOG section as the notes (release-assets.yml adds the files)
github-release:
    {{py}} scripts/release.py github

# Build and push the multi-arch image for the current VERSION's tag
image:
    scripts/image_build.sh

# Verify the pushed image (both arches, tags agree, probes, private scan)
image-verify:
    scripts/image_verify.sh

# The whole release without Claude: preflight, bump, tag, the GitHub Release, smoke, push, verify
release LEVEL:
    just preflight
    just bump {{LEVEL}}
    just release-tag
    just github-release
    just smoke-image "v$(cat VERSION)"
    just image
    just image-verify

# ---- helpers ----------------------------------------------------------------------------------

# Show a backup's migration revision, app version and row counts
inspect-backup FILE:
    cd backend && uv run sunroom inspect-backup {{FILE}}

# Create a new migration (autogenerated against a temporary database at head)
db-revision MSG:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    cd backend
    DATA_DIR="$tmp" uv run alembic upgrade head
    DATA_DIR="$tmp" uv run alembic revision --autogenerate --rev-id "$(date -u +%Y%m%d%H%M)" -m "{{MSG}}"
