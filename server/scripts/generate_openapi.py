#!/usr/bin/env python3
"""Generate openapi.json from the FastAPI app definition.

Run from repo root after changing any routes:

    python server/scripts/generate_openapi.py > server/src/openapi.json

Does not start the server, connect to a database, or load runtime config.
"""
import json
import os
import sys

os.environ.setdefault("OMNISAVE_DATA", "/tmp")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from main import app  # noqa: E402

print(json.dumps(app.openapi(), indent=2))
