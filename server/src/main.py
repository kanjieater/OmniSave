"""OmniSave Server — entry point."""

import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

import database as db
import romm_api
import romm_index
import romm_meta
import romm_vsc
import romm_worker
import startup
import sync_api
import sync_deliver_api
import titledb
import ui_api

DATA_DIR = Path(os.environ.get("OMNISAVE_DATA", "/app/data"))
ARCHIVE_DIR = DATA_DIR / "archive"
STAGING_DIR = DATA_DIR / "staging"
DB_PATH = DATA_DIR / "omnisave.db"
PORT = int(os.environ.get("OMNISAVE_PORT_INTERNAL", "8991"))

_static_candidates = [
    Path(__file__).parent.parent / "static",
    Path(__file__).parent.parent / "ui" / "dist",
]
STATIC_DIR = next((p for p in _static_candidates if p.exists()), _static_candidates[0])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("omnisave")

_start_time = datetime.now(UTC).isoformat()


def _gc_loop(db_path: Path, staging_dir: Path, archive_dir: Path) -> None:
    conn = db.open_db(db_path)
    while True:
        time.sleep(900)
        try:
            startup.run_periodic(conn, staging_dir, archive_dir)
        except Exception as e:
            log.error("periodic gc error: %s", e)


app = FastAPI(title="OmniSave", version="1.0.0")
app.include_router(sync_api.router)
app.include_router(sync_deliver_api.router)
app.include_router(ui_api.router)
app.include_router(romm_api.router)


@app.get("/api/health")
def health():
    return {
        "service": "OmniSave",
        "status": "online",
        "version": "1.0.0",
        "started_at": _start_time,
    }


_static_root: Path | None = None


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_HASHED_EXTS = {".js", ".css", ".woff2", ".woff", ".ttf", ".png", ".svg", ".ico"}


@app.get("/{full_path:path}", include_in_schema=False)
def spa_serve(full_path: str):
    root = _static_root
    if root is None or not root.exists():
        return JSONResponse({"error": "UI not built"}, status_code=503)
    try:
        target = (root / full_path).resolve()
        if not str(target).startswith(str(root.resolve())):
            return JSONResponse({"error": "forbidden"}, status_code=403)
    except Exception:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if target.is_file():
        headers = _IMMUTABLE if target.suffix in _HASHED_EXTS else _NO_CACHE
        return FileResponse(str(target), headers=headers)
    index = root / "index.html"
    return (
        FileResponse(str(index), headers=_NO_CACHE)
        if index.exists()
        else JSONResponse({"error": "not found"}, status_code=404)
    )


def main():
    global _static_root

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    conn = db.open_db(DB_PATH)
    log.info("database: %s", DB_PATH)

    startup.run(conn, STAGING_DIR, ARCHIVE_DIR)

    sync_api.init(conn, STAGING_DIR, ARCHIVE_DIR)
    sync_deliver_api.init(conn, STAGING_DIR, ARCHIVE_DIR)
    ui_api.init(conn, ARCHIVE_DIR)
    romm_api.init(conn, STAGING_DIR, ARCHIVE_DIR)
    romm_meta.init(DB_PATH)
    romm_meta.reload_config(conn)
    if romm_meta.ROMM_HOST and romm_meta.ROMM_API_KEY:
        romm_meta.load_or_create_device_id(conn)
    # RomM virtual devices are per-user; registered on demand, not at startup.
    conn.commit()
    titledb.prefetch()
    romm_meta.warm_cache_all(conn)
    romm_vsc.start_pull_loop(STAGING_DIR, ARCHIVE_DIR)
    romm_worker.start_worker_loop()

    t = threading.Thread(
        target=_gc_loop, args=(DB_PATH, STAGING_DIR, ARCHIVE_DIR), daemon=True
    )
    t.start()

    _static_root = STATIC_DIR
    if STATIC_DIR.exists():
        log.info("serving UI from %s", STATIC_DIR)
    else:
        log.warning("UI not built — dashboard unavailable")

    log.info("HTTP on :%d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
