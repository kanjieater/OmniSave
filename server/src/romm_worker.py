"""Consume READY_FOR_RESTORE outbound transactions for the RomM virtual device.

Pushes saves to RomM via POST /api/saves (direct CRUD — no negotiate protocol).
OmniSave is the sync authority; RomM is a transport endpoint.

Loop-prevention invariant (see romm_vsc.py docstring):
    Both romm_save_sync markers (outbound + inbound loop guard) are written
    atomically in a single commit before complete_outbound() is called.
    A crash between marker writes is detected and healed on the next run_once() call.
"""

import logging
import pathlib
import threading
import time

import database as db
import romm_index
import romm_meta
import romm_vsc

log = logging.getLogger(__name__)

_catalog_last_seen: dict[str, frozenset] = {}  # username → last known Switch ROM ID set
_catalog_check_ts: dict[str, float] = {}  # username → last reconcile timestamp
_CATALOG_RECONCILE_INTERVAL = 300  # safety backstop default: 5 min


def _reconcile_romm_catalog_backstop(conn, username: str) -> None:
    """Safety backstop: detect RomM catalog drift and trigger re-indexing.

    NOT the primary ingestion path — that is romm_index. Only fires
    request_index_refresh(); never mutates romm_title_map directly.
    Throttled to _CATALOG_RECONCILE_INTERVAL seconds per user.
    Snapshot diff detects both additions and deletions."""
    now = time.time()
    if now - _catalog_check_ts.get(username, 0) < _CATALOG_RECONCILE_INTERVAL:
        return
    _catalog_check_ts[username] = now
    try:
        current_ids = frozenset(r["id"] for r in romm_index._fetch_switch_roms())
        last_seen = _catalog_last_seen.get(username)
        if last_seen is None:
            _catalog_last_seen[username] = current_ids  # seed snapshot, no refresh
            return
        if current_ids != last_seen:
            added = len(current_ids - last_seen)
            removed = len(last_seen - current_ids)
            log.info(
                "romm catalog drift detected user=%s (+%d/-%d ROMs) — queuing index refresh",
                username,
                added,
                removed,
            )
            _catalog_last_seen[username] = current_ids
            romm_index.request_index_refresh()
        else:
            _catalog_last_seen[username] = current_ids
    except Exception as exc:
        log.debug("romm catalog backstop failed user=%s: %s", username, exc)


def run_once(conn) -> None:
    """Process pending RomM outbound transactions for all enabled users. Best-effort; never raises."""
    for username in db.get_romm_users(conn):
        _run_once_for_user(conn, username)


def _run_once_for_user(conn, username: str) -> None:
    if not romm_vsc._load_user_creds(conn, username):
        return
    device_id = romm_vsc.get_user_romm_device_id(conn, username)
    _reconcile_romm_catalog_backstop(conn, username)

    # Keep device_installed_games in sync with romm_title_map each cycle.
    # No open transaction here — sync_romm_catalog_to_device uses BEGIN IMMEDIATE safely.
    before = conn.execute(
        "SELECT COUNT(*) FROM device_installed_games WHERE device_id=?", (device_id,)
    ).fetchone()[0]
    db.sync_romm_catalog_to_device(conn, username, device_id)
    after = conn.execute(
        "SELECT COUNT(*) FROM device_installed_games WHERE device_id=?", (device_id,)
    ).fetchone()[0]
    if before != after:
        log.info("romm catalog sync user=%s rows=%d→%d", username, before, after)

    romm_uuid = db.get_user_config(conn, username, "romm_device_id") or ""
    host = db.get_user_config(conn, username, "romm_host") or romm_meta.ROMM_HOST
    romm_contacted = False
    pending = db.get_pending_outbound(conn, device_id)
    for row in pending:
        txn_id = row["transaction_id"]
        title_id = row["title_id"]

        txn = db.get_transaction(conn, txn_id)
        if not txn or not txn["snapshot_path"]:
            log.warning("romm_worker: no archive for txn=%s — skipping", txn_id[:8])
            continue
        txn_owner = txn.get("owner_user_id")
        if txn_owner and txn_owner != username:
            log.error(
                "romm_worker: SECURITY owner mismatch txn=%s owner=%s expected=%s — failing outbound",
                txn_id[:8],
                txn_owner,
                username,
            )
            db.fail_outbound(conn, device_id, txn_id)
            conn.commit()
            continue
        snapshot_path = pathlib.Path(txn["snapshot_path"])
        if not snapshot_path.exists():
            log.warning("romm_worker: archive missing on disk txn=%s — skipping", txn_id[:8])
            continue

        rom_id = db.get_romm_rom_id(conn, username, title_id)
        if rom_id is None:
            if romm_meta.auto_match_in_flight(username, title_id):
                log.debug(
                    "romm_worker: auto-match in flight title=%s — deferring outbound", title_id
                )
                continue
            db.fail_outbound(conn, device_id, txn_id)
            conn.commit()
            log.warning(
                "romm_worker: failing outbound for unmapped title=%s txn=%s", title_id, txn_id[:8]
            )
            continue

        existing = conn.execute(
            "SELECT romm_save_id FROM romm_save_sync"
            " WHERE username=? AND direction='outbound' AND transaction_id=?",
            (username, txn_id),
        ).fetchone()
        if existing:
            romm_save_id = existing["romm_save_id"]
            romm_vsc.stamp_device_head(
                conn,
                title_id=title_id,
                username=username,
                snapshot_sequence=txn["snapshot_sequence"],
            )
            romm_vsc.record_romm_delivery(
                conn,
                username=username,
                rom_id=rom_id,
                romm_save_id=romm_save_id,
                transaction_id=txn_id,
            )
            db.complete_outbound(conn, device_id, txn_id)
            conn.execute(
                "UPDATE sync_transactions SET state='SUPERSEDED', updated_at=?"
                " WHERE title_id=? AND target_device_id=? AND direction='outbound'"
                " AND state='FAILED' AND transaction_id != ?",
                (db._now(), row["title_id"], device_id, txn_id),
            )
            conn.commit()
            log.info(
                "romm_worker: healed crash-incomplete txn=%s save_id=%d", txn_id[:8], romm_save_id
            )
            continue

        filename = romm_vsc._romm_filename(title_id, conn, username, rom_id)
        result, err_str = romm_meta.upload_save(rom_id, snapshot_path, romm_uuid, filename=filename)
        if result is None:
            size_mb = snapshot_path.stat().st_size / 1024 / 1024
            log.warning(
                "romm_worker: upload failed txn=%s size=%.1fMB — will retry next cycle: %s",
                txn_id[:8],
                size_mb,
                err_str,
            )
            db.log_event(
                conn,
                "ROMM_PUSH_FAILED",
                f"title={title_id} txn={txn_id[:8]} size={size_mb:.1f}MB err={err_str}",
                title_id=title_id,
                transaction_id=txn_id,
                device_id=device_id,
                owner_user_id=username,
            )
            conn.commit()
            continue

        romm_contacted = True
        romm_save_id = result["id"]
        romm_vsc.stamp_device_head(
            conn, title_id=title_id, username=username, snapshot_sequence=txn["snapshot_sequence"]
        )
        romm_vsc.record_romm_delivery(
            conn, username=username, rom_id=rom_id, romm_save_id=romm_save_id, transaction_id=txn_id
        )
        db.complete_outbound(conn, device_id, txn_id)
        conn.execute(
            "UPDATE sync_transactions SET state='SUPERSEDED', updated_at=?"
            " WHERE title_id=? AND target_device_id=? AND direction='outbound'"
            " AND state='FAILED' AND transaction_id != ?",
            (db._now(), title_id, device_id, txn_id),
        )
        conn.commit()
        db.log_event(
            conn,
            "ROMM_PUSH",
            f"title={title_id} romm_save_id={romm_save_id}",
            title_id=title_id,
            transaction_id=txn_id,
            device_id=device_id,
            owner_user_id=username,
        )
        log.info(
            "romm_worker: pushed txn=%s title=%s → romm_save_id=%d user=%s",
            txn_id[:8],
            title_id,
            romm_save_id,
            username,
        )

    n = db.supersede_failed_outbounds_for_uninstalled(conn)
    if n:
        conn.commit()
        log.info(
            "romm_worker: superseded %d FAILED outbound(s) for uninstalled titles user=%s",
            n,
            username,
        )
    _reconcile_undelivered(conn, username, device_id)

    # Fallback: if no real work this cycle, probe reachability.
    # Worker (60s) drives heartbeat; pull loop runs at 900s so can't rely on it.
    if not romm_contacted:
        romm_contacted = romm_meta.ping(host)

    if romm_contacted:
        db.touch_device(conn, device_id, username)


def _reconcile_undelivered(conn, username: str, device_id: str) -> None:
    """Queue outbounds for titles where HEAD exists but all delivery attempts failed."""
    rows = db.get_romm_undelivered_head_txns(conn, username, device_id)
    for row in rows:
        new_id = db.create_outbound_transaction(conn, row["transaction_id"], device_id)
        if new_id:
            conn.commit()
            log.info(
                "romm_worker: reconcile queued txn=%s title=%s seq=%d user=%s",
                new_id[:8],
                row["title_id"],
                row["snapshot_sequence"],
                username,
            )


_REINDEX_EVERY_CYCLES = 360  # 360 × 60s = 6 hours


def start_worker_loop(interval_sec: int = 60) -> None:
    """Start a daemon thread that calls run_once every interval_sec seconds."""
    cycle = 0

    def _loop():
        nonlocal cycle
        while True:
            time.sleep(interval_sec)
            cycle += 1
            try:
                if not romm_meta._db_path:
                    continue
                conn = db.open_db(romm_meta._db_path)
                try:
                    run_once(conn)
                finally:
                    conn.close()
                if cycle % _REINDEX_EVERY_CYCLES == 0:
                    romm_index.request_index_refresh()
                romm_index.maybe_run_index()
            except Exception as exc:
                log.warning("romm_worker: loop error: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="romm-worker").start()
    log.info(
        "romm_worker: started (interval=%ds reindex_every=%dh)",
        interval_sec,
        interval_sec * _REINDEX_EVERY_CYCLES // 3600,
    )
