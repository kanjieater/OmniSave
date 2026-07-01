#!/usr/bin/env bash
# Regenerate server/src/openapi.json from the running server.
# Run after any API change (new route, changed schema, new path param annotation).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$REPO_ROOT/server/src/openapi.json"

"$SCRIPT_DIR/server.sh" up

echo "Waiting for server to be ready..."
for i in $(seq 1 30); do
    curl -sf http://localhost:8991/openapi.json > /dev/null 2>&1 && break
    sleep 1
done

curl -sf http://localhost:8991/openapi.json > "$OUT"
echo "Regenerated $OUT"
