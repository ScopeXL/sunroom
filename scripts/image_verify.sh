#!/usr/bin/env bash
# Verify the pushed image: both architectures, matching tags, the probes on a fresh volume with no
# settings at all, setup through the API, and the private scan.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/image_common.sh
V="$(tr -d '[:space:]' < VERSION)"
platforms="$(docker buildx imagetools inspect --raw "$IMAGE:$V" \
  | jq -r '.manifests[].platform | select(.os == "linux") | .os + "/" + .architecture' | sort | tr '\n' ' ')"
[ "$platforms" = "linux/amd64 linux/arm64 " ] || { echo "unexpected platforms: $platforms" >&2; exit 1; }
digest() { docker buildx imagetools inspect "$1" --format '{{json .Manifest}}' | jq -r .digest; }
D="$(digest "$IMAGE:$V")"
for tag in "${V%.*}" latest; do
  [ "$(digest "$IMAGE:$tag")" = "$D" ] || { echo "$IMAGE:$tag does not point at $D" >&2; exit 1; }
done
NAME="sunroom-verify"
PORT=17868
JAR="$(mktemp)"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME" >/dev/null 2>&1 || true; rm -f "$JAR"' EXIT
for arch in amd64 arm64; do
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$NAME" >/dev/null 2>&1 || true
  docker pull --quiet --platform "linux/$arch" "$IMAGE@$D" >/dev/null
  docker volume create "$NAME" >/dev/null
  docker run -d --name "$NAME" --platform "linux/$arch" -p "127.0.0.1:$PORT:7867" -v "$NAME:/data" \
    "$IMAGE@$D" >/dev/null
  wait_healthy "$NAME" 120
  probe "$PORT" "$V"
  set_up "$PORT" "$JAR"
done
uv run --quiet --no-project --python 3.14 scripts/private_scan.py image "$IMAGE@$D"
echo "Verified $IMAGE:$V ($D): amd64 + arm64, tags agree, probes and setup pass, private scan clean."
