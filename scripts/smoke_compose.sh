#!/usr/bin/env bash
# The compose example for real (docs/DEPLOY.md, ADR 0046): Sunroom and the updater companion from
# docker-compose.example.yml, on a volume of their own. An older release stands in as "latest", then
# the companion is asked for the update: through Sunroom's Update Now when that release has it, its
# API directly when not. Sunroom must come back newer, on the same volume, and the schedule must still
# be running. Needs Docker and Docker Hub; touches nothing outside this project, except that the local
# scopexl/sunroom:latest goes.
#
#   smoke_compose.sh [OLD]   OLD: a release on Docker Hub, or `head`: this checkout, stamped 0.1.0,
#                            so it asks the real site or GitHub and takes the real Update Now path.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/image_common.sh
OLD="${1:-0.18.0}"
PROJECT="sunroom-smoke-compose"
APP="sunroom-smoke-app"
UPDATER="sunroom-smoke-updater"
VOLUME="sunroom_smoke_data"
PORT=17869
BASE="http://127.0.0.1:$PORT"
WORK="$(mktemp -d)"
FILE="$WORK/docker-compose.yml"
JAR="$WORK/jar"

compose() { docker compose -p "$PROJECT" -f "$FILE" "$@"; }
cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  docker image rm "$IMAGE:latest" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# The example file itself, with only what keeps this run apart from a real Sunroom on this computer.
# PORT: a release from before 1.0 answers on 8080 unless it's told.
perl -pe '
  s|"7867:7867"|"127.0.0.1:'"$PORT"':7867"|;
  s|name: sunroom_data|name: '"$VOLUME"'|;
  s|container_name: sunroom-updater|container_name: '"$UPDATER"'|;
  s|container_name: sunroom$|container_name: '"$APP"'|;
  s|^(\s*)TZ: \$\{TZ:-\} # the household.*$|$&\n$1PORT: "7867"|;
' docker-compose.example.yml >"$FILE"
compose config -q || fail "the compose example doesn't parse"

compose down -v --remove-orphans >/dev/null 2>&1 || true
if [ "$OLD" = head ]; then
  OLD=0.1.0
  STANDS_IN="this checkout, stamped $OLD"
  image_args HEAD
  ARGS+=(--build-arg "VERSION=$OLD")
  mkdir "$WORK/tree"
  git archive --format=tar HEAD | tar -x -C "$WORK/tree"
  echo "$OLD" >"$WORK/tree/VERSION"
  docker buildx build "${ARGS[@]}" -t "$IMAGE:latest" --load "$WORK/tree" >/dev/null
else
  STANDS_IN="$OLD"
  docker pull -q "$IMAGE:$OLD" >/dev/null
  docker tag "$IMAGE:$OLD" "$IMAGE:latest"
fi
echo "Starting Sunroom ($STANDS_IN) and the updater from the compose example…"
compose up -d --quiet-pull 2>/dev/null
wait_healthy "$APP" 120
[ "$(curl -fsS "$BASE/api/version" | jq -r .version)" = "$OLD" ] || fail "not running $OLD"
BEFORE="$(docker inspect -f '{{.Image}}' "$APP")"

# A household on the volume, to find again afterwards.
status="$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR" "${CSRF[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"password":"smoke-password-0000","household_name":"Smoke Test Home","timezone":"Etc/UTC"}' \
  "$BASE/api/setup")"
[ "$status" = 201 ] || fail "setup through the API answered $status"

# The schedule: Watchtower's HTTP API turns it off unless HTTP_API_PERIODIC_POLLS says otherwise.
for _ in $(seq 1 30); do
  compose logs sunroom-updater 2>/dev/null | grep -q 'Next scheduled run' && break
  sleep 1
done
compose logs sunroom-updater 2>/dev/null | grep -q 'Next scheduled run' || {
  compose logs sunroom-updater >&2
  fail "the updater isn't keeping a schedule, so nothing would install overnight"
}
echo "The updater keeps its schedule."

# Sunroom's own Update Now when this release has it, and the companion's API when it doesn't.
answer="$(curl -fsS -b "$JAR" "$BASE/api/admin/update")"
if [ "$(jq -r '.updater // false' <<<"$answer")" = true ]; then
  curl -fsS -b "$JAR" "${CSRF[@]}" -X POST "$BASE/api/admin/update/check" >/dev/null || true
  answer="$(curl -fsS -b "$JAR" "$BASE/api/admin/update")"
  jq -c '{current, latest, available, updater, update_now, how}' <<<"$answer"
  [ "$(jq -r .update_now <<<"$answer")" = true ] || fail "Update Now isn't on offer"
  [ "$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "${CSRF[@]}" -X POST \
    "$BASE/api/admin/update")" = 202 ] || fail "Update Now was refused"
  echo "Asked through Update Now."
else
  docker exec "$APP" python -c '
import os, urllib.request
request = urllib.request.Request(
    os.environ["SUNROOM_UPDATER_URL"] + "/v1/update?async=true",
    method="POST",
    headers={"Authorization": "Bearer " + os.environ["SUNROOM_UPDATER_TOKEN"]},
)
assert urllib.request.urlopen(request).status == 202
' || fail "the updater refused the update"
  echo "Asked the updater directly ($STANDS_IN has no Update Now)."
fi

# The swap: a new container under the same name, from a newer image.
for _ in $(seq 1 300); do
  AFTER="$(docker inspect -f '{{.Image}}' "$APP" 2>/dev/null || true)"
  [ -n "$AFTER" ] && [ "$AFTER" != "$BEFORE" ] && break
  sleep 1
done
[ -n "$AFTER" ] && [ "$AFTER" != "$BEFORE" ] || {
  compose logs sunroom-updater >&2
  fail "the updater never replaced Sunroom"
}
echo "The updater replaced Sunroom."
[ "$(docker inspect -f '{{range .Mounts}}{{.Name}} {{end}}' "$APP")" = "$VOLUME " ] \
  || fail "the new container isn't on the same volume"
docker inspect -f '{{json .Config.Labels}}' "$APP" | grep -q 'watchtower.enable' \
  || fail "the new container lost its label, so the next update would miss it"
docker inspect -f '{{json .Config.Env}}' "$APP" | grep -q 'SUNROOM_UPDATER_URL' \
  || fail "the new container lost its settings"

if [ "$STANDS_IN" != "$OLD" ]; then
  echo "Stopping at the swap: the newest release can't open a database this checkout migrated."
  echo "Update Now works from $STANDS_IN."
  exit 0
fi
wait_healthy "$APP" 180
NOW="$(curl -fsS "$BASE/api/version" | jq -r .version)"
[ "$NOW" != "$OLD" ] || fail "still running $OLD"
[ "$(curl -fsS "$BASE/api/setup/status" | jq -r .setup_complete)" = true ] \
  || fail "the household is gone: not the same volume"
[ "$(curl -fsS "$BASE/api/discover" | jq -r .name)" = "Smoke Test Home" ] \
  || fail "the household's name is gone: not the same volume"
[ "$(curl -fsS -b "$JAR" "$BASE/api/auth/session" | jq -r .device_kind)" = phone ] \
  || fail "the session didn't survive the update"
echo "Sunroom $OLD updated itself to $NOW on the same volume."
