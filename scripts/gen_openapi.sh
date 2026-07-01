#!/usr/bin/env bash
# Regenerate server/src/openapi.json from the live app routes.
# Uses the Docker test image (no live server needed).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

docker compose run --rm test python - << 'PYEOF'
import sys, json, tempfile
sys.path.insert(0, "/app/server/src")
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
(tmp / "staging").mkdir()
(tmp / "archive").mkdir()

import database as db
conn = db.open_db(tmp / "spec.db")

import main, sync_api, sync_deliver_api, activity_api, ui_api
sync_api.init(conn, tmp / "staging", tmp / "archive")
sync_deliver_api.init(conn, tmp / "staging", tmp / "archive")
activity_api.init(conn)
ui_api.init(conn, tmp / "archive")

from fastapi.testclient import TestClient
spec = TestClient(main.app).get("/openapi.json").json()

out = Path("/app/server/src/openapi.json")
out.write_text(json.dumps(spec, indent=2) + "\n")
print(f"Regenerated {out}")
PYEOF
