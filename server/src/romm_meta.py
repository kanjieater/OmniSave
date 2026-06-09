"""
RomM metadata fetcher — resolves rom_id → name + icon_url and caches in SQLite.

Called at startup to warm the cache for all mapped titles, and on-demand when
a new title→rom mapping is added via the UI.

Auth header: Authorization: Bearer <ROMM_API_KEY>  (NOT X-Api-Key)
"""

import http.client
import json
import logging
import os
import pathlib
import random
import ssl
import threading
import time
import urllib.parse
import urllib.request

import database

log = logging.getLogger(__name__)

ROMM_HOST = os.environ.get("ROMM_HOST", "").rstrip("/")
ROMM_API_KEY = os.environ.get("ROMM_API_KEY", "")

_db_path: pathlib.Path | None = None
_in_flight: set[str] = set()
_in_flight_lock = threading.Lock()
_request_local = threading.local()


def set_request_creds(host: str, api_key: str) -> None:
    """Bind per-request RomM credentials to the current thread (request handlers only)."""
    _request_local.host = host.rstrip("/")
    _request_local.api_key = api_key


def _effective_host() -> str:
    return getattr(_request_local, "host", None) or ROMM_HOST


def _effective_key() -> str:
    return getattr(_request_local, "api_key", None) or ROMM_API_KEY


def init(db_path) -> None:
    global _db_path
    _db_path = pathlib.Path(db_path)


def reload_config(conn) -> None:
    """Apply server_config overrides to module globals — enables runtime toggle without restart.

    Reads romm_host, romm_api_key, romm_enabled from server_config and overwrites the
    env-var-sourced globals. Called at the start of each worker/pull cycle so the
    disable toggle takes effect immediately without a server restart.
    """
    global ROMM_HOST, ROMM_API_KEY
    enabled = database.get_config(conn, "romm_enabled")
    if enabled == "0":
        ROMM_HOST = ""
        ROMM_API_KEY = ""
        return
    host_override = database.get_config(conn, "romm_host")
    key_override = database.get_config(conn, "romm_api_key")
    if host_override:
        ROMM_HOST = host_override.rstrip("/")
    if key_override:
        ROMM_API_KEY = key_override


def load_or_create_device_id(conn) -> str:
    """Return the stored romm_device_id, generating and persisting one if absent."""
    import uuid as _uuid

    stored = database.get_config(conn, "romm_device_id")
    if stored:
        return stored
    new_id = str(_uuid.uuid4())
    database.set_config(conn, "romm_device_id", new_id)
    log.info("romm: generated device_id=%s", new_id)
    return new_id


_SWITCH_PLATFORM_ID = 21  # Nintendo Switch platform_id in RomM


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {_effective_key()}",
        "User-Agent": "OmniSave/1.0",
    }


def _abs_url(path: str | None) -> str | None:
    """Prepend effective host if path is relative (starts with '/')."""
    if not path:
        return None
    if path.startswith("/"):
        return f"{_effective_host()}{path}"
    return path


def fetch_rom_metadata(rom_id: int) -> dict | None:
    """Fetch name + icon_url for a single rom_id from RomM. Returns None on failure."""
    if not _effective_host() or not _effective_key():
        return None
    try:
        req = urllib.request.Request(
            f"{_effective_host()}/api/roms/{rom_id}",
            headers=_auth_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        name = data.get("name") or data.get("fs_name_no_tags") or data.get("fs_name")
        raw_icon = (
            data.get("url_cover")
            or data.get("path_cover_large")
            or None
            or data.get("path_cover_small")
            or None
        )
        icon_url = _abs_url(raw_icon)
        return {"rom_id": rom_id, "name": name, "icon_url": icon_url}
    except Exception as exc:
        log.warning("romm_meta: fetch failed for rom_id=%d: %s", rom_id, exc)
        return None


def search_roms(query: str, limit: int = 10) -> list:
    """Search RomM for Switch ROMs matching query. Returns [{id, name, icon_url}]."""
    if not _effective_host() or not _effective_key():
        return []
    try:
        import urllib.parse

        qs = urllib.parse.urlencode(
            {"platform_id": _SWITCH_PLATFORM_ID, "search_term": query, "limit": limit}
        )
        req = urllib.request.Request(
            f"{_effective_host()}/api/roms?{qs}",
            headers=_auth_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return [
            {
                "id": r["id"],
                "name": r.get("name") or r.get("fs_name_no_tags") or r.get("fs_name", ""),
                "icon_url": _abs_url(
                    r.get("url_cover")
                    or r.get("path_cover_large")
                    or None
                    or r.get("path_cover_small")
                    or None
                ),
            }
            for r in data.get("items", [])
        ]
    except Exception as exc:
        log.warning("romm_meta: search failed for %r: %s", query, exc)
        return []


def fetch_and_cache(rom_id: int, conn, username: str) -> dict | None:
    """Fetch metadata for rom_id and store in per-user DB cache. Returns cached row or None."""
    meta = fetch_rom_metadata(rom_id)
    if meta:
        database.upsert_romm_game_cache(conn, username, rom_id, meta["name"], meta["icon_url"])
    return meta


def warm_cache(conn, username: str) -> None:
    """Background: fetch metadata for every title in this user's romm_title_map not yet cached.

    Invariant: strictly per-username execution context. Must never access or mutate any
    global RomM cache structure. Credentials are captured at call time so the background
    thread has explicit per-user creds — thread-locals are NOT inherited by spawned threads.
    """
    # Capture caller-thread creds NOW, before the new thread starts.
    host = _effective_host()
    api_key = _effective_key()

    def _run():
        # Establish per-user creds explicitly in this thread.
        set_request_creds(host, api_key)
        title_map = database.get_romm_title_map(conn, username)
        if not title_map:
            return
        for entry in title_map:
            title_id = entry["title_id"]
            rom_id = entry["rom_id"]
            cached = database.get_romm_game_cache(conn, username, rom_id)
            if cached and cached.get("name"):
                log.debug("romm_meta: cache hit for rom_id=%d (%s)", rom_id, title_id)
                continue
            meta = fetch_rom_metadata(rom_id)
            if meta:
                database.upsert_romm_game_cache(
                    conn, username, rom_id, meta["name"], meta["icon_url"]
                )
                log.info(
                    "romm_meta: cached rom_id=%d → %r for title %s", rom_id, meta["name"], title_id
                )
            time.sleep(random.uniform(0.2, 0.8))

    threading.Thread(target=_run, daemon=True, name="romm-meta-warm").start()


def warm_cache_all(conn) -> None:
    """Startup warm: iterate all RomM-enabled users and warm each user's cache."""
    for username in database.get_romm_users(conn):
        host = database.get_user_config(conn, username, "romm_host") or ROMM_HOST
        key = database.get_user_config(conn, username, "romm_api_key") or ROMM_API_KEY
        if host and key:
            set_request_creds(host, key)
            warm_cache(conn, username)


def resolve_name(title_id: str, conn, username: str) -> str | None:
    """Return RomM name for title_id if mapped and cached for this user, else None."""
    rom_id = database.get_romm_rom_id(conn, username, title_id)
    if rom_id is None:
        return None
    cached = database.get_romm_game_cache(conn, username, rom_id)
    if cached:
        return cached.get("name")
    meta = fetch_and_cache(rom_id, conn, username)
    return meta["name"] if meta else None


def resolve_icon(title_id: str, conn, username: str) -> str | None:
    """Return RomM icon_url for title_id if mapped and cached for this user, else None."""
    rom_id = database.get_romm_rom_id(conn, username, title_id)
    if rom_id is None:
        return None
    cached = database.get_romm_game_cache(conn, username, rom_id)
    if cached:
        return cached.get("icon_url")
    meta = fetch_and_cache(rom_id, conn, username)
    return meta["icon_url"] if meta else None


def list_saves_for_rom(rom_id: int, device_id: str) -> list:
    """GET /saves?rom_id=&device_id= — returns only saves tagged to this device_id."""
    if not _effective_host() or not _effective_key():
        return []
    try:
        import urllib.parse

        qs = urllib.parse.urlencode({"rom_id": rom_id, "device_id": device_id})
        req = urllib.request.Request(f"{_effective_host()}/api/saves?{qs}", headers=_auth_headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("romm_meta: list_saves failed rom_id=%d: %s", rom_id, exc)
        return []


def fetch_current_user() -> dict | None:
    """Fetch the RomM username for the configured API key. Tries known endpoint variants."""
    if not _effective_host() or not _effective_key():
        return None
    for path in ("/api/users/me", "/api/me", "/api/auth/me"):
        try:
            req = urllib.request.Request(
                f"{_effective_host()}{path}",
                headers=_auth_headers(),
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode())
            username = data.get("username") or data.get("name") or data.get("login")
            if username:
                return {"id": data.get("id"), "username": username}
        except Exception as exc:
            log.debug("romm_meta: fetch_current_user %s failed: %s", path, exc)
    return None


def refresh_username_cache(conn, username: str) -> None:
    """Fetch the RomM username for the user's API key and store in user_config."""
    user = fetch_current_user()
    database.set_user_config(conn, username, "romm_username", user["username"] if user else "")
    log.info(
        "romm_meta: cached romm_username=%r for user=%s",
        user["username"] if user else None,
        username,
    )


def list_all_saves_for_rom(rom_id: int) -> list:
    """GET /api/saves?rom_id= — all saves regardless of originating device.

    Used by the pull loop so saves from Argosy, muOS, web player, etc. are all
    captured. Dedup is handled by romm_save_sync, not by filtering here.
    Never use the negotiate protocol (/api/sync/negotiate) — OmniSave owns conflict resolution.
    """
    if not _effective_host() or not _effective_key():
        return []
    try:
        import urllib.parse

        qs = urllib.parse.urlencode({"rom_id": rom_id})
        req = urllib.request.Request(f"{_effective_host()}/api/saves?{qs}", headers=_auth_headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("romm_meta: list_all_saves failed rom_id=%d: %s", rom_id, exc)
        return []


def download_save_content(save_id: int) -> bytes | None:
    """GET /saves/{id}/content — returns raw binary or None on failure."""
    if not _effective_host() or not _effective_key():
        return None
    try:
        req = urllib.request.Request(
            f"{_effective_host()}/api/saves/{save_id}/content", headers=_auth_headers()
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception as exc:
        log.warning("romm_meta: download_save failed save_id=%d: %s", save_id, exc)
        return None


def upload_save(
    rom_id: int,
    snapshot_path: pathlib.Path,
    device_id: str = "",
    filename: str = "omnisave-latest.zip",
    autocleanup_limit: int = 10,
) -> tuple[dict | None, str | None]:
    """POST /api/saves — multipart streaming upload. Returns (save_dict, None) or (None, error_str)."""
    if not _effective_host() or not _effective_key():
        return None, "romm not configured"
    try:
        boundary = "omnisave-boundary"
        part_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="saveFile"; filename="{filename}"\r\n'
            f"Content-Type: application/zip\r\n\r\n"
        ).encode()
        part_footer = f"\r\n--{boundary}--\r\n".encode()

        file_size = snapshot_path.stat().st_size
        content_length = len(part_header) + file_size + len(part_footer)

        parsed = urllib.parse.urlparse(_effective_host())
        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        req_path = (
            f"/api/saves"
            f"?rom_id={rom_id}"
            f"&slot=autosave"
            f"&autocleanup=true"
            f"&autocleanup_limit={autocleanup_limit}"
        )
        # 1 second per 512KB, floor 2 min — conservative for slow uplinks
        timeout = max(120, file_size // (512 * 1024))

        if scheme == "https":
            conn = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)

        t0 = time.monotonic()
        try:
            conn.putrequest("POST", req_path)
            for k, v in {
                **_auth_headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(content_length),
            }.items():
                conn.putheader(k, v)
            conn.endheaders()
            conn.send(part_header)
            with snapshot_path.open("rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    conn.send(chunk)
            conn.send(part_footer)
            resp = conn.getresponse()
            resp_body = resp.read().decode()
        finally:
            conn.close()

        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status not in (200, 201):
            err = f"HTTP {resp.status}: {resp_body[:500]}"
            log.warning("romm_meta: upload_save HTTP error rom_id=%d: %s", rom_id, err)
            return None, err
        log.debug(
            "romm_meta: upload_save ok rom_id=%d status=%d latency=%dms",
            rom_id,
            resp.status,
            latency_ms,
        )
        return json.loads(resp_body), None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.warning("romm_meta: upload_save failed rom_id=%d: %s", rom_id, err)
        return None, err


def clear_last_played(rom_id: int) -> None:
    """PUT /api/roms/{id}/props?remove_last_played=true — prevent OmniSave uploads from
    polluting RomM's play-history. Never raises."""
    if not _effective_host() or not _effective_key():
        return
    try:
        req = urllib.request.Request(
            f"{_effective_host()}/api/roms/{rom_id}/props?remove_last_played=true",
            method="PUT",
            headers={**_auth_headers(), "Content-Length": "0"},
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        log.debug("romm_meta: clear_last_played ok rom_id=%d", rom_id)
    except Exception as exc:
        log.debug("romm_meta: clear_last_played failed rom_id=%d: %s", rom_id, exc)


def ping(host: str = "") -> bool:
    """Health signal: GET /api/heartbeat (unauthenticated). True on HTTP 200. Never raises."""
    effective = (host or _effective_host()).rstrip("/")
    if not effective:
        return False
    try:
        req = urllib.request.Request(
            f"{effective}/api/heartbeat",
            headers={"User-Agent": "OmniSave/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def try_auto_match(title_id: str, username: str) -> None:
    """Auto-map title_id to a RomM ROM for one user. Never raises. Opens its own DB connection."""
    if not _effective_host() or not _effective_key() or not _db_path:
        return
    try:
        import titledb as tdb

        conn = database.open_db(_db_path)
        try:
            if database.get_romm_rom_id(conn, username, title_id) is not None:
                return
            name = tdb.resolve_game_name(title_id)
            if not name:
                log.debug("romm_meta: auto-match skipped title=%s (no titledb name)", title_id)
                import romm_index as _ri

                _ri.request_index_refresh()
                return
            results = search_roms(name, limit=5)
            if len(results) != 1:
                log.debug(
                    "romm_meta: auto-match skipped title=%s name=%r results=%d",
                    title_id,
                    name,
                    len(results),
                )
                import romm_index as _ri

                _ri.request_index_refresh()
                return
            rom = results[0]
            database.upsert_romm_title_map(conn, username, title_id, rom["id"])
            database.upsert_romm_game_cache(conn, username, rom["id"], rom["name"], rom["icon_url"])
            log.info(
                "romm_meta: auto-matched title=%s → rom_id=%d name=%r user=%s",
                title_id,
                rom["id"],
                rom["name"],
                username,
            )
        finally:
            conn.close()
        import romm_vsc

        romm_vsc.push_head_async(title_id)
    except Exception as exc:
        log.warning("romm_meta: auto-match error for title=%s user=%s: %s", title_id, username, exc)


def try_auto_match_async(title_id: str, username: str | None = None) -> None:
    """Fire-and-forget daemon thread. If username is None, runs for all RomM-enabled users."""
    if not _db_path:
        return
    if username is None:
        # Called from processing pipeline without user context — match for all enabled users.
        conn = database.open_db(_db_path)
        try:
            users = database.get_romm_users(conn)
        finally:
            conn.close()
        for u in users:
            try_auto_match_async(title_id, u)
        return
    key = f"{username}:{title_id}"
    with _in_flight_lock:
        if key in _in_flight:
            return
        _in_flight.add(key)

    def _run():
        try:
            try_auto_match(title_id, username)
        finally:
            with _in_flight_lock:
                _in_flight.discard(key)

    threading.Thread(target=_run, daemon=True, name=f"romm-automatch-{title_id[:8]}").start()


def auto_match_in_flight(username: str, title_id: str) -> bool:
    with _in_flight_lock:
        return f"{username}:{title_id}" in _in_flight
