#!/usr/bin/env bash
# Starts the real backend serving the production frontend build, for Playwright: test mode (the
# reset, seed and clock endpoints, localhost only), a throwaway data folder, and no APP_PASSWORD,
# so the first-run wizard runs as a family would see it.
#
# Beside it, Sunroom Screen's agent in --fake mode on 127.0.0.1:4174 (ADR 0035): a pretend
# screen (no browser, no commands) serving the screen's own pages from the same build, which
# finds this backend as a Sunroom on its "network". It's started first and waited for, so when
# Playwright sees the backend's health both are up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$(mktemp -d)"
AGENT_PID=""
SERVER_PID=""
stop() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -rf "$DATA"
}
trap stop EXIT INT TERM

(cd "$ROOT/kiosk/agent" && exec uv run --quiet sunroom-kiosk run --fake pi --port 4174 --log-level warning \
  --config "$DATA/screen/config" --fake-sunroom http://127.0.0.1:4173) &
AGENT_PID=$!
for _ in $(seq 1 120); do
  curl -fs -o /dev/null http://127.0.0.1:4174/api/screen && break
  sleep 0.25
done

export APP_SECRET_KEY="e2e-only-secret-key-0123456789abcdef"
export TZ="America/New_York"
export PORT=4173
export DATA_DIR="$DATA"
export SUNROOM_TEST_MODE=1
# What a phone should open, as kiosk/install.sh sets it on a Pi (the wall itself is on loopback).
export SUNROOM_ADVERTISED_URL="http://sunroom.local:4173"
export SUNROOM_STATIC_DIR="$ROOT/frontend/dist"
# Send Feedback is on (ADR 0042): in test mode the server keeps what it would post
# (GET /api/_test/feedback) and posts nothing, so this address is never reached.
export SUNROOM_FEEDBACK_URL="https://feedback.invalid/"
export LOG_LEVEL=WARNING
cd "$ROOT/backend"
uv run sunroom serve --host 127.0.0.1 &
SERVER_PID=$!
wait "$SERVER_PID"
