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
import urllib.error
import urllib.parse
import urllib.request

import database as db
import romm_meta

log = logging.getLogger(__name__)

_TITLE_ID_FILE_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
_SWITCH_PLATFORM_ID = 21


def _fetch_switch_roms() -> list[dict]:
    """Paginate /api/roms, return full item dicts for all ROMs.

    The list response already contains fs_name, fs_name_no_tags, url_cover, etc.
    Callers should try _base_title_id() on each item before falling back to
    _fetch_rom_detail() — this avoids one HTTP call per ROM for the common case
    where the primary filename includes a bracketed title ID.
    """
    roms: list[dict] = []
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
            roms.append(r)
        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
    return roms


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


def _fetch_detail_with_creds(rom_id: int, host: str, api_key: str) -> tuple[dict | None, int]:
    """Fetch ROM detail with explicit per-thread credentials (safe for ThreadPoolExecutor)."""
    romm_meta.set_request_creds(host, api_key)
    t0 = time.monotonic()
    detail = _fetch_rom_detail(rom_id)
    return detail, int((time.monotonic() - t0) * 1000)


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
    global _last_scan_error, _last_scan_ts

    romm_meta.set_request_creds(host, api_key)
    scan_started = time.monotonic()
    try:
        unmapped_count = conn.execute(
            "SELECT COUNT(DISTINCT title_id) FROM ("
            "  SELECT title_id FROM sync_transactions"
            "  UNION"
            "  SELECT title_id FROM device_installed_games"
            ") WHERE title_id NOT IN"
            " (SELECT title_id FROM romm_title_map WHERE username=?)",
            (username,),
        ).fetchone()[0]
        log.info("romm_index: scanning RomM (unmapped=%d) user=%s", unmapped_count, username)
        already_mapped_rom_ids: set[int] = {
            r["rom_id"]
            for r in conn.execute(
                "SELECT rom_id FROM romm_title_map WHERE username=?", (username,)
            ).fetchall()
        }

        # ── Stale cleanup — remove mappings for ROMs deleted from RomM ─────────
        list_t0 = time.monotonic()
        roms = _fetch_switch_roms()
        list_ms = int((time.monotonic() - list_t0) * 1000)
        log.info(
            "romm_index: list fetch done roms=%d list_ms=%d user=%s",
            len(roms), list_ms, username,
        )
        rom_ids_set = {r["id"] for r in roms}
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

        # ── File scan — match via [TITLEID] in RomM filenames only ───────────
        # Phase 0 (no HTTP): extract title_id from list-response fields directly.
        # Phase 1 (parallel): batch-fetch details for the rest; skip if still no bracket ID.
        mapped_count = 0
        detail_calls = 0
        detail_ms_total = 0
        matched_from_file = 0
        needs_detail: dict[int, dict] = {}  # rom_id → list-response item

        for rom in roms:
            rom_id = rom["id"]
            if rom_id in already_mapped_rom_ids:
                continue
            title_id = _base_title_id(rom)
            if title_id:
                name = rom.get("name") or rom.get("fs_name_no_tags") or rom.get("fs_name")
                raw_icon = (
                    rom.get("url_cover") or rom.get("path_cover_large") or rom.get("path_cover_small")
                )
                icon_url = romm_meta._abs_url(raw_icon)
                db.upsert_romm_title_map(conn, username, title_id, rom_id)
                db.upsert_romm_game_cache(conn, username, rom_id, name, icon_url)
                log.info(
                    "romm_index: file-matched title=%s → rom_id=%d name=%r user=%s",
                    title_id, rom_id, name, username,
                )
                already_mapped_rom_ids.add(rom_id)
                mapped_count += 1
                matched_from_file += 1
            else:
                needs_detail[rom_id] = rom

        # Phase 1: parallel detail fetch; skip ROM if still no bracket title ID.
        if needs_detail:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(_fetch_detail_with_creds, rom_id, host, api_key): rom_id
                    for rom_id in needs_detail
                }
                for future in as_completed(futures):
                    rom_id = futures[future]
                    rom = needs_detail[rom_id]
                    detail, elapsed = future.result()
                    detail_calls += 1
                    detail_ms_total += elapsed
                    if detail is None:
                        continue
                    title_id = _base_title_id(detail)
                    if not title_id:
                        continue  # no bracket ID in filename or files[] — skip
                    name = (
                        detail.get("name") or detail.get("fs_name_no_tags") or detail.get("fs_name")
                        or rom.get("name") or rom.get("fs_name_no_tags") or rom.get("fs_name")
                    )
                    raw_icon = (
                        detail.get("url_cover")
                        or detail.get("path_cover_large")
                        or detail.get("path_cover_small")
                    )
                    icon_url = romm_meta._abs_url(raw_icon)
                    db.upsert_romm_title_map(conn, username, title_id, rom_id)
                    db.upsert_romm_game_cache(conn, username, rom_id, name, icon_url)
                    log.info(
                        "romm_index: file-matched title=%s → rom_id=%d name=%r user=%s",
                        title_id, rom_id, name, username,
                    )
                    already_mapped_rom_ids.add(rom_id)
                    mapped_count += 1
                    matched_from_file += 1

        log.info(
            "romm_index: scan done user=%s roms=%d detail_calls=%d detail_ms=%d "
            "matched_file=%d mapped=%d elapsed_ms=%d",
            username,
            len(roms),
            detail_calls,
            detail_ms_total,
            matched_from_file,
            mapped_count,
            int((time.monotonic() - scan_started) * 1000),
        )
        _last_scan_error = None
        _last_scan_ts = time.time()
    except Exception as exc:
        _last_scan_error = str(exc)
        _last_scan_ts = time.time()
        log.warning("romm_index: error user=%s: %s", username, exc)
        if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
            log.warning("romm_index: auth error (HTTP %d) — not retrying user=%s", exc.code, username)
            try:
                db.set_user_config(conn, username, "romm_connect_status", "auth_failed")
                db.set_user_config(conn, username, "romm_connect_detail", f"HTTP {exc.code} — check RomM API key")
                conn.commit()
            except Exception:
                pass
        else:
            request_index_refresh()


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
_last_scan_error: str | None = None
_last_scan_ts: float = 0.0


def scan_status() -> dict:
    """Return current scan state for UI status display."""
    return {
        "running": _INDEX_RUNNING.is_set(),
        "queued": _REFRESH_REQUESTED.is_set(),
        "last_error": _last_scan_error,
        "last_scan_ts": _last_scan_ts or None,
    }


def request_index_refresh() -> None:
    """Signal that a title-ID lookup missed. Worker will execute on next cycle."""
    _REFRESH_REQUESTED.set()


def request_index_run_now() -> None:
    """Request a refresh and start the background scan immediately if none is running.

    Non-blocking: returns instantly. The scan runs in a daemon thread.
    Coalescing: if a scan is already in flight, the flag stays set so the
    worker picks it up on the next cycle after the current scan finishes.
    Safe to call from any HTTP request handler.
    """
    request_index_refresh()
    maybe_run_index()


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
        global _last_scan_error
        _INDEX_RUNNING.set()
        _last_scan_error = None  # clear stale error so UI banner drops immediately on retry
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
