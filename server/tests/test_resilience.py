"""
Resilience and idempotency behavioral tests.
Covers: startup recovery, stale upload expiry, missing archive.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import database as db
import startup
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, poll_queue, report_catalog

SAVE = b"resilience-test-save"


def test_startup_expires_stale_uploading_transaction(conn, tmp_dirs):
    staging, archive = tmp_dirs
    # Create an UPLOADING transaction with last_active_at 13h ago
    txn_id, session_id = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1,
        total_size_bytes=100,
        parent_sequence_num=None,
    )
    stale_time = (datetime.now(UTC) - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE upload_sessions SET last_active_at=? WHERE session_id=?",
        (stale_time, session_id),
    )

    startup.run(conn, staging, archive)

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "FAILED"


def test_expire_writes_python_format_timestamp(conn, tmp_dirs):
    """_expire_stale_uploads must write updated_at in Python ISO format ('T' separator),
    not SQLite datetime('now') format ('YYYY-MM-DD HH:MM:SS').

    Bug: using datetime('now') makes the cutoff comparison in hard_delete_old_failed wrong
    on the exact retention-boundary date: ' ' < 'T' in ASCII causes 23:00 (SQLite) to sort
    before 12:00 (Python), so a transaction can be prematurely GC'd the same day it expired.
    """
    staging, archive = tmp_dirs
    txn_id, session_id = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1, total_size_bytes=5, parent_sequence_num=None
    )
    stale_time = (datetime.now(UTC) - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE upload_sessions SET last_active_at=? WHERE session_id=?",
        (stale_time, session_id),
    )
    conn.commit()

    startup._expire_stale_uploads(conn, staging)

    row = conn.execute(
        "SELECT state, updated_at FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["state"] == "FAILED"
    assert "T" in row["updated_at"], (
        f"updated_at must use Python ISO format (with 'T'), got: {row['updated_at']!r}"
    )


def test_startup_does_not_expire_recent_upload(conn, tmp_dirs):
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1,
        total_size_bytes=100,
        parent_sequence_num=None,
    )

    startup.run(conn, staging, archive)

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "UPLOADING"


def test_startup_fails_ready_with_missing_archive(conn, tmp_dirs):
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1,
        total_size_bytes=100,
        parent_sequence_num=None,
    )
    missing_path = str(archive / "ghost" / "save.zip")
    conn.execute(
        "UPDATE sync_transactions "
        "SET state='READY_FOR_RESTORE', snapshot_path=?, snapshot_sequence=1, sha256='abc' "
        "WHERE transaction_id=?",
        (missing_path, txn_id),
    )

    startup.run(conn, staging, archive)

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "FAILED"


def test_startup_supersedes_legacy_bin_archives(conn, tmp_dirs):
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1,
        total_size_bytes=9,
        parent_sequence_num=None,
    )
    legacy_path = str(archive / txn_id / "save.bin")
    conn.execute(
        "UPDATE sync_transactions "
        "SET state='READY_FOR_RESTORE', snapshot_path=?, snapshot_sequence=1, sha256='abc' "
        "WHERE transaction_id=?",
        (legacy_path, txn_id),
    )

    startup.run(conn, staging, archive)

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "SUPERSEDED"


def test_startup_keeps_ready_with_existing_archive(conn, tmp_dirs):
    staging, archive = tmp_dirs
    archive_path = archive / "real_txn" / "save.zip"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"real_data")

    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1,
        total_size_bytes=9,
        parent_sequence_num=None,
    )
    conn.execute(
        "UPDATE sync_transactions "
        "SET state='READY_FOR_RESTORE', snapshot_path=?, snapshot_sequence=1, sha256='abc' "
        "WHERE transaction_id=?",
        (str(archive_path), txn_id),
    )

    startup.run(conn, staging, archive)

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "READY_FOR_RESTORE"



def test_orphan_staging_dirs_purged(conn, tmp_dirs):
    staging, archive = tmp_dirs
    orphan = staging / "orphan-session-id"
    orphan.mkdir()
    (orphan / "0000000000.bin").write_bytes(b"orphan")

    startup.run(conn, staging, archive)

    assert not orphan.exists()


def test_hard_delete_removes_old_failed_transaction(conn, tmp_dirs):
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    archive_path = archive / txn_id / "save.zip"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"stale-data")
    stale_time = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED', snapshot_path=?, updated_at=? "
        "WHERE transaction_id=?",
        (str(archive_path), stale_time, txn_id),
    )

    startup.hard_delete_old_failed(conn, archive)

    assert not archive_path.exists()
    row = conn.execute(
        "SELECT * FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row is None


def test_hard_delete_spares_failed_with_sequence(conn, tmp_dirs):
    """FAILED rows that burned a sequence slot must NOT be GC'd.
    Deleting them creates a permanent gap in save numbers that the user
    can never explain (save #1 disappears from history silently)."""
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    stale_time = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED', snapshot_sequence=1, updated_at=? "
        "WHERE transaction_id=?",
        (stale_time, txn_id),
    )

    startup.hard_delete_old_failed(conn, archive)

    row = conn.execute(
        "SELECT * FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row is not None, "FAILED row with snapshot_sequence must not be GC'd"
    assert row["snapshot_sequence"] == 1


def test_sync_counters_does_not_renumber_head_when_preservation_has_higher_seq(conn, tmp_dirs):
    """Root-cause regression: a preservation upload with seq=2 must NOT cause startup to
    renumber the HEAD (seq=1) to seq=3.

    Proven bug: _sync_counters_and_resequence_heads computed actual_max across ALL
    transactions including preservation ones, then unconditionally overwrote the HEAD's
    snapshot_sequence when head_seq < actual_max.  A deploy after a preservation upload
    would silently mutate committed sequences, causing the activity feed (logged at seq=1)
    to disagree with the game page (showing seq=3)."""
    staging, archive = tmp_dirs

    # Inbound A — normal (non-preservation) HEAD with seq=1
    txn_a, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    conn.execute(
        "UPDATE sync_transactions SET state='READY_FOR_RESTORE', snapshot_sequence=1, "
        "sha256='aaa', snapshot_path='/fake/a', preservation=0 WHERE transaction_id=?",
        (txn_a,),
    )
    conn.execute(
        "INSERT INTO snapshot_counters (title_id, counter) VALUES (?, 1) "
        "ON CONFLICT(title_id) DO UPDATE SET counter=1",
        (TITLE_1.upper(),),
    )

    # Inbound B — preservation upload with seq=2 (legitimately higher than HEAD)
    txn_b, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    conn.execute(
        "UPDATE sync_transactions SET state='READY_FOR_RESTORE', snapshot_sequence=2, "
        "sha256='bbb', snapshot_path='/fake/b', preservation=1 WHERE transaction_id=?",
        (txn_b,),
    )
    conn.execute(
        "UPDATE snapshot_counters SET counter=2 WHERE title_id=?",
        (TITLE_1.upper(),),
    )
    conn.commit()

    startup._sync_counters_and_resequence_heads(conn)

    seq_a = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_a,)
    ).fetchone()["snapshot_sequence"]
    seq_b = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_b,)
    ).fetchone()["snapshot_sequence"]
    counter = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]

    assert seq_a == 1, f"HEAD seq must not be renumbered by startup; got {seq_a}"
    assert seq_b == 2, f"Preservation seq must be unchanged; got {seq_b}"
    assert counter == 2, f"Counter should be synced to actual_max=2; got {counter}"
    # Confirm no seq=3 was created
    row3 = conn.execute(
        "SELECT transaction_id FROM sync_transactions WHERE snapshot_sequence=3 AND title_id=?",
        (TITLE_1.upper(),),
    ).fetchone()
    assert row3 is None, "No transaction should have been renumbered to seq=3"


def test_migration_removes_lease_columns(tmp_path):
    """Migration path: DB with old lease columns → lease cols dropped, DELIVERING → READY_FOR_RESTORE."""
    import sqlite3
    raw = sqlite3.connect(str(tmp_path / "old.db"))
    raw.row_factory = sqlite3.Row
    raw.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            state TEXT NOT NULL,
            snapshot_sequence INTEGER,
            parent_sequence_num INTEGER,
            has_conflict INTEGER NOT NULL DEFAULT 0,
            target_device_id TEXT,
            lease_id TEXT,
            lease_expires_at TEXT,
            sha256 TEXT,
            snapshot_path TEXT,
            total_size_bytes INTEGER,
            checkpoint_ledger TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE upload_sessions (
            session_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL UNIQUE,
            session_state TEXT NOT NULL DEFAULT 'ACTIVE',
            total_size_bytes INTEGER NOT NULL,
            chunk_size_bytes INTEGER NOT NULL DEFAULT 0,
            expected_total_chunks INTEGER NOT NULL DEFAULT 0,
            server_verified_bytes INTEGER NOT NULL DEFAULT 0,
            last_active_at TEXT NOT NULL
        );
        INSERT INTO sync_transactions VALUES
            ('txn-1','0100abc','dev-a','outbound','DELIVERING',1,0,0,'dev-b','lease-x','2026-01-01',NULL,NULL,100,NULL,'2026-01-01','2026-01-01'),
            ('txn-2','0100abc','dev-a','outbound','READY_FOR_RESTORE',2,0,0,'dev-c',NULL,NULL,NULL,NULL,100,NULL,'2026-01-01','2026-01-01');
    """)
    raw.commit()

    db._apply_migrations(raw)
    raw.commit()

    cols = {r[1] for r in raw.execute("PRAGMA table_info(sync_transactions)").fetchall()}
    assert "lease_id" not in cols
    assert "lease_expires_at" not in cols

    rows = {r["transaction_id"]: r["state"] for r in raw.execute("SELECT transaction_id, state FROM sync_transactions").fetchall()}
    assert rows["txn-1"] == "READY_FOR_RESTORE"
    assert rows["txn-2"] == "READY_FOR_RESTORE"
    raw.close()


def test_migration_adds_owner_user_id_to_existing_db(tmp_path):
    """Upgrade path: existing DB with events table but no owner_user_id column.
    open_db() must complete without error and add the column + indexes."""
    import sqlite3
    raw = sqlite3.connect(str(tmp_path / "existing.db"))
    raw.row_factory = sqlite3.Row
    raw.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
            state TEXT NOT NULL,
            snapshot_sequence INTEGER,
            parent_sequence_num INTEGER,
            has_conflict INTEGER NOT NULL DEFAULT 0,
            preservation INTEGER NOT NULL DEFAULT 0,
            target_device_id TEXT,
            sha256 TEXT,
            snapshot_path TEXT,
            total_size_bytes INTEGER,
            checkpoint_ledger TEXT,
            user_key TEXT,
            user_display TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_outbound_per_device_title
            ON sync_transactions(target_device_id, title_id, COALESCE(user_key,''))
            WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE';
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title_id TEXT,
            device_id TEXT,
            transaction_id TEXT,
            message TEXT NOT NULL
        );
        CREATE INDEX idx_events_time ON events(occurred_at DESC);
    """)
    raw.commit()
    raw.close()

    # open_db must not raise — this is what the production server calls on startup
    conn = db.open_db(tmp_path / "existing.db")

    evt_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert "owner_user_id" in evt_cols, "open_db must add owner_user_id to existing events table"

    indexes = {r[1] for r in conn.execute("PRAGMA index_list(events)").fetchall()}
    assert "idx_events_owner" in indexes

    sync_indexes = {r[1] for r in conn.execute("PRAGMA index_list(sync_transactions)").fetchall()}
    assert "idx_sync_owner" in sync_indexes
    assert "idx_sync_owner_title" in sync_indexes

    conn.close()


def test_migration_flattens_snapshot_counters_device_id(tmp_path):
    """Migration: old snapshot_counters with device_id column → global per-title counter."""
    import sqlite3
    raw = sqlite3.connect(str(tmp_path / "old_counters.db"))
    raw.row_factory = sqlite3.Row
    raw.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE events (
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title_id TEXT,
            device_id TEXT,
            transaction_id TEXT,
            message TEXT
        );
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            state TEXT NOT NULL,
            snapshot_sequence INTEGER,
            parent_sequence_num INTEGER,
            has_conflict INTEGER NOT NULL DEFAULT 0,
            target_device_id TEXT,
            sha256 TEXT,
            snapshot_path TEXT,
            total_size_bytes INTEGER,
            checkpoint_ledger TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE upload_sessions (
            session_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL UNIQUE,
            session_state TEXT NOT NULL DEFAULT 'ACTIVE',
            total_size_bytes INTEGER NOT NULL,
            chunk_size_bytes INTEGER NOT NULL DEFAULT 0,
            expected_total_chunks INTEGER NOT NULL DEFAULT 0,
            server_verified_bytes INTEGER NOT NULL DEFAULT 0,
            last_active_at TEXT NOT NULL
        );
        CREATE TABLE snapshot_counters (
            title_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            counter INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (title_id, device_id)
        );
        INSERT INTO snapshot_counters VALUES
            ('0100F2C0115B6000', 'AABBCCDDEEFF', 15),
            ('0100F2C0115B6000', '112233445566', 12),
            ('0100EC001DE7E000', 'AABBCCDDEEFF', 3);
    """)
    raw.commit()

    db._apply_migrations(raw)
    raw.commit()

    cols = {r[1] for r in raw.execute("PRAGMA table_info(snapshot_counters)").fetchall()}
    assert "device_id" not in cols
    assert "title_id" in cols
    assert "counter" in cols

    rows = {r["title_id"]: r["counter"] for r in raw.execute("SELECT title_id, counter FROM snapshot_counters").fetchall()}
    assert rows["0100F2C0115B6000"] == 15
    assert rows["0100EC001DE7E000"] == 3
    raw.close()


def test_processing_rollback_on_finalize_error(conn, tmp_dirs, monkeypatch):
    """Exception inside BEGIN IMMEDIATE block → ROLLBACK issued, transaction set to FAILED."""
    import processing
    staging, archive = tmp_dirs

    txn_id, session_id = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    conn.execute(
        "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
    )
    conn.execute(
        "UPDATE upload_sessions SET session_state='COMPLETED', server_verified_bytes=5 "
        "WHERE transaction_id=?",
        (txn_id,),
    )
    seq = db.next_global_sequence(conn, TITLE_1)
    conn.execute(
        "UPDATE sync_transactions SET snapshot_sequence=? WHERE transaction_id=?",
        (seq, txn_id),
    )
    conn.commit()

    staging_file = staging / session_id / "save.zip"
    staging_file.parent.mkdir(parents=True)
    staging_file.write_bytes(b"save")

    monkeypatch.setattr(db, "upsert_device_title_head", lambda *_: (_ for _ in ()).throw(RuntimeError("injected")))

    processing._run(txn_id, session_id, staging, archive, conn.path)

    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["state"] == "FAILED"


def test_crash_after_file_move_recovered_by_startup(conn, tmp_dirs, client):
    """Crash between shutil.move and conn.commit must be recovered by startup.

    Reproduces the atomicity gap in processing._process:
      shutil.move(staging → archive)   ← point of no return
      ... CPU-bound sha256 ...
      conn.execute("BEGIN IMMEDIATE")
      conn.commit()                    ← crash here leaves PROCESSING + archive on disk

    Without the fix: transaction stays PROCESSING until _expire_stale_uploads fires
    after 12 h, then becomes FAILED — save is never delivered to peers.
    With the fix: startup._recover_interrupted_processing re-runs the commit step
    and advances the transaction to READY_FOR_RESTORE.
    """
    import processing

    staging, archive = tmp_dirs

    # Upload normally so the archive lands on disk.
    txn_id = do_upload(client, DEVICE_A, TITLE_1, SAVE)
    archive_path = archive / txn_id / "save.zip"
    assert archive_path.exists(), "archive must exist after successful upload"

    # Simulate the crash state: rewind DB fields to what they were before the commit,
    # but leave the archive file in place.
    conn.execute(
        "UPDATE sync_transactions SET state='PROCESSING', sha256=NULL, "
        "snapshot_path=NULL, snapshot_sequence=NULL, updated_at=datetime('now') "
        "WHERE transaction_id=?",
        (txn_id,),
    )
    conn.execute(
        "UPDATE upload_sessions SET session_state='COMPLETED' WHERE transaction_id=?",
        (txn_id,),
    )
    conn.commit()

    assert conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["state"] == "PROCESSING"

    # Startup recovery should detect archive-in-place PROCESSING txn and re-run commit.
    startup.run(conn, staging, archive)

    row = conn.execute(
        "SELECT state, snapshot_path, snapshot_sequence FROM sync_transactions "
        "WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE", (
        f"expected READY_FOR_RESTORE after recovery, got {row['state']}"
    )
    assert row["snapshot_path"] is not None
    assert row["snapshot_sequence"] is not None


def test_repair_duplicate_sequences(conn):
    """Rows sharing (title, seq) with different sha256 get reassigned unique seqs."""
    now = "2026-01-01T00:00:00Z"
    later = "2026-01-01T01:00:00Z"
    # Seed two inbound rows with the same snapshot_sequence but different sha256
    for txn_id, sha256, ts, device in [
        ("txn-old-a", "aaa", now,   DEVICE_A),
        ("txn-old-b", "bbb", later, DEVICE_B),
    ]:
        conn.execute(
            "INSERT INTO sync_transactions "
            "(transaction_id,title_id,source_device_id,direction,state,"
            " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
            "VALUES (?,?,?,'inbound','SUPERSEDED',1,?,0,0,?,?)",
            (txn_id, TITLE_1, device, sha256, ts, ts),
        )
    conn.execute(
        "INSERT INTO snapshot_counters (title_id,counter) VALUES (?,5)",
        (TITLE_1.upper(),),
    )
    conn.commit()

    startup._repair_duplicate_sequences(conn)

    seqs = {
        r["transaction_id"]: r["snapshot_sequence"]
        for r in conn.execute(
            "SELECT transaction_id, snapshot_sequence FROM sync_transactions "
            "WHERE title_id=? AND direction='inbound'",
            (TITLE_1.upper(),),
        ).fetchall()
    }
    # Earliest row keeps seq=1; second gets a new seq > 1
    assert seqs["txn-old-a"] == 1
    assert seqs["txn-old-b"] > 1
    assert seqs["txn-old-a"] != seqs["txn-old-b"]


def test_repair_duplicate_sequences_updates_outbound(conn):
    """Outbound transactions linked to a reassigned inbound get the new seq."""
    now = "2026-01-01T00:00:00Z"
    later = "2026-01-01T01:00:00Z"
    for txn_id, sha256, ts, device in [
        ("in-a", "aaa", now,   DEVICE_A),
        ("in-b", "bbb", later, DEVICE_B),
    ]:
        conn.execute(
            "INSERT INTO sync_transactions "
            "(transaction_id,title_id,source_device_id,direction,state,"
            " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
            "VALUES (?,?,?,'inbound','SUPERSEDED',1,?,0,0,?,?)",
            (txn_id, TITLE_1, device, sha256, ts, ts),
        )
    # Outbound for the extra inbound (DEVICE_B, seq=1)
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,target_device_id,has_conflict,preservation,created_at,updated_at) "
        "VALUES ('out-b',?,?,'outbound','SUPERSEDED',1,?,0,0,?,?)",
        (TITLE_1.upper(), DEVICE_B, DEVICE_A, now, now),
    )
    conn.execute(
        "INSERT INTO snapshot_counters (title_id,counter) VALUES (?,5)",
        (TITLE_1.upper(),),
    )
    conn.commit()

    startup._repair_duplicate_sequences(conn)

    new_in_seq = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id='in-b'"
    ).fetchone()["snapshot_sequence"]
    out_seq = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id='out-b'"
    ).fetchone()["snapshot_sequence"]
    assert out_seq == new_in_seq


def test_hard_delete_skips_recent_failed(conn, tmp_dirs):
    staging, archive = tmp_dirs
    txn_id, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 5, None)
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED' WHERE transaction_id=?", (txn_id,)
    )

    startup.hard_delete_old_failed(conn, archive)

    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["state"] == "FAILED"


def test_sync_counters_fixes_lagging_counter(conn):
    """Counter below actual_max → synced up to actual_max."""
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
        "VALUES ('txn-head',?,?,'inbound','READY_FOR_RESTORE',5,'abc',0,0,?,?)",
        (TITLE_1.upper(), DEVICE_A, now, now),
    )
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
        "VALUES ('txn-sup',?,?,'inbound','SUPERSEDED',39,'def',0,0,?,?)",
        (TITLE_1.upper(), DEVICE_A, now, now),
    )
    conn.execute(
        "INSERT INTO snapshot_counters (title_id, counter) VALUES (?, 5)",
        (TITLE_1.upper(),),
    )
    conn.commit()

    startup._sync_counters_and_resequence_heads(conn)

    counter = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]
    assert counter >= 39


def test_sync_counters_does_not_renumber_head_below_max(conn):
    """HEAD seq < actual_max must NOT cause HEAD renumbering.
    snapshot_sequence is immutable once committed.  The counter is synced
    to actual_max so next_global_sequence stays monotonically increasing."""
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
        "VALUES ('txn-head',?,?,'inbound','READY_FOR_RESTORE',5,'abc',0,0,?,?)",
        (TITLE_1.upper(), DEVICE_A, now, now),
    )
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,sha256,has_conflict,preservation,created_at,updated_at) "
        "VALUES ('txn-old',?,?,'inbound','SUPERSEDED',39,'def',0,0,?,?)",
        (TITLE_1.upper(), DEVICE_A, now, now),
    )
    conn.execute(
        "INSERT INTO snapshot_counters (title_id, counter) VALUES (?, 39)",
        (TITLE_1.upper(),),
    )
    conn.commit()

    startup._sync_counters_and_resequence_heads(conn)

    # HEAD sequence must be unchanged — renumbering committed rows is the bug
    head_seq = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id='txn-head'"
    ).fetchone()["snapshot_sequence"]
    assert head_seq == 5, f"HEAD must not be renumbered; got {head_seq}"

    # Counter is synced to actual_max so next allocation doesn't collide
    counter = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]
    assert counter == 39


# ── upsert_device_title_head monotonicity ─────────────────────────────────────


def test_upsert_device_title_head_monotonic_advance(conn):
    db.upsert_device_title_head(conn, TITLE_1, DEVICE_A, 3)
    db.upsert_device_title_head(conn, TITLE_1, DEVICE_A, 5)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (TITLE_1.upper(), DEVICE_A),
    ).fetchone()
    assert row["last_seq"] == 5


def test_upsert_device_title_head_monotonic_no_regress(conn):
    db.upsert_device_title_head(conn, TITLE_1, DEVICE_A, 5)
    db.upsert_device_title_head(conn, TITLE_1, DEVICE_A, 3)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (TITLE_1.upper(), DEVICE_A),
    ).fetchone()
    assert row["last_seq"] == 5


# ── _repair_romm_push_head_device_title_head ──────────────────────────────────


_romm_save_id_counter = 0


def _seed_romm_save_sync(conn, username, title_id, seq):
    import uuid
    global _romm_save_id_counter
    _romm_save_id_counter += 1
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT OR IGNORE INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,has_conflict,created_at,updated_at)"
        " VALUES (?,?,'dev-x','inbound','READY_FOR_RESTORE',?,0,datetime('now'),datetime('now'))",
        (txn_id, title_id.upper(), seq),
    )
    rom_id = 999
    db.upsert_romm_title_map(conn, username, title_id, rom_id)
    conn.execute(
        "INSERT OR IGNORE INTO romm_save_sync"
        " (username,rom_id,romm_save_id,direction,transaction_id,synced_at)"
        " VALUES (?,?,?,'outbound',?,datetime('now'))",
        (username, rom_id, _romm_save_id_counter, txn_id),
    )
    conn.commit()


def test_repair_romm_backfill_writes_max_seq(conn):
    """Backfill collapses multiple romm_save_sync entries to MAX(snapshot_sequence)."""
    username = "testuser"
    _seed_romm_save_sync(conn, username, TITLE_1, seq=2)
    _seed_romm_save_sync(conn, username, TITLE_1, seq=4)
    n = startup._repair_romm_push_head_device_title_head(conn)
    assert n == 1
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (f"romm:{username}", TITLE_1.upper()),
    ).fetchone()
    assert row["last_seq"] == 4


def test_repair_romm_backfill_insert_or_ignore(conn):
    """Existing device_title_head at seq=5 is not overwritten by backfill at seq=3."""
    username = "testuser"
    db.upsert_device_title_head(conn, TITLE_1, f"romm:{username}", 5)
    _seed_romm_save_sync(conn, username, TITLE_1, seq=3)
    startup._repair_romm_push_head_device_title_head(conn)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (f"romm:{username}", TITLE_1.upper()),
    ).fetchone()
    assert row["last_seq"] == 5


# ── ACK supersedes prior FAILED outbounds ──────────────────────────────────────


def test_ack_supersedes_prior_failed_outbounds(conn, tmp_dirs, client):
    """ACK handler marks prior FAILED outbounds for same title+target as SUPERSEDED."""
    import uuid
    from helpers import do_ack

    now = "2026-01-01T00:00:00Z"

    # Ghost FAILED row — an older delivery attempt that never cleaned up
    ghost_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "  target_device_id,snapshot_path,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','FAILED',1,?,NULL,'abc',10,?,?)",
        (ghost_id, TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )
    # Real READY_FOR_RESTORE outbound — what the device will ACK
    outbound_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "  target_device_id,snapshot_path,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','READY_FOR_RESTORE',2,?,NULL,'def',10,?,?)",
        (outbound_id, TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )
    # Register DEVICE_B so the sync API accepts the X-Device-ID header
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_B})

    do_ack(client, DEVICE_B, outbound_id)

    ghost = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (ghost_id,)
    ).fetchone()
    assert ghost["state"] == "SUPERSEDED"


# ── Supersede FAILED outbounds for uninstalled titles ─────────────────────────


def test_supersede_failed_outbounds_for_uninstalled_titles(conn):
    """FAILED outbounds for titles not in device_installed_games are superseded on startup."""
    import uuid

    now = "2026-01-01T00:00:00Z"

    # Title NOT installed on DEVICE_B — delivery will always fail
    uninstalled_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "  target_device_id,snapshot_path,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','FAILED',1,?,NULL,'abc',10,?,?)",
        (uninstalled_id, TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )

    # TITLE_2 IS installed on DEVICE_B — keep this FAILED row (still deliverable)
    conn.execute(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?,?)",
        (DEVICE_B, TITLE_2.upper()),
    )
    installed_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "  target_device_id,snapshot_path,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','FAILED',2,?,NULL,'def',10,?,?)",
        (installed_id, TITLE_2.upper(), DEVICE_A, DEVICE_B, now, now),
    )

    n = db.supersede_failed_outbounds_for_uninstalled(conn)
    assert n == 1

    assert conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (uninstalled_id,)
    ).fetchone()["state"] == "SUPERSEDED"

    # TITLE_2 is installed — row stays FAILED (still deliverable)
    assert conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (installed_id,)
    ).fetchone()["state"] == "FAILED"


# ── Catalog report event triggers immediate supersede ─────────────────────────


def test_catalog_update_supersedes_failed_outbounds_for_uninstalled(conn, client):
    """POST device-config with installed_titles excluding a title → FAILED outbound superseded."""
    import uuid

    now = "2026-01-01T00:00:00Z"

    # DEVICE_B had TITLE_1 installed and received a failed delivery
    failed_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "  target_device_id,snapshot_path,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','FAILED',1,?,NULL,'abc',10,?,?)",
        (failed_id, TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )

    # DEVICE_B reports its catalog — TITLE_1 is no longer installed
    report_catalog(client, DEVICE_B, [TITLE_2.upper()])

    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (failed_id,)
    ).fetchone()
    assert row["state"] == "SUPERSEDED"
