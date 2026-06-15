#!/bin/bash
# Build and push a dev image to ghcr.io.
# Tags: ghcr.io/kanjieater/omnisave:dev  (floating)
#       ghcr.io/kanjieater/omnisave:dev-<sha>  (immutable)
#
# Usage:
#   ./scripts/publish-dev.sh            # build from current commit
#   ./scripts/publish-dev.sh --no-push  # build only, skip push
set -euo pipefail

REGISTRY="ghcr.io/kanjieater/omnisave"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

NO_PUSH=0
for arg in "$@"; do [[ "$arg" == "--no-push" ]] && NO_PUSH=1; done

# Require a clean working tree — dev images must be reproducible.
if ! git -C "$REPO_ROOT" diff --quiet HEAD; then
    echo "ERROR: Uncommitted changes present. Commit or stash before publishing."
    exit 1
fi

SHA=$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD)
TAG_SHA="${REGISTRY}:dev-${SHA}"
TAG_FLOAT="${REGISTRY}:dev"

echo "Building ${TAG_SHA} ..."
docker build \
    --label "org.opencontainers.image.revision=${SHA}" \
    --label "org.opencontainers.image.source=https://github.com/kanjieater/OmniSaveServer" \
    -t "${TAG_SHA}" \
    -t "${TAG_FLOAT}" \
    "${REPO_ROOT}/server"

if [[ "$NO_PUSH" -eq 1 ]]; then
    echo "Built (push skipped):"
    echo "  ${TAG_SHA}"
    echo "  ${TAG_FLOAT}"
    exit 0
fi

echo "Pushing ..."
docker push "${TAG_SHA}"
docker push "${TAG_FLOAT}"

echo ""
echo "Published:"
echo "  ${TAG_SHA}   ← pin this in .env for a specific build"
echo "  ${TAG_FLOAT}  ← always latest dev"
echo ""
echo "To deploy:"
echo "  # floating (auto-pull latest dev):"
echo "  OMNISAVE_IMAGE=${TAG_FLOAT} ./scripts/server.sh up"
echo ""
echo "  # pinned to this commit:"
echo "  OMNISAVE_IMAGE=${TAG_SHA} ./scripts/server.sh up"
