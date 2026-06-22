"""
RomM Metadata API — /api/v1/romm/*

Manage title_id → rom_id mappings, proxy RomM search, and resolve display names.
RomM is metadata-only; it has no influence on snapshot lineage or sync state.

Resolution priority: custom label > RomM cache > titledb US > titledb JP.
Cache consistency: romm_game_cache fills asynchronously after PUT /mapping.
  A GET /titles/{id} immediately after PUT may return cache_pending=true — this is expected.
"""

import logging
import re
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
import game_meta
import romm_meta
import romm_vsc
import ui_api

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/romm", tags=["romm"])

_conn = None
_staging_dir = None
_archive_dir = None

_TITLE_RE = re.compile(r"^[A-Fa-f0-9]{16}$")


def init(conn, staging_dir=None, archive_dir=None) -> None:
    global _conn, _staging_dir, _archive_dir
    _conn = conn
    _staging_dir = staging_dir
    _archive_dir = archive_dir


def _load_user_romm_creds(username: str) -> JSONResponse | None:
    """Set thread-local RomM creds from user_config. Returns 503 if not configured."""
    host = db.get_user_config(_conn, username, "romm_host") or romm_meta.ROMM_HOST
    key = db.get_user_config(_conn, username, "romm_api_key") or romm_meta.ROMM_API_KEY
    if not host or not key:
        return JSONResponse({"error": "RomM not configured for this user"}, status_code=503)
    romm_meta.set_request_creds(host, key)
    return None


def _sync_romm_catalog(username: str) -> None:
    """Rebuild device_installed_games for the user's RomM virtual device."""
    romm_device_id = romm_vsc.get_user_romm_device_id(_conn, username)
    try:
        db.sync_romm_catalog_to_device(_conn, username, romm_device_id)
    except Exception as exc:
        log.warning("romm_api: catalog sync failed: %s", exc)


def _valid_title(v: str) -> str | None:
    """Normalize to uppercase canonical form; return None if invalid."""
    return v.upper() if _TITLE_RE.match(v) else None


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def _resolve(title_id: str, username: str) -> dict:
    title_id = title_id.upper()
    rom_id = db.get_romm_rom_id(_conn, username, title_id)
    cached = db.get_romm_game_cache(_conn, username, rom_id) if rom_id else None

    romm_name = cached["name"] if cached else None
    romm_icon = cached["icon_url"] if cached else None

    display = game_meta.game_display_name(_conn, title_id, username)
    icon = game_meta.game_icon_url(_conn, title_id, username)

    custom = db.get_label(_conn, "game", title_id)
    if custom:
        source = "custom_label"
    elif romm_name:
        source = "romm"
    elif display:
        source = "titledb"
    else:
        source = None

    return {
        "title_id": title_id,
        "display_name": display,
        "icon_url": icon,
        "name_source": source,
        "rom_id": rom_id,
        "romm_name": romm_name,
        "romm_icon_url": romm_icon,
        "cache_pending": rom_id is not None and cached is None,
    }


# ── Search ────────────────────────────────────────────────────────────────────


@router.get("/search")
def search_roms(request: Request, q: str = "", limit: int = 10):
    err = ui_api._auth_err(request)
    if err:
        return err
    if not q:
        return _err("q is required")
    username = ui_api._current_username(request)
    cred_err = _load_user_romm_creds(username)
    if cred_err:
        return cred_err
    results = romm_meta.search_roms(q, limit=min(limit, 50))
    return {"results": results}


# ── Title mapping list ────────────────────────────────────────────────────────


@router.get("/titles")
def list_mappings(request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    username = ui_api._current_username(request)
    mappings = db.get_romm_title_map(_conn, username)
    cache = db.get_all_romm_game_cache(_conn, username)
    result = []
    for m in mappings:
        cached = cache.get(m["rom_id"], {})
        result.append(
            {
                "title_id": m["title_id"],
                "rom_id": m["rom_id"],
                "name": cached.get("name"),
                "icon_url": cached.get("icon_url"),
                "mapped_at": m["mapped_at"],
            }
        )
    return {"mappings": result}


# ── Per-title metadata resolution ─────────────────────────────────────────────


@router.get("/titles/{title_id}")
def get_title(title_id: str, request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    tid = _valid_title(title_id)
    if not tid:
        return _err("title_id must be 16 hex characters")
    username = ui_api._current_username(request)
    return _resolve(tid, username)


# ── Mapping management ────────────────────────────────────────────────────────


class MappingBody(BaseModel):
    rom_id: int


@router.put("/titles/{title_id}/mapping")
def put_mapping(title_id: str, body: MappingBody, request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    tid = _valid_title(title_id)
    if not tid:
        return _err("title_id must be 16 hex characters")
    if body.rom_id <= 0:
        return _err("rom_id must be a positive integer")

    username = ui_api._current_username(request)
    # Atomically remove any existing mapping for this rom_id before upserting.
    # romm_title_map has UNIQUE(username,rom_id), so without this delete,
    # re-mapping rom_id=X to a different title_id raises IntegrityError and silently drops.
    db.delete_romm_title_map_by_rom_id(_conn, username, body.rom_id)
    db.upsert_romm_title_map(_conn, username, tid, body.rom_id)
    _sync_romm_catalog(username)
    romm_meta.fetch_and_cache(body.rom_id, _conn, username)

    cached = db.get_romm_game_cache(_conn, username, body.rom_id)
    name = cached["name"] if cached else None
    log.info("romm map title=%s → rom_id=%d name=%r user=%s", tid, body.rom_id, name, username)
    romm_vsc.push_head_async(tid)
    return {"ok": True, "name": name, "cache_pending": cached is None}


@router.delete("/titles/{title_id}/mapping")
def delete_mapping(title_id: str, request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    tid = _valid_title(title_id)
    if not tid:
        return _err("title_id must be 16 hex characters")
    username = ui_api._current_username(request)
    db.delete_romm_title_map(_conn, username, tid)
    _sync_romm_catalog(username)
    return {"ok": True}


# ── Cache warm ────────────────────────────────────────────────────────────────


@router.post("/cache/warm")
def cache_warm(request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    username = ui_api._current_username(request)
    host = db.get_user_config(_conn, username, "romm_host") or romm_meta.ROMM_HOST
    key = db.get_user_config(_conn, username, "romm_api_key") or romm_meta.ROMM_API_KEY
    if host and key:
        romm_meta.set_request_creds(host, key)
    romm_meta.warm_cache(_conn, username)
    return JSONResponse({"ok": True}, status_code=202)


# ── VSC sync controls ─────────────────────────────────────────────────────────


@router.post("/sync/push")
def sync_push(request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    return JSONResponse(
        {"ok": True, "message": "push is automatic per snapshot"},
        status_code=202,
    )


@router.post("/sync/pull")
def sync_pull(request: Request):
    err = ui_api._auth_err(request)
    if err:
        return err
    if _staging_dir is None or _archive_dir is None:
        return JSONResponse({"error": "server not initialized"}, status_code=503)
    threading.Thread(
        target=romm_vsc.pull,
        args=(_staging_dir, _archive_dir),
        daemon=True,
        name="romm-manual-pull",
    ).start()
    return JSONResponse({"ok": True}, status_code=202)


@router.post("/scan")
def trigger_scan(request: Request):
    """Request an immediate title-ID index rebuild.

    Sets the refresh flag consumed by the worker; returns 202 immediately.
    The actual scan runs in background and completes within seconds.
    """
    err = ui_api._auth_err(request)
    if err:
        return err
    import romm_index

    romm_index.request_index_refresh()
    romm_index.maybe_run_index()
    log.info("romm_api: manual scan requested by %s", ui_api._current_username(request))
    return JSONResponse({"ok": True}, status_code=202)
