#!/usr/bin/env bash
# Wipe and restart the dev OmniSave instance at /mnt/srv/omnisavedev.
# NEVER touches /mnt/srv/omnisave (prod).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEV_ROOT="/mnt/srv/omnisavedev"
COMPOSE="$DEV_ROOT/docker-compose.yml"
ENV="$DEV_ROOT/.env"
DATA="$DEV_ROOT/data"

echo "==> Stopping omnisavedev..."
OMNISAVE_ROOT="$DEV_ROOT" docker compose -f "$COMPOSE" --env-file "$ENV" down

echo "==> Wiping DB..."
rm -f "$DATA/omnisave.db" "$DATA/omnisave.db-shm" "$DATA/omnisave.db-wal"

echo "==> Clearing staging and archive..."
find "$DATA/staging" -mindepth 1 -delete 2>/dev/null || true
find "$DATA/archive" -mindepth 1 -delete 2>/dev/null || true

echo "==> Starting fresh..."
OMNISAVE_ROOT="$DEV_ROOT" "$SCRIPT_DIR/server.sh" up
