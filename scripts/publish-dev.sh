#!/bin/bash
# Build and push a dev image to ghcr.io.
# Tags: ghcr.io/kanjieater/omnisave:dev  (floating)
#       ghcr.io/kanjieater/omnisave:dev-<sha>  (immutable)
#
# Usage:
#   ./scripts/publish-dev.sh            # build + push to GHCR
#   ./scripts/publish-dev.sh --no-push  # build with GHCR tags, skip push
#   ./scripts/publish-dev.sh --local    # build as omnisave:local (no registry, no clean-tree check)
set -euo pipefail

REGISTRY="ghcr.io/kanjieater/omnisave"
LOCAL_TAG="omnisave:local"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

NO_PUSH=0
LOCAL=0
for arg in "$@"; do
    [[ "$arg" == "--no-push" ]] && NO_PUSH=1
    [[ "$arg" == "--local" ]]   && LOCAL=1
done

_deploy_hint() {
    local tag="$1"
    echo ""
    echo "  Tag: ${tag}"
    echo "  Use: OMNISAVE_IMAGE=${tag} ./scripts/server.sh up"
}

if [[ "$LOCAL" -eq 1 ]]; then
    echo "Building ${LOCAL_TAG} (local only) ..."
    docker build -t "${LOCAL_TAG}" "${REPO_ROOT}/server"
    _deploy_hint "${LOCAL_TAG}"
    exit 0
fi

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
    echo "Built (push skipped)."
    _deploy_hint "${TAG_SHA}"
    exit 0
fi

echo "Pushing ..."
docker push "${TAG_SHA}"
docker push "${TAG_FLOAT}"

echo "Published."
_deploy_hint "${TAG_SHA}"
echo ""
echo "  Tag (floating): ${TAG_FLOAT}"
