"""RomM Virtual Sync Client — bidirectional save exchange between OmniSave and RomM.

Architecture invariants
-----------------------
* Switches never know RomM exists. All data flows through OmniSave's transaction
  pipeline; RomM is a transport endpoint, not a sync authority.
* OmniSave NEVER uses RomM's /api/sync/negotiate protocol — that would delegate
  conflict authority to RomM. Only the save CRUD API is used:
      POST /api/saves, GET /api/saves?rom_id=, GET /api/saves/{id}/content

Loop-prevention invariant
-------------------------
Every successful RomM upload MUST atomically write BOTH:
    romm_save_sync(direction='outbound', transaction_id=txn)
    romm_save_sync(direction='inbound',  transaction_id=NULL)   ← loop guard
in a single commit before calling complete_outbound().
Without the inbound record the pull cycle will re-import the same save,
creating the OmniSave → RomM → OmniSave → … loop.
"""

import logging
import pathlib
import re
import threading
import time

import database as db
import romm_meta
import titledb

log = logging.getLogger(__name__)


# ── Device ID ─────────────────────────────────────────────────────────────────


def get_user_romm_device_id(conn, username: str) -> str:
    """Return the stable virtual device_id for this user's RomM VSC."""
    return db.get_user_config(conn, username, "romm_source_id") or f"romm:{username}"


# ── Per-user credential loader ─────────────────────────────────────────────────


def _load_user_creds(conn, username: str) -> bool:
    """Set thread-local RomM creds for username. Returns False if not configured/enabled."""
    if db.get_user_config(conn, username, "romm_enabled") == "0":
        return False
    host = db.get_user_config(conn, username, "romm_host") or ""
    key = db.get_user_config(conn, username, "romm_api_key") or ""
    if not host or not key:
        return False
    romm_meta.set_request_creds(host, key)
    return True


# ── Push (OmniSave → RomM) ────────────────────────────────────────────────────

_UNSAFE_FILENAME_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def _romm_filename(title_id: str, conn, username: str = "", rom_id: int | None = None) -> str:
    if rom_id is not None and username:
        cached = db.get_romm_game_cache(conn, username, rom_id)
        if not (cached and cached.get("name")):
            meta = romm_meta.fetch_rom_metadata(rom_id)
            if meta and meta.get("name"):
                db.upsert_romm_game_cache(
                    conn, username, rom_id, meta["name"], meta.get("icon_url")
                )
                cached = {"name": meta["name"]}
        if cached and cached.get("name"):
            safe = _UNSAFE_FILENAME_RE.sub("", cached["name"]).strip()[:120]
            if safe:
                return f"{safe}.zip"
    # No RomM mapping — use official titledb name only, never the user's display label
    name = titledb.resolve_game_name(title_id)
    if not name:
        return "omnisave-latest.zip"
    safe = _UNSAFE_FILENAME_RE.sub("", name).strip()[:120]
    return f"{safe}.zip" if safe else "omnisave-latest.zip"


def stamp_device_head(conn, *, title_id: str, username: str, snapshot_sequence: int) -> None:
    """Stamp device_title_head for this user's RomM VSC device.

    Required after every successful RomM delivery. Monotonic — never regresses.
    """
    db.upsert_device_title_head(
        conn, title_id, get_user_romm_device_id(conn, username), snapshot_sequence
    )


def record_romm_delivery(
    conn, *, username: str, rom_id: int, romm_save_id: int, transaction_id: "str | None"
) -> None:
    """Write romm_save_sync outbound record + inbound loop guard.

    Required after every successful RomM delivery. Idempotent — INSERT OR IGNORE.
    transaction_id is the inbound txn for push() path, outbound txn for worker path.
    """
    db.record_romm_sync(conn, username, rom_id, romm_save_id, "outbound", transaction_id)
    db.record_romm_sync(conn, username, rom_id, romm_save_id, "inbound", None)


def push(title_id: str, transaction_id: str, archive_path: str, username: str) -> None:
    """Upload save.zip for title_id to the given user's RomM. Best-effort; never raises."""
    if not romm_meta._db_path:
        return
    try:
        conn = db.open_db(romm_meta._db_path)
        try:
            if not _load_user_creds(conn, username):
                return
            rom_id = db.get_romm_rom_id(conn, username, title_id)
            if rom_id is None:
                return
            existing = conn.execute(
                "SELECT 1 FROM romm_save_sync WHERE username=? AND direction='outbound' AND transaction_id=?",
                (username, transaction_id),
            ).fetchone()
            if existing:
                return
            device_id = db.get_user_config(conn, username, "romm_device_id") or ""
            filename = _romm_filename(title_id, conn, username, rom_id)
            result, _ = romm_meta.upload_save(
                rom_id, pathlib.Path(archive_path), device_id, filename=filename
            )
            if result is None:
                return
            romm_save_id = result["id"]
            seq_row = conn.execute(
                "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
                (transaction_id,),
            ).fetchone()
            stamp_device_head(
                conn,
                title_id=title_id,
                username=username,
                snapshot_sequence=seq_row["snapshot_sequence"],
            )
            record_romm_delivery(
                conn,
                username=username,
                rom_id=rom_id,
                romm_save_id=romm_save_id,
                transaction_id=transaction_id,
            )
            conn.commit()
            log.info(
                "romm_vsc: pushed title=%s txn=%s → romm_save_id=%d user=%s",
                title_id,
                transaction_id[:8],
                romm_save_id,
                username,
            )
        finally:
            conn.close()
    except Exception as exc:
        log.warning("romm_vsc: push error title=%s user=%s: %s", title_id, username, exc)


def push_async(title_id: str, transaction_id: str, archive_path: str, username: str) -> None:
    threading.Thread(
        target=push,
        args=(title_id, transaction_id, archive_path, username),
        daemon=True,
        name=f"romm-push-{transaction_id[:8]}",
    ).start()


# ── Pull (RomM → OmniSave) ────────────────────────────────────────────────────


def _pull_for_user(staging_dir, archive_dir, username: str) -> None:
    """Ingest new RomM saves for a single user. Best-effort; never raises."""
    try:
        import processing

        conn = db.open_db(romm_meta._db_path)
        try:
            if not _load_user_creds(conn, username):
                return
            source_device_id = get_user_romm_device_id(conn, username)
            title_map = db.get_romm_title_map(conn, username)
            for entry in title_map:
                title_id = entry["title_id"]
                rom_id = entry["rom_id"]
                saves = romm_meta.list_all_saves_for_rom(rom_id)
                for save in saves:
                    save_id = save["id"]
                    ext = (save.get("file_extension") or "").lower()
                    fname = (save.get("file_name") or "").lower()
                    if ext != "zip" and not fname.endswith(".zip"):
                        log.debug("romm_vsc: skip non-zip save_id=%d title=%s", save_id, title_id)
                        continue
                    if db.has_romm_sync(conn, username, rom_id, save_id, "inbound"):
                        continue
                    content = romm_meta.download_save_content(save_id)
                    if content is None:
                        continue
                    txn_id = processing.ingest_direct(
                        title_id,
                        source_device_id,
                        content,
                        staging_dir,
                        archive_dir,
                        conn,
                        owner_user_id=username,
                    )
                    if txn_id:
                        db.record_romm_sync(conn, username, rom_id, save_id, "inbound", txn_id)
                        db.log_event(
                            conn,
                            "ROMM_PULL_IMPORTED",
                            f"save_id={save_id} title={title_id} txn={txn_id[:8]}",
                            title_id=title_id,
                            transaction_id=txn_id,
                        )
                        log.info(
                            "romm_vsc: ingested save_id=%d title=%s → txn=%s user=%s",
                            save_id,
                            title_id,
                            txn_id[:8],
                            username,
                        )
                    time.sleep(0.1)
        finally:
            conn.close()
    except Exception as exc:
        log.warning("romm_vsc: pull error user=%s: %s", username, exc)


def pull(staging_dir, archive_dir) -> None:
    """Poll RomM for all enabled users and ingest new saves. Best-effort; never raises."""
    if not romm_meta._db_path:
        return
    try:
        conn = db.open_db(romm_meta._db_path)
        try:
            users = db.get_romm_users(conn)
        finally:
            conn.close()
        for username in users:
            _pull_for_user(staging_dir, archive_dir, username)
    except Exception as exc:
        log.warning("romm_vsc: pull error: %s", exc)


def push_head(title_id: str, username: str) -> None:
    """Push current HEAD READY_FOR_RESTORE snapshot for title_id to one user's RomM."""
    if not romm_meta._db_path:
        return
    try:
        conn = db.open_db(romm_meta._db_path)
        try:
            row = conn.execute(
                "SELECT transaction_id, snapshot_path FROM sync_transactions"
                " WHERE title_id=? AND direction='inbound' AND state='READY_FOR_RESTORE'"
                " AND has_conflict=0 ORDER BY snapshot_sequence DESC LIMIT 1",
                (title_id.upper(),),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row["snapshot_path"]:
            return
        push(title_id, row["transaction_id"], row["snapshot_path"], username)
    except Exception as exc:
        log.warning("romm_vsc: push_head error title=%s user=%s: %s", title_id, username, exc)


def _push_head_all_users(title_id: str) -> None:
    try:
        conn = db.open_db(romm_meta._db_path)
        try:
            users = db.get_romm_users(conn)
        finally:
            conn.close()
        for username in users:
            push_head(title_id, username)
    except Exception as exc:
        log.warning("romm_vsc: push_head_all_users error title=%s: %s", title_id, exc)


def push_head_async(title_id: str) -> None:
    """Fire-and-forget: push HEAD snapshot for title_id to all enabled users' RomM."""
    if not romm_meta._db_path:
        return
    threading.Thread(
        target=_push_head_all_users,
        args=(title_id,),
        daemon=True,
        name=f"romm-push-head-{title_id[:8]}",
    ).start()


def start_pull_loop(staging_dir, archive_dir, interval_sec: int = 900) -> None:
    """Start a daemon thread that pulls from all users' RomM every interval_sec seconds."""

    def _loop():
        while True:
            time.sleep(interval_sec)
            pull(staging_dir, archive_dir)

    threading.Thread(target=_loop, daemon=True, name="romm-vsc-pull").start()
