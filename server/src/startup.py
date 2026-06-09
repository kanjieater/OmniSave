"""
Crash recovery executed on every server startup.

Rules:
  1. UPLOADING/PROCESSING transactions idle > 12h → FAILED (staging dirs deleted)
  2. READY_FOR_RESTORE inbound missing archive file → FAILED
  3. Staging dirs with no corresponding upload_sessions row → delete (orphans)
  4. Outbound transactions with NULL checkpoint_ledger but extant archive → recompute
"""

import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import xxhash

import database as db
import processing

log = logging.getLogger(__name__)
UPLOAD_TIMEOUT_HOURS = 12
FAILED_RETENTION_DAYS = 7


def _migrate_schema(conn) -> None:
    migrations = [
        "ALTER TABLE events ADD COLUMN transaction_id TEXT",
        "ALTER TABLE events ADD COLUMN title_id TEXT",
        "ALTER TABLE events ADD COLUMN device_id TEXT",
        "DROP INDEX IF EXISTS uniq_active_outbound_per_device",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
            log.info("startup: applied migration: %s", sql)
        except Exception:
            pass


_CHECKPOINT_SIZE = 4 * 1024 * 1024


def _compute_ledger(path: Path) -> list[int]:
    ledger = []
    with path.open("rb") as f:
        while True:
            block = f.read(_CHECKPOINT_SIZE)
            if not block:
                break
            ledger.append(xxhash.xxh32(block).intdigest())
    return ledger


def _supersede_legacy_bin_archives(conn) -> None:
    """Supersede any READY_FOR_RESTORE transactions whose archive is a .bin file.

    These are pre-ZIP-format saves that the current client cannot unpack.
    Marking them SUPERSEDED prevents them from being delivered.
    """
    rows = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE state='READY_FOR_RESTORE' AND snapshot_path LIKE '%.bin'"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE sync_transactions SET state='SUPERSEDED',updated_at=datetime('now') "
            "WHERE transaction_id=?",
            (row["transaction_id"],),
        )
        log.info("startup: superseded legacy .bin archive %s", row["transaction_id"][:8])
    if rows:
        conn.commit()


def _repair_duplicate_sequences(conn) -> None:
    """One-time repair: reassign globally unique sequences to SUPERSEDED rows that share a
    (title_id, snapshot_sequence) with a different sha256 (pre-global-seq era data).
    Only touches SUPERSEDED rows — never READY_FOR_RESTORE (which would corrupt HEAD ordering).
    Idempotent — subsequent runs find no duplicate groups and do nothing."""
    dupes = conn.execute("""
        SELECT title_id, snapshot_sequence
        FROM sync_transactions
        WHERE direction='inbound' AND snapshot_sequence IS NOT NULL AND sha256 IS NOT NULL
          AND state='SUPERSEDED'
        GROUP BY title_id, snapshot_sequence
        HAVING COUNT(DISTINCT sha256) > 1
        ORDER BY title_id, snapshot_sequence
    """).fetchall()
    if not dupes:
        return
    n = 0
    for group in dupes:
        tid, old_seq = group["title_id"], group["snapshot_sequence"]
        extras = conn.execute(
            """
            SELECT transaction_id, source_device_id
            FROM sync_transactions
            WHERE title_id=? AND direction='inbound' AND snapshot_sequence=?
              AND sha256 IS NOT NULL AND state='SUPERSEDED'
            ORDER BY created_at ASC
            LIMIT -1 OFFSET 1
        """,
            (tid, old_seq),
        ).fetchall()
        for row in extras:
            conn.execute(
                "INSERT INTO snapshot_counters (title_id,counter) VALUES (?,1) "
                "ON CONFLICT(title_id) DO UPDATE SET counter=counter+1",
                (tid,),
            )
            new_seq = conn.execute(
                "SELECT counter FROM snapshot_counters WHERE title_id=?", (tid,)
            ).fetchone()["counter"]
            conn.execute(
                "UPDATE sync_transactions SET snapshot_sequence=? WHERE transaction_id=?",
                (new_seq, row["transaction_id"]),
            )
            conn.execute(
                """
                UPDATE sync_transactions SET snapshot_sequence=?
                WHERE direction='outbound' AND title_id=? AND snapshot_sequence=?
                  AND source_device_id=?
            """,
                (new_seq, tid, old_seq, row["source_device_id"]),
            )
            n += 1
    conn.commit()
    log.info("startup: repaired %d duplicate-sequence rows", n)


def _sync_counters_and_resequence_heads(conn) -> None:
    """Ensure snapshot_counters.counter >= MAX(snapshot_sequence) for every title.

    snapshot_sequence is immutable once written by the processing worker inside
    BEGIN IMMEDIATE after hash verification — this function must never renumber
    committed rows.

    Root cause of the seq-drift bug: a previous version of this function
    also renumbered the READY_FOR_RESTORE HEAD to MAX(all seqs)+1.  That
    logic incorrectly treated preservation uploads (which legitimately have
    higher seq numbers than the HEAD) as evidence the HEAD was stale,
    causing unconditional overwrites of committed sequences on every restart.

    Idempotent."""
    titles = conn.execute("SELECT DISTINCT title_id FROM snapshot_counters").fetchall()
    for row in titles:
        tid = row["title_id"]
        actual_max = conn.execute(
            "SELECT COALESCE(MAX(snapshot_sequence), 0) FROM sync_transactions WHERE title_id=?",
            (tid,),
        ).fetchone()[0]
        counter = conn.execute(
            "SELECT counter FROM snapshot_counters WHERE title_id=?", (tid,)
        ).fetchone()["counter"]
        if counter < actual_max:
            conn.execute(
                "UPDATE snapshot_counters SET counter=? WHERE title_id=?",
                (actual_max, tid),
            )
            log.info("startup: synced counter %s: %d → %d", tid[:16], counter, actual_max)
    conn.commit()


def _supersede_uninstalled_failed_outbounds(conn) -> None:
    """Supersede FAILED outbounds for titles the target device doesn't have installed."""
    n = db.supersede_failed_outbounds_for_uninstalled(conn)
    conn.commit()
    if n:
        log.info("startup: superseded %d FAILED outbound(s) for uninstalled titles", n)


def _recover_interrupted_processing(conn, staging_dir: Path, archive_dir: Path) -> None:
    """Re-complete PROCESSING transactions where archive is already on disk.

    Handles the atomicity gap in processing._process: shutil.move succeeds but the
    process dies before conn.commit(). On restart the transaction is stuck in PROCESSING
    with the archive already in place. Re-run _run so the DB is brought into sync.
    Must run BEFORE _expire_stale_uploads so recent crashes are recovered, not expired.
    """
    rows = conn.execute(
        "SELECT st.transaction_id, us.session_id "
        "FROM sync_transactions st "
        "JOIN upload_sessions us ON us.transaction_id = st.transaction_id "
        "WHERE st.state = 'PROCESSING'"
    ).fetchall()
    for row in rows:
        txn_id = row["transaction_id"]
        if (archive_dir / txn_id / "save.zip").exists():
            log.info("startup: recovering interrupted processing txn=%s", txn_id[:8])
            processing._run(txn_id, row["session_id"], staging_dir, archive_dir, conn.path)


def run(conn, staging_dir: Path, archive_dir: Path) -> None:
    _migrate_schema(conn)
    _supersede_legacy_bin_archives(conn)
    _repair_duplicate_sequences(conn)
    _sync_counters_and_resequence_heads(conn)
    _recover_interrupted_processing(conn, staging_dir, archive_dir)
    _expire_stale_uploads(conn, staging_dir)
    _fail_missing_archives(conn)
    _repair_null_ledgers(conn)
    _repair_romm_push_head_device_title_head(conn)
    _purge_orphan_staging_dirs(conn, staging_dir)


def _expire_stale_uploads(conn, staging_dir: Path) -> None:
    cutoff = (datetime.now(UTC) - timedelta(hours=UPLOAD_TIMEOUT_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    rows = conn.execute(
        "SELECT st.transaction_id, us.session_id "
        "FROM sync_transactions st "
        "JOIN upload_sessions us ON us.transaction_id = st.transaction_id "
        "WHERE st.state IN ('UPLOADING','PROCESSING') AND us.last_active_at < ?",
        (cutoff,),
    ).fetchall()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        conn.execute(
            "UPDATE sync_transactions SET state='FAILED',updated_at=? WHERE transaction_id=?",
            (now, row["transaction_id"]),
        )
        conn.execute(
            "UPDATE upload_sessions SET session_state='FAILED' WHERE session_id=?",
            (row["session_id"],),
        )
        session_dir = staging_dir / row["session_id"]
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
        log.info("startup: expired stale upload %s", row["transaction_id"][:8])


def _fail_missing_archives(conn) -> None:
    rows = conn.execute(
        "SELECT transaction_id, snapshot_path FROM sync_transactions "
        "WHERE direction='inbound' AND state='READY_FOR_RESTORE' AND snapshot_path IS NOT NULL"
    ).fetchall()
    for row in rows:
        if not Path(row["snapshot_path"]).exists():
            # Force-fail regardless of state — archive is gone; transaction is unrecoverable.
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "UPDATE sync_transactions SET state='FAILED', updated_at=? WHERE transaction_id=?",
                (now, row["transaction_id"]),
            )
            log.warning("startup: archive missing for %s → FAILED", row["transaction_id"][:8])


def hard_delete_old_failed(conn, archive_dir: Path) -> None:
    """Hard-delete FAILED/DEDUPED inbound transactions older than 7 days.

    PRESERVATION INVARIANT: Only FAILED and DEDUPED transactions (which never produced
    a new committed artifact) are eligible for automatic deletion.
    All transactions that reached READY_FOR_RESTORE, SUPERSEDED, or COMPLETED are
    retained permanently unless the user explicitly deletes them via the UI.
    DEDUPED rows have no archive (deleted at processing time) and snapshot_sequence=NULL.
    FAILED rows that somehow acquired a sequence are kept so the gap is visible in history.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=FAILED_RETENTION_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    rows = conn.execute(
        "SELECT transaction_id, snapshot_path FROM sync_transactions "
        "WHERE state IN ('FAILED','DEDUPED') AND direction='inbound' AND updated_at < ?"
        " AND snapshot_sequence IS NULL",
        (cutoff,),
    ).fetchall()
    for row in rows:
        if row["snapshot_path"]:
            path = Path(row["snapshot_path"])
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
        conn.execute("DELETE FROM upload_sessions WHERE transaction_id=?", (row["transaction_id"],))
        conn.execute(
            "DELETE FROM sync_transactions WHERE transaction_id=?", (row["transaction_id"],)
        )
        log.info("gc: hard-deleted failed txn %s", row["transaction_id"][:8])


def run_periodic(conn, staging_dir: Path, archive_dir: Path) -> None:
    """Periodic maintenance task (every 15 min via _gc_loop in main.py)."""
    _expire_stale_uploads(conn, staging_dir)
    hard_delete_old_failed(conn, archive_dir)
    _fail_missing_archives(conn)
    _supersede_uninstalled_failed_outbounds(conn)


def _repair_null_ledgers(conn) -> None:
    """Recompute checkpoint_ledger for outbound transactions missing it (pre-V2 uploads)."""
    rows = conn.execute(
        "SELECT transaction_id, snapshot_path FROM sync_transactions "
        "WHERE direction='outbound' AND checkpoint_ledger IS NULL AND snapshot_path IS NOT NULL"
    ).fetchall()
    for row in rows:
        path = Path(row["snapshot_path"])
        if not path.exists():
            continue
        try:
            ledger = _compute_ledger(path)
            conn.execute(
                "UPDATE sync_transactions SET checkpoint_ledger=?,updated_at=datetime('now') "
                "WHERE transaction_id=?",
                (json.dumps(ledger), row["transaction_id"]),
            )
            log.info(
                "startup: repaired ledger %s checkpoints=%d",
                row["transaction_id"][:8],
                len(ledger),
            )
        except Exception as exc:
            log.warning("startup: ledger repair failed for %s: %s", row["transaction_id"][:8], exc)


def _repair_romm_push_head_device_title_head(conn) -> int:
    """Backfill device_title_head for RomM VSC devices from historical push_head records.

    push() did not stamp device_title_head before this fix. romm_save_sync is the only
    record of those successful deliveries. Collapses to MAX(snapshot_sequence) per title
    so multiple sync records produce a single authoritative entry. INSERT OR IGNORE skips
    titles already tracked by device_title_head.

    Assumption: one RomM virtual device per user (romm_source_id or romm:{username}).
    """
    cur = conn.execute("""
        INSERT INTO device_title_head (title_id, device_id, last_seq, updated_at)
        SELECT
            t.title_id,
            COALESCE(
                (SELECT value FROM user_config
                 WHERE username=rss.username AND key='romm_source_id'),
                'romm:' || rss.username
            ),
            MAX(t.snapshot_sequence),
            MAX(rss.synced_at)
        FROM romm_save_sync rss
        JOIN sync_transactions t ON t.transaction_id=rss.transaction_id
        WHERE rss.direction='outbound'
          AND t.snapshot_sequence IS NOT NULL
        GROUP BY t.title_id, rss.username
        ON CONFLICT (title_id, device_id) DO UPDATE
            SET last_seq = MAX(last_seq, excluded.last_seq),
                updated_at = MAX(updated_at, excluded.updated_at)
            WHERE excluded.last_seq > last_seq
    """)
    conn.commit()
    if cur.rowcount:
        log.info(
            "startup: backfilled device_title_head for %d romm push_head title(s)", cur.rowcount
        )
    return cur.rowcount


def _purge_orphan_staging_dirs(conn, staging_dir: Path) -> None:
    if not staging_dir.exists():
        return
    known = {r["session_id"] for r in conn.execute("SELECT session_id FROM upload_sessions")}
    for child in staging_dir.iterdir():
        if child.is_dir() and child.name not in known:
            shutil.rmtree(child, ignore_errors=True)
            log.info("startup: purged orphan staging dir %s", child.name[:8])
