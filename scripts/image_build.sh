#!/usr/bin/env bash
# Build and push the multi-arch release image from `git archive vX.Y.Z` (docs/PLAN.md §14.5).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/image_common.sh
V_FILE="$(tr -d '[:space:]' < VERSION)"
REF="v$V_FILE"
git rev-parse -q --verify "refs/tags/$REF" >/dev/null || { echo "tag $REF does not exist" >&2; exit 1; }
image_args "$REF"
if docker buildx imagetools inspect "$IMAGE:$V" >/dev/null 2>&1; then
  echo "$IMAGE:$V already exists on Docker Hub; released versions are never overwritten." >&2
  exit 1
fi
echo "Building and pushing $IMAGE:$V (linux/amd64, linux/arm64) from $REF…"
# From 1.0 a household can pin how far an update goes (ADR 0046): :1 takes minors and patches, :1.0
# patches only, and the updater companion follows whichever is written.
TAGS=(-t "$IMAGE:$V" -t "$IMAGE:${V%.*}" -t "$IMAGE:latest")
[ "${V%%.*}" -ge 1 ] && TAGS+=(-t "$IMAGE:${V%%.*}")
git archive --format=tar "$REF" | docker buildx build "${ARGS[@]}" \
  --platform linux/amd64,linux/arm64 --provenance=mode=min --sbom=false \
  "${TAGS[@]}" --push -
echo "Pushed ${TAGS[*]//-t /}."
