#!/usr/bin/env bash
# Build an amd64 image from `git archive REF`, run it on an empty volume with no settings at all,
# probe it, finish setup through the API, and check it refuses a bad data folder (PLAN §14.6).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/image_common.sh
REF="${1:-HEAD}"
image_args "$REF"
TAG="sunroom:smoke"
NAME="sunroom-smoke"
PORT=17867
JAR="$(mktemp)"

cleanup() {
  docker rm -f "$NAME" "$NAME-root" "$NAME-novol" "$NAME-locked" >/dev/null 2>&1 || true
  docker volume rm "$NAME" "$NAME-root" "$NAME-locked" >/dev/null 2>&1 || true
  rm -f "$JAR"
}
trap cleanup EXIT
cleanup

echo "Building $TAG from $REF (version $V, linux/amd64)…"
git archive --format=tar "$REF" | docker buildx build "${ARGS[@]}" --platform linux/amd64 -t "$TAG" --load -

# No environment at all: Sunroom makes its own secret key and asks for setup (ADR 0006).
run_app() {
  local name="$1"; shift
  docker run -d --name "$name" --platform linux/amd64 "$@" "$TAG" >/dev/null
}

docker volume create "$NAME" >/dev/null
run_app "$NAME" -p "127.0.0.1:$PORT:7867" -v "$NAME:/data"
wait_healthy "$NAME" 90
probe "$PORT" "$V"
[ "$(docker exec "$NAME" id -u)" = 10001 ] || fail "not running as uid 10001"
set_up "$PORT" "$JAR"
[ "$(docker exec "$NAME" stat -c %a /data/secret.key)" = 600 ] || fail "the secret key isn't 0600"

docker restart "$NAME" >/dev/null
wait_healthy "$NAME" 90
copies="$(docker exec "$NAME" sh -c 'ls /data/backups/pre-migrate 2>/dev/null | wc -l' | tr -d ' ')"
[ "$copies" = 0 ] || fail "a restart took a new pre-migration backup"
[ "$(curl -fsS -b "$JAR" "http://127.0.0.1:$PORT/api/auth/session" | jq -r .device_kind)" = phone ] \
  || fail "the session didn't survive a restart"

# The optional lock (ADR 0034): with APP_ALLOWED_HOSTS set, only local names and those listed.
docker volume create "$NAME-locked" >/dev/null
run_app "$NAME-locked" -p "127.0.0.1:$((PORT + 1)):7867" -v "$NAME-locked:/data" \
  -e APP_ALLOWED_HOSTS=calendar.example.com
wait_healthy "$NAME-locked" 90
locked="http://127.0.0.1:$((PORT + 1))/api/version"
[ "$(curl -so /dev/null -w '%{http_code}' -H 'Host: evil.example' "$locked")" = 421 ] \
  || fail "with the lock set, an unknown Host wasn't refused with 421"
[ "$(curl -so /dev/null -w '%{http_code}' -H 'Host: calendar.example.com' "$locked")" = 200 ] \
  || fail "with the lock set, a listed Host wasn't answered"
docker rm -f "$NAME-locked" >/dev/null

# Negative cases: a root-owned volume and no volume at all must both refuse to start (exit 73).
docker volume create "$NAME-root" >/dev/null
# Docker re-copies the image's /data ownership into a volume while it is empty, so leave a file
# behind: this simulates a root-owned host folder (a bind mount), the case that really fails.
docker run --rm --platform linux/amd64 --user 0 --entrypoint sh -v "$NAME-root:/data" "$TAG" \
  -c 'touch /data/.root-owned && chown -R 0:0 /data && chmod 755 /data'
run_app "$NAME-root" -v "$NAME-root:/data"
expect_exit() { # NAME CODE: wait up to 60 s for the container to stop with CODE
  local code
  code="$(timeout_wait "$1" 60)"
  [ "$code" = "$2" ] || { echo "$1 exited with '$code', expected $2" >&2; docker logs --tail 5 "$1" >&2; exit 1; }
}
expect_exit "$NAME-root" 73
run_app "$NAME-novol"
expect_exit "$NAME-novol" 73

uv run --quiet --no-project --python 3.14 scripts/private_scan.py image "$TAG"
echo "Smoke test passed for $V ($REF)."
