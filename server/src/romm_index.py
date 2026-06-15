"""
RomM Switch ROM title-ID indexer.

Paginates all ROMs in RomM, filters for platform_id==21 (Nintendo Switch),
fetches each ROM's file list, and maps any title IDs (found in NSP/XCI filenames
as [XXXXXXXXXXXXXXXX]) to the RomM rom_id.  Runs once at startup as a daemon
thread so games without titledb entries still get auto-matched.

Title IDs for base games always end in '000'.  Update titles (ending in '800',
etc.) are ignored — we care only about the base application.
"""

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request

import database as db
import romm_meta

log = logging.getLogger(__name__)

_TITLE_ID_FILE_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
_SWITCH_PLATFORM_ID = 21


def _fetch_switch_rom_ids() -> list[int]:
    """Paginate /api/roms, return rom_ids where platform_id==21."""
    rom_ids: list[int] = []
    offset = 0
    limit = 200
    while True:
        qs = urllib.parse.urlencode({"limit": limit, "offset": offset})
        req = urllib.request.Request(
            f"{romm_meta._effective_host()}/api/roms?{qs}",
            headers=romm_meta._auth_headers(),
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        for r in data.get("items", []):
            if r.get("platform_id") == _SWITCH_PLATFORM_ID:
                rom_ids.append(r["id"])
        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
    return rom_ids


def _base_title_id(detail: dict) -> str | None:
    """Extract the base-game title ID from a ROM detail.

    Checks top-level filename fields first (fs_name, file_name), then the files sub-array.
    RomM stores the primary filename in fs_name, not in files[].
    """
    candidates = [
        detail.get("fs_name", ""),
        detail.get("fs_name_no_tags", ""),
        detail.get("file_name", ""),
    ]
    for f in detail.get("files", []):
        candidates.append(f.get("file_name", ""))
    for candidate in candidates:
        m = _TITLE_ID_FILE_RE.search(candidate)
        if m:
            tid = m.group(1).upper()
            if tid.endswith("000"):
                return tid
    return None


def _fetch_rom_detail(rom_id: int) -> dict | None:
    try:
        req = urllib.request.Request(
            f"{romm_meta._effective_host()}/api/roms/{rom_id}",
            headers=romm_meta._auth_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("romm_index: fetch detail rom_id=%d: %s", rom_id, exc)
        return None


def _build_for_user(conn, username: str, host: str, api_key: str) -> None:
    """Index build for one user. Credentials are set explicitly — no shared state."""
    import titledb as tdb

    romm_meta.set_request_creds(host, api_key)
    try:
        # Candidates: any title on a paired device OR in the upload history, not yet mapped.
        unmapped: set[str] = {
            r["title_id"]
            for r in conn.execute(
                "SELECT DISTINCT title_id FROM ("
                "  SELECT title_id FROM sync_transactions"
                "  UNION"
                "  SELECT title_id FROM device_installed_games"
                ") WHERE title_id NOT IN"
                " (SELECT title_id FROM romm_title_map WHERE username=?)",
                (username,),
            ).fetchall()
        }
        log.info("romm_index: scanning RomM (unmapped=%d) user=%s", len(unmapped), username)
        already_mapped_rom_ids: set[int] = {
            r["rom_id"]
            for r in conn.execute(
                "SELECT rom_id FROM romm_title_map WHERE username=?", (username,)
            ).fetchall()
        }

        # ── Stale cleanup — remove mappings for ROMs deleted from RomM ─────────
        rom_ids = _fetch_switch_rom_ids()
        rom_ids_set = set(rom_ids)
        stale_rom_ids = already_mapped_rom_ids - rom_ids_set
        if stale_rom_ids:
            for stale_id in stale_rom_ids:
                title_row = conn.execute(
                    "SELECT title_id FROM romm_title_map WHERE username=? AND rom_id=?",
                    (username, stale_id),
                ).fetchone()
                conn.execute(
                    "DELETE FROM romm_title_map WHERE username=? AND rom_id=?",
                    (username, stale_id),
                )
                log.info(
                    "romm_index: removed stale mapping rom_id=%d title_id=%s user=%s",
                    stale_id,
                    title_row["title_id"] if title_row else "?",
                    username,
                )
            conn.commit()
            already_mapped_rom_ids -= stale_rom_ids

        # ── Pass 1: file scan — match via [TITLEID] in RomM filenames ────────
        mapped_count = 0
        for rom_id in rom_ids:
            if rom_id in already_mapped_rom_ids:
                continue
            detail = _fetch_rom_detail(rom_id)
            if detail is None:
                continue
            name = detail.get("name") or detail.get("fs_name_no_tags") or detail.get("fs_name")
            title_id = _base_title_id(detail)
            match_method = "file"
            if not title_id and name:
                # Filename has no [TITLEID] — try reverse lookup against titledb
                title_id = tdb.find_title_id_by_name(name)
                match_method = "titledb-name"
            if title_id:
                raw_icon = (
                    detail.get("url_cover")
                    or detail.get("path_cover_large")
                    or None
                    or detail.get("path_cover_small")
                    or None
                )
                icon_url = romm_meta._abs_url(raw_icon)
                db.upsert_romm_title_map(conn, username, title_id, rom_id)
                db.upsert_romm_game_cache(conn, username, rom_id, name, icon_url)
                log.info(
                    "romm_index: %s-matched title=%s → rom_id=%d name=%r user=%s",
                    match_method,
                    title_id,
                    rom_id,
                    name,
                    username,
                )
                unmapped.discard(title_id)
                already_mapped_rom_ids.add(rom_id)
                mapped_count += 1
            time.sleep(0.05)

        # ── Pass 2: name search fallback — for titles still unmatched ─────────
        for title_id in list(unmapped):
            name = tdb.resolve_game_name(title_id)
            if not name:
                continue
            try:
                results = romm_meta.search_roms(name, limit=5)
            except Exception as exc:
                log.debug("romm_index: name search error title=%s: %s", title_id, exc)
                continue
            if len(results) != 1:
                log.debug(
                    "romm_index: name search ambiguous title=%s name=%r results=%d user=%s",
                    title_id,
                    name,
                    len(results),
                    username,
                )
                continue
            rom = results[0]
            if rom["id"] in already_mapped_rom_ids:
                log.debug(
                    "romm_index: name search skipped title=%s — rom_id=%d already mapped user=%s",
                    title_id,
                    rom["id"],
                    username,
                )
                continue
            db.upsert_romm_title_map(conn, username, title_id, rom["id"])
            db.upsert_romm_game_cache(conn, username, rom["id"], rom["name"], rom["icon_url"])
            log.info(
                "romm_index: name-matched title=%s → rom_id=%d name=%r user=%s",
                title_id,
                rom["id"],
                rom["name"],
                username,
            )
            unmapped.discard(title_id)
            mapped_count += 1

        log.info("romm_index: done — %d new mapping(s) user=%s", mapped_count, username)
    except Exception as exc:
        log.warning("romm_index: error user=%s: %s", username, exc)
        request_index_refresh()  # re-queue so next worker cycle retries


def build_title_id_index() -> None:
    """Scan Switch ROMs and map unmatched title IDs for all enabled RomM users."""
    if not romm_meta._db_path:
        return
    try:
        conn = db.open_db(romm_meta._db_path)
    except Exception as exc:
        log.warning("romm_index: cannot open db: %s", exc)
        return
    try:
        users = db.get_romm_users(conn)
    finally:
        conn.close()
    for username in users:
        conn = db.open_db(romm_meta._db_path)
        try:
            host = db.get_user_config(conn, username, "romm_host") or ""
            key = db.get_user_config(conn, username, "romm_api_key") or ""
            romm_device_id = (
                db.get_user_config(conn, username, "romm_source_id") or f"romm:{username}"
            )
            if host and key:
                _build_for_user(conn, username, host, key)
                db.sync_romm_catalog_to_device(conn, username, romm_device_id)
        finally:
            conn.close()


_REFRESH_REQUESTED = threading.Event()
_INDEX_RUNNING = threading.Event()


def request_index_refresh() -> None:
    """Signal that a title-ID lookup missed. Worker will execute on next cycle."""
    _REFRESH_REQUESTED.set()


def maybe_run_index() -> None:
    """Single execution entrypoint — called each worker cycle.

    Launches a background rebuild if a refresh was requested and none is already
    in flight. Coalesces: many request_index_refresh() calls → at most one scan.
    """
    if not _REFRESH_REQUESTED.is_set():
        return
    if _INDEX_RUNNING.is_set():
        return  # scan already running; flag stays set for next cycle
    _REFRESH_REQUESTED.clear()

    def _run() -> None:
        _INDEX_RUNNING.set()
        try:
            build_title_id_index()
        finally:
            _INDEX_RUNNING.clear()

    threading.Thread(target=_run, daemon=True, name="romm-index").start()


def build_title_id_index_async() -> None:
    """Fire-and-forget startup trigger — request + immediately attempt execution."""
    if not romm_meta._db_path:
        return
    request_index_refresh()
    maybe_run_index()
