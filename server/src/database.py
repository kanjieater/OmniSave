import logging
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# Nintendo sentinel profile: present when a save slot has no associated account (no-account placeholder).
# Never a real user; must be excluded from all profile-claim and auto-claim logic.
NULL_PROFILE_ID = "0000000000000000"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL DEFAULT '',
    hardware_type TEXT NOT NULL DEFAULT '',
    client_type   TEXT NOT NULL DEFAULT '',
    last_seen     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    owner_user_id TEXT,
    deleted_at    TEXT
);

CREATE TABLE IF NOT EXISTS device_pairing_codes (
    code       TEXT PRIMARY KEY,
    device_id  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS device_share_codes (
    code       TEXT PRIMARY KEY,
    device_id  TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS device_access (
    device_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (device_id, user_id)
);

CREATE TABLE IF NOT EXISTS sync_transactions (
    transaction_id      TEXT PRIMARY KEY,
    title_id            TEXT NOT NULL,
    source_device_id    TEXT NOT NULL,
    direction           TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    state               TEXT NOT NULL,
    snapshot_sequence   INTEGER,
    parent_sequence_num INTEGER,
    has_conflict        INTEGER NOT NULL DEFAULT 0,  -- diagnostic telemetry only; never controls behavior or shown to user
    preservation        INTEGER NOT NULL DEFAULT 0,  -- 1 = pre-restore backup; never fans out, never advances HEAD
    target_device_id    TEXT,
    sha256              TEXT,
    snapshot_path       TEXT,
    total_size_bytes    INTEGER,
    checkpoint_ledger   TEXT,                          -- V2: JSON uint32 array; set after processing
    user_key            TEXT,                          -- opaque account UID hex from device; NULL for legacy rows
    user_display        TEXT,                          -- cosmetic account name from device; never used for routing
    owner_user_id       TEXT,                          -- stamped once at inbound creation from device_auth; immutable
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_outbound_per_device_title
ON sync_transactions(target_device_id, title_id, COALESCE(owner_user_id,''))
WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE';

CREATE TABLE IF NOT EXISTS upload_sessions (
    session_id            TEXT PRIMARY KEY,
    transaction_id        TEXT NOT NULL UNIQUE,
    session_state         TEXT NOT NULL DEFAULT 'ACTIVE',
    total_size_bytes      INTEGER NOT NULL,
    chunk_size_bytes      INTEGER NOT NULL DEFAULT 0,     -- legacy, unused in V2
    expected_total_chunks INTEGER NOT NULL DEFAULT 0,    -- legacy, unused in V2
    server_verified_bytes INTEGER NOT NULL DEFAULT 0,    -- V2: monotonic high-water mark
    checkpoint_ledger     TEXT,                          -- V2: frozen at manifest POST
    last_active_at        TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES sync_transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS upload_chunks (
    session_id       TEXT NOT NULL,
    chunk_index      INTEGER NOT NULL,
    chunk_size_bytes INTEGER NOT NULL,
    PRIMARY KEY (session_id, chunk_index),
    FOREIGN KEY (session_id) REFERENCES upload_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS snapshot_counters (
    title_id TEXT PRIMARY KEY,
    counter  INTEGER NOT NULL DEFAULT 0
);

-- Per-device tracker: last global sequence each device has seen for a title.
-- Used for pre-restore preservation check and diagnostic divergence logging only.
CREATE TABLE IF NOT EXISTS device_title_head (
    title_id   TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    last_seq   INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (title_id, device_id)
);

CREATE TABLE IF NOT EXISTS server_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_config (
    username TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (username, key)
);

CREATE TABLE IF NOT EXISTS auth_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    session_token TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    token       TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_auth (
    device_id      TEXT PRIMARY KEY,
    device_token   TEXT UNIQUE NOT NULL,
    user_id        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_seen      TEXT,
    config_pending INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS device_profile_map (
    device_id    TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    profile_name TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    PRIMARY KEY (device_id, profile_id, user_id),
    UNIQUE (device_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_dpm_user ON device_profile_map (user_id);

CREATE TABLE IF NOT EXISTS device_known_profiles (
    device_id    TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    profile_name TEXT NOT NULL DEFAULT '',
    last_seen    TEXT NOT NULL,
    PRIMARY KEY (device_id, profile_id)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at    TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    title_id       TEXT,
    device_id      TEXT,
    transaction_id TEXT,
    message        TEXT NOT NULL,
    owner_user_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(occurred_at DESC);

CREATE TABLE IF NOT EXISTS romm_title_map (
    username  TEXT NOT NULL,
    title_id  TEXT NOT NULL,
    rom_id    INTEGER NOT NULL,
    mapped_at TEXT,
    PRIMARY KEY (username, title_id)
);

CREATE TABLE IF NOT EXISTS romm_game_cache (
    username   TEXT NOT NULL,
    rom_id     INTEGER NOT NULL,
    name       TEXT,
    icon_url   TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (username, rom_id)
);

CREATE TABLE IF NOT EXISTS labels (
    entity_type TEXT NOT NULL CHECK(entity_type IN ('game')),
    entity_id   TEXT NOT NULL,
    label       TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS romm_save_sync (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL,
    rom_id         INTEGER NOT NULL,
    romm_save_id   INTEGER NOT NULL,
    direction      TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    transaction_id TEXT,
    synced_at      TEXT NOT NULL,
    UNIQUE(username, rom_id, romm_save_id, direction)
);

-- Per-device backup state convergence: one row per committed snapshot per device.
-- Generation is monotonically increasing per device_id.
-- Clients send their last known generation on heartbeat; server returns delta entries.
CREATE TABLE IF NOT EXISTS device_backup_updates (
    device_id         TEXT    NOT NULL,
    generation        INTEGER NOT NULL,
    title_id          TEXT    NOT NULL,
    snapshot_sequence INTEGER NOT NULL,
    committed_at      TEXT    NOT NULL,
    PRIMARY KEY (device_id, generation)
);

-- Device game catalog: authoritative inventory of which games have save data on each device.
-- Reported by the sysmodule on boot and when the catalog changes.
-- title_id is stored uppercase (matching sync_transactions convention).
CREATE TABLE IF NOT EXISTS device_installed_games (
    device_id    TEXT NOT NULL,
    title_id     TEXT NOT NULL,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (device_id, title_id)
);
CREATE INDEX IF NOT EXISTS idx_dig_title ON device_installed_games (title_id);

-- Raw activity events reported by trusted devices.
-- Platform-agnostic: the server has no concept of Switch/Nintendo/pdm.
-- Deduplication is content-addressed; resubmission is always safe.
CREATE TABLE IF NOT EXISTS device_play_events (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id            TEXT    NOT NULL,
    owner_user_id        TEXT    NOT NULL,
    profile_id           TEXT    NOT NULL DEFAULT '',
    application_id       TEXT    NOT NULL DEFAULT '',
    event_type           TEXT    NOT NULL CHECK(event_type IN (
                             'APPLICATION_STARTED', 'APPLICATION_EXITED',
                             'APPLICATION_FOCUSED', 'APPLICATION_UNFOCUSED',
                             'PROFILE_ACTIVE', 'PROFILE_INACTIVE')),
    event_timestamp      INTEGER NOT NULL,
    monotonic_timestamp  INTEGER NOT NULL,
    recorded_at          TEXT    NOT NULL,
    UNIQUE(device_id, event_type, event_timestamp, monotonic_timestamp, application_id, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_dpe_device_app ON device_play_events(device_id, application_id);
CREATE INDEX IF NOT EXISTS idx_dpe_time       ON device_play_events(event_timestamp DESC);
"""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER TABLE migrations for upgrading existing DBs."""
    existing = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }

    # V2: add new columns to upload_sessions (ignore error if already present)
    for col, ddl in [
        ("server_verified_bytes", "INTEGER NOT NULL DEFAULT 0"),
        ("checkpoint_ledger", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE upload_sessions ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # V2: add checkpoint_ledger to sync_transactions
    try:
        conn.execute("ALTER TABLE sync_transactions ADD COLUMN checkpoint_ledger TEXT")
    except sqlite3.OperationalError:
        pass

    # Remove lease columns (table recreation required — SQLite can't drop columns in CHECK constraints)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_transactions)").fetchall()}
    if "lease_id" in cols:
        conn.execute(
            "UPDATE sync_transactions SET state='READY_FOR_RESTORE', updated_at=? "
            "WHERE state='DELIVERING'",
            (_now(),),
        )
        conn.execute("""
            CREATE TABLE sync_transactions_v2 (
                transaction_id      TEXT PRIMARY KEY,
                title_id            TEXT NOT NULL,
                source_device_id    TEXT NOT NULL,
                direction           TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                state               TEXT NOT NULL,
                snapshot_sequence   INTEGER,
                parent_sequence_num INTEGER,
                has_conflict        INTEGER NOT NULL DEFAULT 0,
                target_device_id    TEXT,
                sha256              TEXT,
                snapshot_path       TEXT,
                total_size_bytes    INTEGER,
                checkpoint_ledger   TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO sync_transactions_v2
            SELECT transaction_id, title_id, source_device_id, direction, state,
                   snapshot_sequence, parent_sequence_num, has_conflict, target_device_id,
                   sha256, snapshot_path, total_size_bytes, checkpoint_ledger,
                   created_at, updated_at
            FROM sync_transactions
        """)
        conn.execute("DROP TABLE sync_transactions")
        conn.execute("ALTER TABLE sync_transactions_v2 RENAME TO sync_transactions")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_outbound_per_device_title
            ON sync_transactions(target_device_id, title_id)
            WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE'
        """)

    # V2: legacy columns — set defaults on existing rows if they have NULL
    if "upload_sessions" in existing:
        conn.execute("UPDATE upload_sessions SET chunk_size_bytes=0 WHERE chunk_size_bytes IS NULL")
        conn.execute(
            "UPDATE upload_sessions SET expected_total_chunks=0 WHERE expected_total_chunks IS NULL"
        )
        conn.execute(
            "UPDATE upload_sessions SET server_verified_bytes=0 WHERE server_verified_bytes IS NULL"
        )

    # Add mapped_at to romm_title_map if absent (nullable, backfilled below)
    try:
        conn.execute("ALTER TABLE romm_title_map ADD COLUMN mapped_at TEXT")
        conn.execute(
            "UPDATE romm_title_map SET mapped_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            " WHERE mapped_at IS NULL"
        )
    except sqlite3.OperationalError:
        pass

    # Add pull_initialized to romm_title_map — tracks whether the pull loop has
    # established its baseline for this ROM (existing saves marked as seen, not ingested).
    try:
        conn.execute(
            "ALTER TABLE romm_title_map ADD COLUMN pull_initialized INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    # Global snapshot counter: flatten per-device → per-title
    counters_cols = {r[1] for r in conn.execute("PRAGMA table_info(snapshot_counters)").fetchall()}
    if "device_id" in counters_cols:
        conn.execute("""
            CREATE TABLE snapshot_counters_global (
                title_id TEXT PRIMARY KEY,
                counter  INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO snapshot_counters_global (title_id, counter)
            SELECT title_id, MAX(counter) FROM snapshot_counters GROUP BY title_id
        """)
        conn.execute("DROP TABLE snapshot_counters")
        conn.execute("ALTER TABLE snapshot_counters_global RENAME TO snapshot_counters")
        log_msg = "applied migration: flatten snapshot_counters to global (dropped device_id)"
        conn.execute(
            "INSERT INTO events (occurred_at,event_type,title_id,device_id,transaction_id,message)"
            " VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'),'MIGRATION',NULL,NULL,NULL,?)",
            (log_msg,),
        )

    # Add preservation column to sync_transactions if absent
    txn_cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_transactions)").fetchall()}
    if "preservation" not in txn_cols:
        conn.execute(
            "ALTER TABLE sync_transactions ADD COLUMN preservation INTEGER NOT NULL DEFAULT 0"
        )

    # Add user_key / user_display / owner_user_id to sync_transactions
    for col_ddl in [
        "user_key  TEXT",
        "user_display TEXT",
        "owner_user_id TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE sync_transactions ADD COLUMN {col_ddl}")
        except sqlite3.OperationalError:
            pass

    # Replace outbound unique index: one active outbound per (device, title, OmniSave user).
    # owner_user_id is the OmniSave account; user_key is source Nintendo account (provenance only).
    try:
        conn.execute("DROP INDEX IF EXISTS uniq_active_outbound_per_device_title")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_outbound_per_device_title "
            "ON sync_transactions(target_device_id, title_id, COALESCE(owner_user_id,'')) "
            "WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE'"
        )
    except sqlite3.OperationalError:  # pragma: no cover
        pass

    # Migrate old labels schema (namespace PK) → new schema (entity_type PK)
    if "labels" in existing:
        label_cols = {r[1] for r in conn.execute("PRAGMA table_info(labels)").fetchall()}
        if "namespace" in label_cols and "entity_type" not in label_cols:
            conn.execute("""
                CREATE TABLE labels_new (
                    entity_type TEXT NOT NULL CHECK(entity_type IN ('game')),
                    entity_id   TEXT NOT NULL,
                    label       TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id)
                )
            """)
            conn.execute("""
                INSERT INTO labels_new(entity_type, entity_id, label)
                SELECT namespace, entity_id, label FROM labels WHERE namespace='game'
            """)
            conn.execute("DROP TABLE labels")
            conn.execute("ALTER TABLE labels_new RENAME TO labels")

    # Create auth_users table if absent (new installs get it from SCHEMA; existing get it here)
    if "auth_users" not in existing:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users ("
            "  username TEXT PRIMARY KEY,"
            "  password_hash TEXT NOT NULL,"
            "  session_token TEXT,"
            "  created_at TEXT NOT NULL"
            ")"
        )

    # Create device_auth table if absent
    if "device_auth" not in existing:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS device_auth ("
            "  device_id TEXT PRIMARY KEY,"
            "  device_token TEXT UNIQUE NOT NULL,"
            "  user_id TEXT NOT NULL,"
            "  created_at TEXT NOT NULL,"
            "  last_seen TEXT,"
            "  config_pending INTEGER NOT NULL DEFAULT 0"
            ")"
        )
    else:
        # Add config_pending column to existing device_auth tables
        try:
            conn.execute(
                "ALTER TABLE device_auth ADD COLUMN config_pending INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass

    # Migrate device_profile_map to 3-col PK (device_id, profile_id, user_id) +
    # UNIQUE(device_id, user_id) — one device profile per OmniSave user per device,
    # but the same device profile may be claimed by multiple OmniSave users.

    # Crash-recovery: if a prior migration crashed after DROP TABLE device_profile_map but
    # before the RENAME, device_profile_map_new is the only surviving copy — promote it.
    # Must run BEFORE the "create if absent" block below so it doesn't create a fresh empty table.
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_profile_map_new'"
        ).fetchone()
        and "device_profile_map" not in existing
    ):
        conn.execute("ALTER TABLE device_profile_map_new RENAME TO device_profile_map")

    # Create device_profile_map if absent
    if (
        "device_profile_map" not in existing
        and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_profile_map'"
        ).fetchone()
        is None
    ):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS device_profile_map ("
            "  device_id TEXT NOT NULL,"
            "  profile_id TEXT NOT NULL,"
            "  user_id TEXT NOT NULL,"
            "  profile_name TEXT NOT NULL DEFAULT '',"
            "  created_at TEXT NOT NULL,"
            "  PRIMARY KEY (device_id, profile_id, user_id),"
            "  UNIQUE (device_id, user_id)"
            ")"
        )

    tbl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='device_profile_map'"
    ).fetchone()
    needs_migration = tbl and (
        "PRIMARY KEY (device_id, profile_id)" in tbl["sql"]
        or "PRIMARY KEY (device_id, profile_id, user_id)" not in tbl["sql"]
    )
    if needs_migration:
        # Single atomic transaction: DELETE + schema rebuild commit together or not at all.
        # needs_migration re-evaluates on every boot and DROP TABLE IF EXISTS
        # device_profile_map_new handle a partial prior run as belt-and-suspenders.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM device_profile_map WHERE rowid NOT IN ("
            "  SELECT MIN(rowid) FROM device_profile_map GROUP BY device_id, user_id"
            ")"
        )
        dup_count = conn.execute("SELECT changes()").fetchone()[0]
        conn.execute("DROP TABLE IF EXISTS device_profile_map_new")
        conn.execute("""
            CREATE TABLE device_profile_map_new (
                device_id    TEXT NOT NULL,
                profile_id   TEXT NOT NULL,
                user_id      TEXT NOT NULL,
                profile_name TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                PRIMARY KEY (device_id, profile_id, user_id),
                UNIQUE (device_id, user_id)
            )
        """)
        conn.execute("INSERT INTO device_profile_map_new SELECT * FROM device_profile_map")
        conn.execute("DROP TABLE device_profile_map")
        conn.execute("ALTER TABLE device_profile_map_new RENAME TO device_profile_map")
        conn.execute("COMMIT")
        if dup_count:
            log.info(
                "device_profile_map migration: dropped %d duplicate claim(s)"
                " (kept oldest per device+user)",
                dup_count,
            )

    # Create device_known_profiles if absent
    if "device_known_profiles" not in existing:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS device_known_profiles ("
            "  device_id TEXT NOT NULL,"
            "  profile_id TEXT NOT NULL,"
            "  profile_name TEXT NOT NULL DEFAULT '',"
            "  last_seen TEXT NOT NULL,"
            "  PRIMARY KEY (device_id, profile_id)"
            ")"
        )

    # Add client_type to devices (new installs have it via SCHEMA)
    if "devices" in existing:
        dev_cols = {r[1] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "client_type" not in dev_cols:
            conn.execute("ALTER TABLE devices ADD COLUMN client_type TEXT NOT NULL DEFAULT ''")
        # Backfill client_type for existing Switch devices that haven't reconnected yet.
        conn.execute(
            "UPDATE devices SET client_type='switch'"
            " WHERE client_type='' AND device_id NOT LIKE 'romm:%' AND hardware_type!='romm-vsc'"
        )

    # Add owner_user_id to events (new installs have it via SCHEMA)
    if "events" in existing:
        evt_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "owner_user_id" not in evt_cols:
            conn.execute("ALTER TABLE events ADD COLUMN owner_user_id TEXT")

    # Ownership indexes on sync_transactions and events (idempotent)
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_sync_owner ON sync_transactions(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sync_owner_title ON sync_transactions(owner_user_id, title_id)",
        "CREATE INDEX IF NOT EXISTS idx_sync_owner_created ON sync_transactions(owner_user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_user_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_sync_inbound_profile"
        " ON sync_transactions(source_device_id, title_id, direction, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_dpm_user ON device_profile_map (user_id)",
    ]:
        try:
            conn.execute(idx_sql)
        except sqlite3.OperationalError:  # pragma: no cover
            pass

    # Create user_config table if absent (new installs get it from SCHEMA)
    if "user_config" not in existing:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_config ("
            "  username TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            "  PRIMARY KEY (username, key)"
            ")"
        )

    # Hard-reset romm tables that lack the username column (pre-release; no data to preserve)
    _ROMM_TABLE_DDL = {
        "romm_title_map": (
            "CREATE TABLE romm_title_map ("
            "  username TEXT NOT NULL, title_id TEXT NOT NULL,"
            "  rom_id INTEGER NOT NULL, mapped_at TEXT,"
            "  PRIMARY KEY (username, title_id)"
            ")"
        ),
        "romm_game_cache": (
            "CREATE TABLE romm_game_cache ("
            "  username TEXT NOT NULL, rom_id INTEGER NOT NULL,"
            "  name TEXT, icon_url TEXT, fetched_at TEXT NOT NULL,"
            "  PRIMARY KEY (username, rom_id)"
            ")"
        ),
        "romm_save_sync": (
            "CREATE TABLE romm_save_sync ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,"
            "  rom_id INTEGER NOT NULL, romm_save_id INTEGER NOT NULL,"
            "  direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),"
            "  transaction_id TEXT, synced_at TEXT NOT NULL,"
            "  UNIQUE(username, rom_id, romm_save_id, direction)"
            ")"
        ),
    }
    for tbl, ddl in _ROMM_TABLE_DDL.items():
        if tbl in existing:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "username" not in cols:
                conn.execute(f"DROP TABLE {tbl}")
                conn.execute(ddl)

    # Add owner_user_id to devices (new installs have it via SCHEMA)
    if "devices" in existing:
        dev_cols = {r[1] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "owner_user_id" not in dev_cols:
            conn.execute("ALTER TABLE devices ADD COLUMN owner_user_id TEXT")
            if "device_auth" in existing:
                conn.execute(
                    "UPDATE devices SET owner_user_id = ("
                    "  SELECT user_id FROM device_auth WHERE device_id = devices.device_id"
                    ") WHERE owner_user_id IS NULL"
                )

    # Create device ownership tables if absent
    for tbl_name, tbl_sql in [
        (
            "device_pairing_codes",
            "CREATE TABLE IF NOT EXISTS device_pairing_codes ("
            "  code TEXT PRIMARY KEY, device_id TEXT NOT NULL,"
            "  expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0"
            ")",
        ),
        (
            "device_share_codes",
            "CREATE TABLE IF NOT EXISTS device_share_codes ("
            "  code TEXT PRIMARY KEY, device_id TEXT NOT NULL,"
            "  granted_by TEXT NOT NULL, expires_at TEXT NOT NULL,"
            "  used INTEGER NOT NULL DEFAULT 0"
            ")",
        ),
        (
            "device_access",
            "CREATE TABLE IF NOT EXISTS device_access ("
            "  device_id TEXT NOT NULL, user_id TEXT NOT NULL,"
            "  granted_by TEXT NOT NULL, created_at TEXT NOT NULL,"
            "  PRIMARY KEY (device_id, user_id)"
            ")",
        ),
    ]:
        if tbl_name not in existing:
            conn.execute(tbl_sql)

    # Add deleted_at to devices for soft-delete (preserve display_name after removal).
    # Guard with `if cols`: PRAGMA returns empty on a non-existent table, and the ALTER
    # would fail. Fresh DBs get deleted_at from SCHEMA directly.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
    if cols and "deleted_at" not in cols:
        conn.execute("ALTER TABLE devices ADD COLUMN deleted_at TEXT")
    if cols and "default_profile_uid" not in cols:
        conn.execute("ALTER TABLE devices ADD COLUMN default_profile_uid TEXT")

    da_cols = {row[1] for row in conn.execute("PRAGMA table_info(device_access)").fetchall()}
    if da_cols and "default_profile_uid" not in da_cols:
        conn.execute("ALTER TABLE device_access ADD COLUMN default_profile_uid TEXT")

    txn_cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_transactions)").fetchall()}
    if txn_cols and "target_profile_uid" not in txn_cols:
        conn.execute("ALTER TABLE sync_transactions ADD COLUMN target_profile_uid TEXT")

    # Backfill device_title_head for source devices from their uploaded inbounds.
    # Idempotent: MAX(last_seq, excluded.last_seq) ensures we only ever advance the pointer.
    # Fixes devices processed before per-device head tracking was introduced.
    # Guard: device_title_head may not exist on very old schemas (SCHEMA creates it).
    dth_tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='device_title_head'"
        ).fetchall()
    }
    if dth_tables:
        conn.execute("""
            INSERT INTO device_title_head (title_id, device_id, last_seq, updated_at)
            SELECT title_id, source_device_id, MAX(snapshot_sequence),
                   strftime('%Y-%m-%dT%H:%M:%SZ','now')
            FROM sync_transactions
            WHERE direction='inbound' AND preservation=0
              AND snapshot_sequence IS NOT NULL
              AND state IN ('READY_FOR_RESTORE','COMPLETED','SUPERSEDED')
            GROUP BY title_id, source_device_id
            ON CONFLICT(title_id, device_id) DO UPDATE SET
                last_seq = MAX(last_seq, excluded.last_seq),
                updated_at = excluded.updated_at
        """)

    # Rename legacy romm-vsc device_id to the configured source_id (default romm:main).
    # Guard: server_config may not exist on very old schemas being migrated.
    sc_tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='server_config'"
        ).fetchall()
    }
    if sc_tables:
        stored_romm_id = (
            conn.execute("SELECT value FROM server_config WHERE key='romm_source_id'").fetchone()
            or [None]
        )[0] or "romm:main"
        conn.execute(
            "UPDATE sync_transactions SET source_device_id=? WHERE source_device_id='romm-vsc'",
            (stored_romm_id,),
        )
        conn.execute(
            "UPDATE sync_transactions SET target_device_id=? WHERE target_device_id='romm-vsc'",
            (stored_romm_id,),
        )
        # device_installed_games and devices rows for romm-vsc will be rebuilt on startup.
        conn.execute("DELETE FROM device_installed_games WHERE device_id='romm-vsc'")
        conn.execute("DELETE FROM devices WHERE device_id='romm-vsc'")

    # Multi-session auth: create auth_sessions and migrate existing single tokens
    if "auth_sessions" not in existing:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_sessions ("
            "  session_id TEXT PRIMARY KEY,"
            "  username TEXT NOT NULL,"
            "  token TEXT UNIQUE NOT NULL,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT OR IGNORE INTO auth_sessions (session_id, username, token, created_at)"
            " SELECT lower(hex(randomblob(16))), username, session_token, created_at"
            " FROM auth_users WHERE session_token IS NOT NULL AND session_token != ''"
        )

    # Enforce one title_id per rom_id per user in romm_title_map.
    # The indexer's Pass 2 (name-search) could map a second title_id to an already-mapped
    # rom_id, producing duplicate catalog entries.  Deduplicate first (keep lowest rowid =
    # the older/file-matched entry), then add the unique index to prevent recurrence.
    if "romm_title_map" in existing:
        conn.execute(
            "DELETE FROM romm_title_map WHERE rowid NOT IN"
            " (SELECT MIN(rowid) FROM romm_title_map GROUP BY username, rom_id)"
        )
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uniq_romm_title_map_rom"
                " ON romm_title_map(username, rom_id)"
            )
        except sqlite3.OperationalError:  # pragma: no cover
            pass


class LockedConnection:
    """Thread-safe proxy around sqlite3.Connection.

    Serialises every Python-level operation with an RLock so multiple threads
    can safely share one connection object.  SQLite's own WAL locking handles
    DB-level write serialisation; this prevents corruption of the pysqlite
    C-struct when GIL is released during disk I/O.

    Exposes .path so background workers can open their own connections to the
    same file rather than sharing this one.
    """

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self.path = path

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def execute(self, sql: str, parameters=()):
        with self._lock:
            return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, data):
        with self._lock:
            return self._conn.executemany(sql, data)

    def executescript(self, sql: str):
        with self._lock:
            return self._conn.executescript(sql)

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def close(self):
        with self._lock:
            return self._conn.close()


def open_db(path: Path) -> LockedConnection:
    if not isinstance(path, Path):
        raise TypeError(f"open_db requires a Path, got {type(path).__name__}: {path!r}")
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # autocommit; use explicit BEGIN IMMEDIATE for atomic blocks
    conn.executescript(SCHEMA)
    _apply_migrations(conn)
    return LockedConnection(conn, path)


# ── Devices ───────────────────────────────────────────────────────────────────


def normalize_device_id(device_id: str) -> str:
    """Strip colons/dashes and uppercase — ensures e.g. '98:41:5C:0F:01:23' == '98415C0F0123'."""
    return device_id.replace(":", "").replace("-", "").upper()


def get_device(conn, device_id: str) -> dict | None:
    _SEL = (
        "SELECT device_id, display_name, hardware_type, client_type, last_seen, created_at,"
        " owner_user_id, default_profile_uid FROM devices WHERE device_id=?"
    )
    # Virtual devices (romm:*) are stored with their raw ID; physical devices are normalized.
    row = conn.execute(_SEL, (device_id,)).fetchone()
    if not row:
        row = conn.execute(_SEL, (normalize_device_id(device_id),)).fetchone()
    return dict(row) if row else None


def get_device_default_profile(conn, device_id: str) -> str | None:
    row = conn.execute(
        "SELECT default_profile_uid FROM devices WHERE device_id=?",
        (normalize_device_id(device_id),),
    ).fetchone()
    return row["default_profile_uid"] if row else None


def get_last_inbound_user_key(
    conn, device_id: str, title_id: str, owner_user_id: str | None = None
) -> str | None:
    """Heuristic cache: Nintendo account UID last used to play title_id on device.

    With owner_user_id: scopes to that OmniSave user's uploads — prevents cross-user profile
    assignment in fanout and push where user context is known.
    Without (None/""): pure (device, title) resolver — used in backfill where the inbound row
    carries no OmniSave user context; safe because query targets the destination device's own
    upload history, not source-side data.
    Returns None when no prior upload exists; callers must chain to device default."""
    if owner_user_id:
        row = conn.execute(
            "SELECT user_key FROM sync_transactions"
            " WHERE source_device_id=? AND title_id=? AND owner_user_id=?"
            " AND direction='inbound' AND state != 'FAILED'"
            " AND user_key IS NOT NULL AND user_key != ''"
            " ORDER BY created_at DESC, transaction_id DESC LIMIT 1",
            (normalize_device_id(device_id), title_id, owner_user_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT user_key FROM sync_transactions"
            " WHERE source_device_id=? AND title_id=?"
            " AND direction='inbound' AND state != 'FAILED'"
            " AND user_key IS NOT NULL AND user_key != ''"
            " ORDER BY created_at DESC, transaction_id DESC LIMIT 1",
            (normalize_device_id(device_id), title_id),
        ).fetchone()
    return row["user_key"] if row else None


def get_user_device_default_profile(conn, device_id: str, user_id: str) -> str | None:
    """Return the default profile for a specific user on a device.

    Owner → devices.default_profile_uid; shared user → device_access.default_profile_uid.
    """
    device_id = normalize_device_id(device_id)
    row = conn.execute(
        "SELECT default_profile_uid FROM devices WHERE device_id=? AND owner_user_id=?",
        (device_id, user_id),
    ).fetchone()
    if row is not None:
        return row["default_profile_uid"]
    row = conn.execute(
        "SELECT default_profile_uid FROM device_access WHERE device_id=? AND user_id=?",
        (device_id, user_id),
    ).fetchone()
    return row["default_profile_uid"] if row else None


def set_device_default_profile(conn, device_id: str, profile_uid: str | None) -> None:
    conn.execute(
        "UPDATE devices SET default_profile_uid=? WHERE device_id=?",
        (profile_uid or None, normalize_device_id(device_id)),
    )


def set_user_device_default_profile(
    conn, device_id: str, user_id: str, profile_uid: str | None
) -> None:
    """Set per-user default profile. Owner writes to devices; shared user writes to device_access."""
    device_id = normalize_device_id(device_id)
    n = conn.execute(
        "UPDATE devices SET default_profile_uid=? WHERE device_id=? AND owner_user_id=?",
        (profile_uid or None, device_id, user_id),
    ).rowcount
    if n == 0:
        conn.execute(
            "UPDATE device_access SET default_profile_uid=? WHERE device_id=? AND user_id=?",
            (profile_uid or None, device_id, user_id),
        )


def get_profile_display_name(conn, device_id: str, profile_id: str) -> str | None:
    """Resolve a profile UID to a display name for a device.

    Checks device_known_profiles first (has last_seen telemetry), then falls
    back to device_profile_map (claimed profiles that may not have re-synced).
    """
    row = conn.execute(
        "SELECT COALESCE(m.profile_name, k.profile_name) AS name"
        " FROM device_known_profiles k"
        " LEFT JOIN device_profile_map m"
        "   ON m.device_id=k.device_id AND m.profile_id=k.profile_id"
        " WHERE k.device_id=? AND k.profile_id=?",
        (device_id, profile_id),
    ).fetchone()
    if row:
        return row["name"] or None
    row = conn.execute(
        "SELECT profile_name FROM device_profile_map WHERE device_id=? AND profile_id=?",
        (device_id, profile_id),
    ).fetchone()
    return (row["profile_name"] or None) if row else None


def upsert_device(conn, device_id: str, hardware_type: str = "", client_type: str = "") -> None:
    device_id = normalize_device_id(device_id)
    now = _now()
    conn.execute(
        "INSERT INTO devices (device_id,hardware_type,client_type,last_seen,created_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(device_id) DO UPDATE SET"
        "   hardware_type=excluded.hardware_type,"
        "   client_type=CASE WHEN excluded.client_type!='' THEN excluded.client_type"
        "                    ELSE devices.client_type END,"
        "   last_seen=excluded.last_seen",
        (device_id, hardware_type, client_type, now, now),
    )


def touch_device(conn, device_id: str, owner_user_id: str) -> None:
    """Refresh last_seen for a virtual device. Idempotent: safe to call multiple times per cycle."""
    conn.execute(
        "UPDATE devices SET last_seen=? WHERE device_id=? AND owner_user_id=?",
        (_now(), device_id, owner_user_id),
    )


def soft_delete_device(conn, device_id: str) -> None:
    conn.execute(
        "UPDATE devices SET deleted_at=? WHERE device_id=?",
        (_now(), device_id),
    )


def get_all_devices(conn) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM devices ORDER BY last_seen DESC")]


def rename_device(conn, device_id: str, display_name: str) -> None:
    conn.execute("UPDATE devices SET display_name=? WHERE device_id=?", (display_name, device_id))


# ── Inbound transaction creation ──────────────────────────────────────────────


def create_inbound_transaction(
    conn,
    device_id: str,
    title_id: str,
    total_size_bytes: int,
    parent_sequence_num: int | None,
    preservation: bool = False,
    user_key: str = "",
    user_display: str = "",
    owner_user_id: str | None = None,
) -> tuple[str, str]:
    """Create UPLOADING inbound transaction + upload session. Returns (transaction_id, session_id)."""
    device_id = normalize_device_id(device_id)
    now = _now()
    txn_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,parent_sequence_num,"
        "preservation,total_size_bytes,user_key,user_display,owner_user_id,created_at,updated_at) "
        "VALUES (?,?,?,'inbound','UPLOADING',?,?,?,?,?,?,?,?)",
        (
            txn_id,
            title_id.upper(),
            device_id,
            parent_sequence_num,
            int(preservation),
            total_size_bytes,
            user_key or None,
            user_display or None,
            owner_user_id or None,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO upload_sessions "
        "(session_id,transaction_id,total_size_bytes,chunk_size_bytes,expected_total_chunks,last_active_at) "
        "VALUES (?,?,?,0,0,?)",
        (session_id, txn_id, total_size_bytes, now),
    )
    return txn_id, session_id


def find_uploading_inbound(
    conn,
    device_id: str,
    title_id: str,
    parent_sequence_num: int | None,
    user_key: str,
    total_size_bytes: int,
) -> tuple[str, str] | None:
    """Return (transaction_id, session_id) if an UPLOADING inbound already exists for this slot.

    Slot = (device, title, parent_seq, user_key, total_size). total_size is included so that
    a retry with different bytes (save changed) gets a fresh session, not the old one.
    parent_sequence_num is read-only here — the server assigns the real sequence in PROCESSING.
    """
    row = conn.execute(
        "SELECT st.transaction_id, us.session_id "
        "FROM sync_transactions st "
        "JOIN upload_sessions us ON us.transaction_id = st.transaction_id "
        "WHERE st.source_device_id=? AND st.title_id=? AND st.direction='inbound' "
        "AND st.state='UPLOADING' "
        "AND COALESCE(st.parent_sequence_num,-1)=COALESCE(?,-1) "
        "AND COALESCE(st.user_key,'')=COALESCE(?,'') "
        "AND st.total_size_bytes=?",
        (device_id, title_id.upper(), parent_sequence_num, user_key or "", total_size_bytes),
    ).fetchone()
    return (row["transaction_id"], row["session_id"]) if row else None


def get_session(conn, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM upload_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_transaction(conn, txn_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    return dict(row) if row else None


def set_session_manifest(conn, session_id: str, ledger_json: str) -> None:
    """Freeze checkpoint_ledger on session. Must be called once before upload begins."""
    conn.execute(
        "UPDATE upload_sessions SET checkpoint_ledger=?,last_active_at=? WHERE session_id=?",
        (ledger_json, _now(), session_id),
    )


def advance_server_verified(conn, session_id: str, new_verified: int) -> None:
    conn.execute(
        "UPDATE upload_sessions SET server_verified_bytes=?,last_active_at=? WHERE session_id=?",
        (new_verified, _now(), session_id),
    )


def set_transaction_ledger(conn, transaction_id: str, ledger_json: str) -> None:
    """Store checkpoint_ledger on transaction after assembly (used for outbound delivery)."""
    conn.execute(
        "UPDATE sync_transactions SET checkpoint_ledger=?,updated_at=? WHERE transaction_id=?",
        (ledger_json, _now(), transaction_id),
    )


def transition_to_processing(conn, session_id: str) -> str | None:
    """
    Completeness gate (server_verified_bytes == total_size_bytes) + state transition to PROCESSING.
    Returns transaction_id on success, None if gate fails or wrong state.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        sess = conn.execute(
            "SELECT * FROM upload_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not sess or sess["session_state"] != "ACTIVE":
            conn.execute("ROLLBACK")
            return None
        txn = conn.execute(
            "SELECT * FROM sync_transactions WHERE transaction_id=?",
            (sess["transaction_id"],),
        ).fetchone()
        if not txn or txn["state"] != "UPLOADING":
            conn.execute("ROLLBACK")
            return None
        if sess["server_verified_bytes"] != sess["total_size_bytes"]:
            conn.execute("ROLLBACK")
            return None
        now = _now()
        conn.execute(
            "UPDATE sync_transactions SET state='PROCESSING',updated_at=? WHERE transaction_id=?",
            (now, sess["transaction_id"]),
        )
        conn.execute(
            "UPDATE upload_sessions SET session_state='COMPLETED' WHERE session_id=?",
            (session_id,),
        )
        conn.execute("COMMIT")
        return sess["transaction_id"]
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── Snapshot sequencing & conflict ────────────────────────────────────────────


def get_head_sequence(conn, title_id: str) -> int | None:
    """Highest snapshot_sequence of committed non-preservation inbound tx for this title."""
    row = conn.execute(
        "SELECT MAX(snapshot_sequence) FROM sync_transactions "
        "WHERE title_id=? AND direction='inbound' AND has_conflict=0 AND preservation=0 "
        "AND state IN ('READY_FOR_RESTORE','COMPLETED')",
        (title_id.upper(),),
    ).fetchone()
    return row[0]


def save_already_committed(conn, title_id: str, sha256: str) -> bool:
    """True if any non-preservation committed inbound for this title already has this sha256."""
    row = conn.execute(
        "SELECT 1 FROM sync_transactions "
        "WHERE title_id=? AND direction='inbound' AND has_conflict=0 AND preservation=0 "
        "AND state IN ('READY_FOR_RESTORE','COMPLETED') "
        "AND sha256=? LIMIT 1",
        (title_id.upper(), sha256),
    ).fetchone()
    return row is not None


def next_global_sequence(conn, title_id: str) -> int:
    """Atomically increment and return the global per-title snapshot counter.

    Always returns MAX(counter, actual_max_in_db) + 1 to guard against counter
    drift caused by data repairs or manual sequence reassignments."""
    tid = title_id.upper()
    conn.execute(
        "INSERT INTO snapshot_counters (title_id, counter) VALUES (?, 0) "
        "ON CONFLICT(title_id) DO NOTHING",
        (tid,),
    )
    conn.execute(
        "UPDATE snapshot_counters "
        "SET counter = MAX(counter, "
        "    (SELECT COALESCE(MAX(snapshot_sequence), 0) "
        "     FROM sync_transactions WHERE title_id=?)"
        ") + 1 "
        "WHERE title_id=?",
        (tid, tid),
    )
    return conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (tid,)
    ).fetchone()["counter"]


def upsert_device_title_head(conn, title_id: str, device_id: str, seq: int) -> None:
    """Record the last global sequence a device has seen for a title.
    Updated on: (1) device ACKs delivery, (2) device's own upload finalizes as HEAD."""
    conn.execute(
        "INSERT INTO device_title_head (title_id,device_id,last_seq,updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(title_id,device_id) DO UPDATE SET"
        " last_seq=CASE WHEN excluded.last_seq > device_title_head.last_seq"
        "   THEN excluded.last_seq ELSE device_title_head.last_seq END,"
        " updated_at=CASE WHEN excluded.last_seq > device_title_head.last_seq"
        "   THEN excluded.updated_at ELSE device_title_head.updated_at END",
        (title_id.upper(), device_id, seq, _now()),
    )


def get_device_last_seq(conn, title_id: str, device_id: str) -> int | None:
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (title_id.upper(), device_id),
    ).fetchone()
    return row["last_seq"] if row else None


def finalize_inbound(
    conn,
    transaction_id: str,
    sha256: str,
    snapshot_path: str,
    snapshot_sequence: int,
    has_conflict: bool,
) -> None:
    # State + content fields: always update unconditionally.
    conn.execute(
        "UPDATE sync_transactions "
        "SET state='READY_FOR_RESTORE',sha256=?,snapshot_path=?,has_conflict=?,updated_at=? "
        "WHERE transaction_id=?",
        (sha256, snapshot_path, int(has_conflict), _now(), transaction_id),
    )
    # Sequence: immutable once written.  Using IS NULL guard matches the commit
    # endpoint and prevents a concurrent worker's finalize from stomping a seq
    # that was already committed by a prior finalize for the same transaction.
    conn.execute(
        "UPDATE sync_transactions SET snapshot_sequence=? "
        "WHERE transaction_id=? AND snapshot_sequence IS NULL",
        (snapshot_sequence, transaction_id),
    )


def fail_transaction(conn, transaction_id: str) -> None:
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED',updated_at=? "
        "WHERE transaction_id=? "
        "AND state NOT IN ('READY_FOR_RESTORE','COMPLETED','DEDUPED','SUPERSEDED')",
        (_now(), transaction_id),
    )


def complete_dedup_transaction(conn, transaction_id: str) -> None:
    """Mark a duplicate (unchanged-content) inbound transaction DEDUPED with no sequence."""
    conn.execute(
        "UPDATE sync_transactions SET state='DEDUPED',updated_at=? WHERE transaction_id=?",
        (_now(), transaction_id),
    )


# ── Outbound / delivery ───────────────────────────────────────────────────────


def get_title_peer_devices(conn, title_id: str, exclude_device_id: str) -> list[str]:
    """All devices that have any committed inbound for this title, excluding source."""
    exclude_device_id = normalize_device_id(exclude_device_id)
    rows = conn.execute(
        "SELECT DISTINCT source_device_id FROM sync_transactions "
        "WHERE title_id=? AND direction='inbound' "
        "AND state IN ('READY_FOR_RESTORE','COMPLETED','DEDUPED') "
        "AND source_device_id != ?",
        (title_id.upper(), exclude_device_id),
    ).fetchall()
    return [r["source_device_id"] for r in rows]


def get_active_outbound_for_snapshot(
    conn, snapshot_sequence: int, title_id: str, target_device_id: str
) -> dict | None:
    return conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=? "
        "AND snapshot_sequence=? AND state='READY_FOR_RESTORE'",
        (target_device_id, title_id.upper(), snapshot_sequence),
    ).fetchone()


def supersede_active_outbound(
    conn, target_device_id: str, title_id: str, owner_user_id: str = ""
) -> None:
    """Mark SUPERSEDED all READY_FOR_RESTORE outbounds for (device, title, owner_user_id).

    owner_user_id is the OmniSave account — the identity boundary. user_key (Nintendo account
    on source device) is provenance only and must NOT affect superseding.
    Different owner_user_id values are never affected.
    """
    conn.execute(
        "UPDATE sync_transactions SET state='SUPERSEDED',updated_at=? "
        "WHERE target_device_id=? AND title_id=? AND direction='outbound' "
        "AND state='READY_FOR_RESTORE' AND COALESCE(owner_user_id,'')=?",
        (_now(), target_device_id, title_id.upper(), owner_user_id or ""),
    )


def create_outbound_transaction(
    conn,
    source_txn_id: str,
    target_device_id: str,
    target_profile_uid: str | None = None,
) -> str | None:
    """Fork a READY_FOR_RESTORE outbound transaction for target device from a committed inbound.

    target_profile_uid: restore destination profile on the target device. Caller is responsible
    for resolving this (device default or explicit override). Stored as-is; never rewritten.
    user_key (source account) is copied from the inbound for audit purposes only.

    Returns outbound transaction_id, or None if INSERT OR IGNORE suppressed a duplicate
    (enforced by uniq_active_outbound_per_device_title index on (device, title, owner_user_id)).
    """
    src = conn.execute(
        "SELECT title_id,source_device_id,snapshot_sequence,sha256,snapshot_path,"
        "total_size_bytes,checkpoint_ledger,user_key,owner_user_id "
        "FROM sync_transactions WHERE transaction_id=?",
        (source_txn_id,),
    ).fetchone()
    if not src:
        raise ValueError(f"source transaction {source_txn_id} not found")
    now = _now()
    outbound_id = str(uuid.uuid4())
    cur = conn.execute(
        "INSERT OR IGNORE INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
        "target_device_id,sha256,snapshot_path,total_size_bytes,checkpoint_ledger,"
        "user_key,target_profile_uid,owner_user_id,created_at,updated_at) "
        "VALUES (?,?,?,'outbound','READY_FOR_RESTORE',?,?,?,?,?,?,?,?,?,?,?)",
        (
            outbound_id,
            src["title_id"],
            src["source_device_id"],
            src["snapshot_sequence"],
            target_device_id,
            src["sha256"],
            src["snapshot_path"],
            src["total_size_bytes"],
            src["checkpoint_ledger"],
            src["user_key"],
            target_profile_uid or None,
            src["owner_user_id"],
            now,
            now,
        ),
    )
    return outbound_id if cur.rowcount > 0 else None


def get_pending_outbound(conn, device_id: str) -> list:
    rows = conn.execute(
        "SELECT transaction_id,title_id,snapshot_sequence,total_size_bytes,"
        "checkpoint_ledger,COALESCE(user_key,'') AS user_key,"
        "COALESCE(target_profile_uid,'') AS target_profile_uid "
        "FROM sync_transactions "
        "WHERE target_device_id=? AND direction='outbound' AND state='READY_FOR_RESTORE'"
        " ORDER BY rowid ASC LIMIT 50",
        (device_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def complete_outbound(conn, device_id: str, transaction_id: str) -> bool:
    """ACK: READY_FOR_RESTORE → COMPLETED. Idempotent on already-COMPLETED."""
    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=? AND target_device_id=?",
        (transaction_id, device_id),
    ).fetchone()
    if not txn:
        return False
    if txn["state"] == "COMPLETED":
        return True
    if txn["state"] != "READY_FOR_RESTORE":
        return False
    conn.execute(
        "UPDATE sync_transactions SET state='COMPLETED',updated_at=? WHERE transaction_id=?",
        (_now(), transaction_id),
    )
    return True


def fail_outbound(conn, device_id: str, transaction_id: str) -> bool:
    """Permanent inject failure: READY_FOR_RESTORE → FAILED."""
    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=? AND target_device_id=?",
        (transaction_id, device_id),
    ).fetchone()
    if not txn or txn["state"] not in ("READY_FOR_RESTORE", "FAILED"):
        return False
    if txn["state"] == "FAILED":
        return True
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED',updated_at=? WHERE transaction_id=?",
        (_now(), transaction_id),
    )
    return True


def retry_outbound(conn, transaction_id: str) -> dict | None:
    """Reset a FAILED outbound back to READY_FOR_RESTORE (UI manual retry).
    Idempotent on already-READY_FOR_RESTORE. Returns None if another
    READY_FOR_RESTORE already exists for the same (title_id, target_device_id,
    user_key) — avoids uniq_active_outbound_per_device_title."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        txn = conn.execute(
            "SELECT * FROM sync_transactions WHERE transaction_id=? AND direction='outbound'",
            (transaction_id,),
        ).fetchone()
        if not txn or txn["state"] not in ("FAILED", "READY_FOR_RESTORE"):
            conn.execute("ROLLBACK")
            return None
        if txn["state"] == "FAILED":
            conflict = conn.execute(
                "SELECT 1 FROM sync_transactions"
                " WHERE target_device_id=? AND title_id=?"
                "   AND COALESCE(user_key,'')=COALESCE(?,'') AND direction='outbound'"
                "   AND state='READY_FOR_RESTORE' AND transaction_id!=?",
                (txn["target_device_id"], txn["title_id"], txn["user_key"], transaction_id),
            ).fetchone()
            if conflict:
                conn.execute("ROLLBACK")
                return None
        conn.execute(
            "UPDATE sync_transactions SET state='READY_FOR_RESTORE',updated_at=? "
            "WHERE transaction_id=?",
            (_now(), transaction_id),
        )
        conn.execute("COMMIT")
        return dict(txn)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def retry_all_failed_outbounds(conn, device_id: str) -> list:
    """Reset one FAILED outbound per (title_id, user_key) to READY_FOR_RESTORE.

    Picks the highest snapshot_sequence FAILED row per group so we never
    re-deliver an older save when a newer one also failed.  Skips titles
    where a COMPLETED outbound already exists at the same or higher sequence
    (ghost rows — a later delivery already succeeded).  Skips titles that
    already have a READY_FOR_RESTORE pending (prevents duplicate queuing).

    Returns list of dicts with txn_id and title_id for each row reset."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        candidates = conn.execute(
            "SELECT f.transaction_id AS txn_id, f.title_id"
            " FROM sync_transactions f"
            " WHERE f.target_device_id=? AND f.direction='outbound' AND f.state='FAILED'"
            # Only consider the highest-seq FAILED per (title, user_key) group
            "   AND NOT EXISTS ("
            "     SELECT 1 FROM sync_transactions f2"
            "     WHERE f2.target_device_id=f.target_device_id"
            "       AND f2.title_id=f.title_id"
            "       AND COALESCE(f2.user_key,'')=COALESCE(f.user_key,'')"
            "       AND f2.direction='outbound' AND f2.state='FAILED'"
            "       AND f2.snapshot_sequence > f.snapshot_sequence"
            "   )"
            # Skip if delivery is already pending
            "   AND NOT EXISTS ("
            "     SELECT 1 FROM sync_transactions a"
            "     WHERE a.target_device_id=f.target_device_id"
            "       AND a.title_id=f.title_id"
            "       AND COALESCE(a.user_key,'')=COALESCE(f.user_key,'')"
            "       AND a.direction='outbound' AND a.state='READY_FOR_RESTORE'"
            "   )"
            # Skip ghost failures — a newer (or same-seq) delivery already completed
            "   AND NOT EXISTS ("
            "     SELECT 1 FROM sync_transactions c"
            "     WHERE c.target_device_id=f.target_device_id"
            "       AND c.title_id=f.title_id"
            "       AND COALESCE(c.user_key,'')=COALESCE(f.user_key,'')"
            "       AND c.direction='outbound' AND c.state='COMPLETED'"
            "       AND c.snapshot_sequence >= f.snapshot_sequence"
            "   )"
            " GROUP BY f.title_id, COALESCE(f.user_key,'')",
            (device_id,),
        ).fetchall()
        retried = []
        for row in candidates:
            conn.execute(
                "UPDATE sync_transactions SET state='READY_FOR_RESTORE', updated_at=?"
                " WHERE transaction_id=?",
                (_now(), row["txn_id"]),
            )
            retried.append({"txn_id": row["txn_id"], "title_id": row["title_id"]})
        conn.execute("COMMIT")
        return retried
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel_outbound_for_title(conn, device_id: str, title_id: str) -> int:
    """Cancel READY_FOR_RESTORE outbound rows for a device+title. Returns count cancelled."""
    cur = conn.execute(
        "UPDATE sync_transactions SET state='CANCELLED', updated_at=? "
        "WHERE target_device_id=? AND title_id=? "
        "AND direction='outbound' AND state='READY_FOR_RESTORE'",
        (_now(), device_id, title_id.upper()),
    )
    return cur.rowcount


# ── Snapshot management ───────────────────────────────────────────────────────


def delete_snapshot(conn, transaction_id: str) -> str | None:
    """Mark an inbound READY_FOR_RESTORE snapshot as FAILED for deletion.

    Also FAILs any active outbound transactions that reference the same archive path.
    Returns the archive file path to delete, or None if not found/not deletable.
    """
    txn = conn.execute(
        "SELECT state, snapshot_path FROM sync_transactions "
        "WHERE transaction_id=? AND direction='inbound'",
        (transaction_id,),
    ).fetchone()
    _deletable = {"READY_FOR_RESTORE", "COMPLETED", "SUPERSEDED", "FAILED", "DEDUPED"}
    if not txn or txn["state"] not in _deletable:
        return None
    path = txn["snapshot_path"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        if path:
            conn.execute(
                "UPDATE sync_transactions SET state='FAILED',updated_at=? "
                "WHERE direction='outbound' AND snapshot_path=? "
                "AND state='READY_FOR_RESTORE'",
                (_now(), path),
            )
        conn.execute(
            "UPDATE sync_transactions SET state='FAILED',snapshot_path=NULL,updated_at=? "
            "WHERE transaction_id=?",
            (_now(), transaction_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    # Return path to delete (may be empty string if no archive — still success)
    return path if path else ""


# ── Auth / server config ──────────────────────────────────────────────────────


def get_config(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM server_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_config(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO server_config (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_user_config(conn, username: str, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM user_config WHERE username=? AND key=?", (username, key)
    ).fetchone()
    return row["value"] if row else None


def set_user_config(conn, username: str, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO user_config (username,key,value) VALUES (?,?,?)"
        " ON CONFLICT(username,key) DO UPDATE SET value=excluded.value",
        (username, key, value),
    )


def get_romm_users(conn) -> list[str]:
    """Usernames that have RomM explicitly enabled (romm_enabled = '1' in user_config)."""
    rows = conn.execute(
        "SELECT username FROM user_config WHERE key='romm_enabled' AND value='1'"
    ).fetchall()
    return [r[0] for r in rows]


# ── Events ────────────────────────────────────────────────────────────────────


def log_event(
    conn,
    event_type: str,
    message: str,
    *,
    title_id=None,
    device_id=None,
    transaction_id=None,
    owner_user_id=None,
) -> None:
    conn.execute(
        "INSERT INTO events (occurred_at,event_type,title_id,device_id,transaction_id,message,owner_user_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (_now(), event_type, title_id, device_id, transaction_id, message, owner_user_id),
    )
    conn.execute(
        "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 500)"
    )


# ── RomM title mapping ─────────────────────────────────────────────────────────


def get_romm_rom_id(conn, username: str, title_id: str) -> int | None:
    row = conn.execute(
        "SELECT rom_id FROM romm_title_map WHERE username=? AND title_id=?",
        (username, title_id.upper()),
    ).fetchone()
    return row["rom_id"] if row else None


def upsert_romm_title_map(conn, username: str, title_id: str, rom_id: int) -> None:
    conn.execute(
        "INSERT INTO romm_title_map(username,title_id,rom_id,mapped_at) VALUES (?,?,?,?) "
        "ON CONFLICT(username,title_id) DO UPDATE SET rom_id=excluded.rom_id, mapped_at=excluded.mapped_at",
        (username, title_id.upper(), rom_id, _now()),
    )


def delete_romm_title_map(conn, username: str, title_id: str) -> None:
    conn.execute(
        "DELETE FROM romm_title_map WHERE username=? AND title_id=?",
        (username, title_id.upper()),
    )


def delete_romm_title_map_by_rom_id(conn, username: str, rom_id: int) -> None:
    conn.execute(
        "DELETE FROM romm_title_map WHERE username=? AND rom_id=?",
        (username, rom_id),
    )


def get_romm_title_map(conn, username: str) -> list:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT title_id, rom_id, mapped_at, pull_initialized FROM romm_title_map"
            " WHERE username=? ORDER BY mapped_at DESC",
            (username,),
        ).fetchall()
    ]


def mark_romm_pull_initialized(conn, username: str, rom_id: int) -> None:
    conn.execute(
        "UPDATE romm_title_map SET pull_initialized=1 WHERE username=? AND rom_id=?",
        (username, rom_id),
    )


# ── RomM game cache ────────────────────────────────────────────────────────────


def get_romm_game_cache(conn, username: str, rom_id: int) -> dict | None:
    row = conn.execute(
        "SELECT rom_id, name, icon_url, fetched_at FROM romm_game_cache"
        " WHERE username=? AND rom_id=?",
        (username, rom_id),
    ).fetchone()
    return dict(row) if row else None


def get_all_romm_game_cache(conn, username: str) -> dict:
    return {
        r["rom_id"]: {"name": r["name"], "icon_url": r["icon_url"], "fetched_at": r["fetched_at"]}
        for r in conn.execute(
            "SELECT rom_id, name, icon_url, fetched_at FROM romm_game_cache WHERE username=?",
            (username,),
        ).fetchall()
    }


def upsert_romm_game_cache(
    conn, username: str, rom_id: int, name: str | None, icon_url: str | None
) -> None:
    if name and len(name) > 512:
        name = name[:512]
    if icon_url and len(icon_url) > 2048:
        icon_url = None
    conn.execute(
        "INSERT INTO romm_game_cache(username,rom_id,name,icon_url,fetched_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(username,rom_id) DO UPDATE SET name=excluded.name, icon_url=excluded.icon_url, "
        "fetched_at=excluded.fetched_at",
        (username, rom_id, name, icon_url, _now()),
    )


# ── Custom labels ──────────────────────────────────────────────────────────────


def get_label(conn, entity_type: str, entity_id: str) -> str | None:
    row = conn.execute(
        "SELECT label FROM labels WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    ).fetchone()
    return row["label"] if row else None


def set_label(conn, entity_type: str, entity_id: str, label: str) -> None:
    conn.execute(
        "INSERT INTO labels(entity_type,entity_id,label) VALUES (?,?,?) "
        "ON CONFLICT(entity_type,entity_id) DO UPDATE SET label=excluded.label",
        (entity_type, entity_id, label),
    )


def delete_label(conn, entity_type: str, entity_id: str) -> None:
    conn.execute(
        "DELETE FROM labels WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    )


# ── RomM save sync tracking ────────────────────────────────────────────────────


def has_romm_sync(conn, username: str, rom_id: int, romm_save_id: int, direction: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM romm_save_sync"
        " WHERE username=? AND rom_id=? AND romm_save_id=? AND direction=?",
        (username, rom_id, romm_save_id, direction),
    ).fetchone()
    return row is not None


def record_romm_sync(
    conn,
    username: str,
    rom_id: int,
    romm_save_id: int,
    direction: str,
    transaction_id: str | None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO romm_save_sync"
        "(username,rom_id,romm_save_id,direction,transaction_id,synced_at) "
        "VALUES(?,?,?,?,?,?)",
        (username, rom_id, romm_save_id, direction, transaction_id, _now()),
    )


def get_romm_undelivered_head_txns(conn, username: str, romm_device_id: str) -> list:
    """Return inbound HEAD transactions where all delivery attempts to romm_device_id failed.

    Retry-only: only fires when at least one FAILED outbound exists for this title+device.
    Never bootstraps on initial connection — new outbounds are created by processing fanout."""
    return conn.execute(
        "SELECT st.transaction_id, st.title_id, st.snapshot_sequence"
        " FROM sync_transactions st"
        " JOIN romm_title_map rtm ON rtm.title_id = st.title_id AND rtm.username = ?"
        " WHERE st.direction='inbound' AND st.state='READY_FOR_RESTORE' AND st.sha256 IS NOT NULL"
        "   AND COALESCE(st.owner_user_id,'') = ?"
        "   AND st.snapshot_sequence = ("
        "     SELECT MAX(s2.snapshot_sequence) FROM sync_transactions s2"
        "     WHERE s2.title_id = st.title_id AND s2.direction='inbound'"
        "       AND s2.state='READY_FOR_RESTORE'"
        "       AND COALESCE(s2.owner_user_id,'') = COALESCE(st.owner_user_id,'')"
        "   )"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM sync_transactions outb"
        "     WHERE outb.title_id = st.title_id"
        "       AND outb.target_device_id = ?"
        "       AND outb.direction = 'outbound'"
        "       AND outb.state IN ('READY_FOR_RESTORE','DELIVERING','COMPLETED')"
        "       AND outb.snapshot_sequence = st.snapshot_sequence"
        "   )"
        "   AND EXISTS ("
        "     SELECT 1 FROM sync_transactions failed"
        "     WHERE failed.title_id = st.title_id"
        "       AND failed.target_device_id = ?"
        "       AND failed.direction = 'outbound'"
        "       AND failed.state = 'FAILED'"
        "   )",
        (username, username, romm_device_id, romm_device_id),
    ).fetchall()


def supersede_failed_outbounds_for_uninstalled(conn) -> int:
    """Supersede FAILED outbounds where target device has no record of the title installed.

    Covers both Switch devices (catalog from sysmodule) and RomM virtual devices
    (synced from romm_title_map each worker cycle). Returns count of rows changed."""
    cur = conn.execute(
        "UPDATE sync_transactions SET state='SUPERSEDED', updated_at=?"
        " WHERE direction='outbound' AND state='FAILED'"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM device_installed_games dig"
        "     WHERE dig.device_id = sync_transactions.target_device_id"
        "       AND dig.title_id = sync_transactions.title_id"
        "   )",
        (_now(),),
    )
    return cur.rowcount


# ── Device backup state convergence (heartbeat generation) ────────────────────


def db_push_backup_update(conn, device_id: str, title_id: str, snapshot_sequence: int) -> int:
    """Record a committed snapshot as a new generation entry for this device.

    Returns the new generation number. Call inside the same transaction as seq assignment
    so the generation bump is atomic with the commit.
    """
    device_id = normalize_device_id(device_id)
    now = _now()
    gen = conn.execute(
        "SELECT COALESCE(MAX(generation),0)+1 FROM device_backup_updates WHERE device_id=?",
        (device_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO device_backup_updates(device_id,generation,title_id,snapshot_sequence,committed_at)"
        " VALUES(?,?,?,?,?)",
        (device_id, gen, title_id.upper(), snapshot_sequence, now),
    )
    return gen


def db_get_sync_generation(conn, device_id: str) -> int:
    """Return the highest generation number for this device (0 if none)."""
    device_id = normalize_device_id(device_id)
    return conn.execute(
        "SELECT COALESCE(MAX(generation),0) FROM device_backup_updates WHERE device_id=?",
        (device_id,),
    ).fetchone()[0]


def db_get_backup_updates_since(conn, device_id: str, since_gen: int) -> list:
    """Return the latest entry per title where the max generation for that title exceeds since_gen.

    Returns at most one row per title_id — the most recently committed snapshot for each title
    that has changed since since_gen. Titles with no entries newer than since_gen are omitted.
    """
    device_id = normalize_device_id(device_id)
    rows = conn.execute(
        "SELECT title_id, snapshot_sequence, committed_at "
        "FROM device_backup_updates "
        "WHERE device_id=? "
        "  AND generation = ("
        "    SELECT MAX(generation) FROM device_backup_updates b2 "
        "    WHERE b2.device_id=? AND b2.title_id=device_backup_updates.title_id"
        "  ) "
        "  AND generation > ? "
        "ORDER BY generation",
        (device_id, device_id, since_gen),
    ).fetchall()
    return [dict(r) for r in rows]


def create_processing_transaction(
    conn,
    device_id: str,
    title_id: str,
    total_size_bytes: int,
    parent_sequence_num: int | None,
    owner_user_id: str | None = None,
) -> tuple[str, str]:
    """Create transaction + session in PROCESSING/COMPLETED state, bypassing the upload protocol."""
    now = _now()
    txn_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,parent_sequence_num,"
        "total_size_bytes,owner_user_id,created_at,updated_at) "
        "VALUES (?,?,?,'inbound','PROCESSING',?,?,?,?,?)",
        (
            txn_id,
            title_id.upper(),
            device_id,
            parent_sequence_num,
            total_size_bytes,
            owner_user_id,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO upload_sessions "
        "(session_id,transaction_id,total_size_bytes,chunk_size_bytes,expected_total_chunks,"
        "server_verified_bytes,session_state,last_active_at) "
        "VALUES (?,?,?,0,0,?,'COMPLETED',?)",
        (session_id, txn_id, total_size_bytes, total_size_bytes, now),
    )
    return txn_id, session_id


# ── Login users (auth_users) ──────────────────────────────────────────────────


def create_auth_user(conn, username: str, password_hash: str) -> None:
    conn.execute(
        "INSERT INTO auth_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, _now()),
    )


def get_auth_user(conn, username: str) -> dict | None:
    row = conn.execute(
        "SELECT username, password_hash, session_token, created_at FROM auth_users WHERE username=?",
        (username,),
    ).fetchone()
    return dict(row) if row else None


def get_auth_user_by_token(conn, token: str) -> dict | None:
    row = conn.execute(
        "SELECT username FROM auth_sessions WHERE token=?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def insert_auth_session(conn, username: str, token: str) -> None:
    conn.execute(
        "INSERT INTO auth_sessions (session_id, username, token, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), username, token, _now()),
    )


def delete_auth_session_by_token(conn, token: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE token=?", (token,))


def delete_auth_sessions_for_user(conn, username: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE username=?", (username,))


def rename_auth_sessions_user(conn, old_username: str, new_username: str) -> None:
    conn.execute(
        "UPDATE auth_sessions SET username=? WHERE username=?",
        (new_username, old_username),
    )


def list_auth_users(conn) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT username, created_at FROM auth_users ORDER BY created_at ASC"
        ).fetchall()
    ]


def set_auth_user_session(conn, username: str, token: str | None) -> None:
    conn.execute(
        "UPDATE auth_users SET session_token=? WHERE username=?",
        (token, username),
    )


def delete_auth_user(conn, username: str) -> bool:
    conn.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
    n = conn.execute("DELETE FROM auth_users WHERE username=?", (username,)).rowcount
    return n > 0


def set_auth_user_password(conn, username: str, password_hash: str) -> None:
    conn.execute(
        "UPDATE auth_users SET password_hash=? WHERE username=?",
        (password_hash, username),
    )


def rename_auth_user(conn, old_username: str, new_username: str) -> None:
    """Rename a user across all ownership tables. Raises sqlite3.IntegrityError if
    new_username already exists. Atomic: all tables update or none do."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE auth_users SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE auth_sessions SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE user_config SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE devices SET owner_user_id=? WHERE owner_user_id=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE sync_transactions SET owner_user_id=? WHERE owner_user_id=?",
            (new_username, old_username),
        )
        conn.execute(
            "UPDATE events SET owner_user_id=? WHERE owner_user_id=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE device_auth SET user_id=? WHERE user_id=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE device_profile_map SET user_id=? WHERE user_id=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE romm_title_map SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE romm_game_cache SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute(
            "UPDATE romm_save_sync SET username=? WHERE username=?", (new_username, old_username)
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── Device auth ───────────────────────────────────────────────────────────────


def create_device_token(conn, device_id: str, user_id: str) -> str:
    """Generate sk_device_ token and insert row. Raises on duplicate device_id."""
    import secrets as _sec

    token = "sk_device_" + _sec.token_urlsafe(32)
    conn.execute(
        "INSERT INTO device_auth (device_id, device_token, user_id, created_at) VALUES (?,?,?,?)",
        (device_id, token, user_id, _now()),
    )
    return token


def rotate_device_token(conn, device_id: str) -> str:
    """Generate new token, update row. Raises if device_id not in device_auth."""
    import secrets as _sec

    token = "sk_device_" + _sec.token_urlsafe(32)
    n = conn.execute(
        "UPDATE device_auth SET device_token=? WHERE device_id=?",
        (token, device_id),
    ).rowcount
    if n == 0:
        raise KeyError(f"device_id not found: {device_id}")
    return token


def revoke_device_token(conn, device_id: str) -> None:
    conn.execute("DELETE FROM device_auth WHERE device_id=?", (device_id,))


def get_device_auth_by_token(conn, token: str) -> dict | None:
    row = conn.execute(
        "SELECT device_id, user_id, last_seen FROM device_auth WHERE device_token=?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def get_device_auth(conn, device_id: str) -> dict | None:
    row = conn.execute(
        "SELECT device_id, user_id, created_at, last_seen FROM device_auth WHERE device_id=?",
        (device_id,),
    ).fetchone()
    return dict(row) if row else None


def touch_device_last_seen(conn, device_id: str) -> None:
    """Update last_seen. Called ONLY after a valid authenticated sync. Never for anonymous."""
    conn.execute(
        "UPDATE device_auth SET last_seen=? WHERE device_id=?",
        (_now(), device_id),
    )


# ── Device auth config_pending ────────────────────────────────────────────────


def set_device_config_pending(conn, device_id: str) -> None:
    conn.execute("UPDATE device_auth SET config_pending=1 WHERE device_id=?", (device_id,))


def consume_pending_config(conn, device_id: str, device_last_seen: str | None) -> str | None:
    """Return device_token if config_pending=1 and device was seen within 15 minutes. Clears flag."""
    from datetime import UTC, datetime, timedelta

    if not device_last_seen:
        return None
    try:
        seen_dt = datetime.fromisoformat(device_last_seen.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datetime.now(UTC) - seen_dt > timedelta(minutes=15):
        return None
    row = conn.execute(
        "SELECT device_token FROM device_auth WHERE device_id=? AND config_pending=1",
        (device_id,),
    ).fetchone()
    if not row:
        return None
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (device_id,))
    return row["device_token"]


# ── Device profile mapping ────────────────────────────────────────────────────


def upsert_known_profile(conn, device_id: str, profile_id: str, profile_name: str) -> None:
    conn.execute(
        "INSERT INTO device_known_profiles (device_id, profile_id, profile_name, last_seen)"
        " VALUES (?,?,?,?) ON CONFLICT(device_id, profile_id)"
        " DO UPDATE SET profile_name=excluded.profile_name, last_seen=excluded.last_seen",
        (device_id, profile_id, profile_name, _now()),
    )
    # Auto-set first seen profile as the device default if none is set yet.
    conn.execute(
        "UPDATE devices SET default_profile_uid=? WHERE device_id=? AND default_profile_uid IS NULL",
        (profile_id, device_id),
    )


def upsert_device_profile(
    conn, device_id: str, profile_id: str, user_id: str, profile_name: str = ""
) -> None:
    """Claim a device profile for an OmniSave user.

    One OmniSave user claims exactly ONE device profile per device (UNIQUE device_id, user_id).
    Multiple OmniSave users may claim the same device profile (PK includes user_id).
    INSERT OR REPLACE atomically evicts any prior claim by the same user on this device.
    """
    conn.execute(
        "INSERT OR REPLACE INTO device_profile_map"
        " (device_id, profile_id, user_id, profile_name, created_at)"
        " VALUES (?,?,?,?,?)",
        (device_id, profile_id, user_id, profile_name, _now()),
    )


def get_profile_owner(conn, device_id: str, profile_id: str) -> str | None:
    """Return the oldest claimant for a profile, or None if unclaimed.

    ORDER BY created_at ASC makes the result deterministic when multiple OmniSave users
    share the same Nintendo profile (3-col PK allows this). The oldest claim is the
    authoritative owner for inbound transaction stamping.
    """
    row = conn.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?"
        " ORDER BY created_at ASC LIMIT 1",
        (device_id, profile_id),
    ).fetchone()
    return row["user_id"] if row else None


def get_device_owner(conn, device_id: str) -> str | None:
    row = conn.execute(
        "SELECT owner_user_id FROM devices WHERE device_id=?",
        (device_id,),
    ).fetchone()
    return row["owner_user_id"] if row else None


def get_user_profile_on_device(conn, device_id: str, user_id: str) -> str | None:
    row = conn.execute(
        "SELECT profile_id FROM device_profile_map WHERE device_id=? AND user_id=?",
        (device_id, user_id),
    ).fetchone()
    return row["profile_id"] if row else None


def delete_device_profile(conn, device_id: str, profile_id: str, user_id: str) -> None:
    """Remove one user's claim on a device profile. Other users' claims on the same profile are unaffected."""
    conn.execute(
        "DELETE FROM device_profile_map WHERE device_id=? AND profile_id=? AND user_id=?",
        (device_id, profile_id, user_id),
    )


def backfill_owner_on_profile_claim(conn, device_id: str, profile_id: str, user_id: str) -> None:
    """Stamp owner_user_id on historical transactions/events for a newly claimed profile."""
    conn.execute(
        "UPDATE sync_transactions SET owner_user_id=?"
        " WHERE source_device_id=? AND user_key=? AND owner_user_id IS NULL",
        (user_id, device_id, profile_id),
    )
    conn.execute(
        "UPDATE events SET owner_user_id=?"
        " WHERE transaction_id IN ("
        "  SELECT transaction_id FROM sync_transactions"
        "  WHERE source_device_id=? AND user_key=?"
        ") AND owner_user_id IS NULL",
        (user_id, device_id, profile_id),
    )


def backfill_owner_off_profile_unclaim(conn, device_id: str, profile_id: str, user_id: str) -> None:
    """Null out owner_user_id on this user's transactions/events when they unclaim a profile.

    Only affects rows owned by this user — other users' claims on the same profile are
    unaffected. Nulled rows become un-deliverable until the profile is re-claimed.
    Visibility is claim-table driven, so they also disappear from UI immediately.
    """
    conn.execute(
        "UPDATE sync_transactions SET owner_user_id=NULL"
        " WHERE source_device_id=? AND user_key=? AND owner_user_id=?",
        (device_id, profile_id, user_id),
    )
    conn.execute(
        "UPDATE events SET owner_user_id=NULL"
        " WHERE owner_user_id=? AND transaction_id IN ("
        "  SELECT transaction_id FROM sync_transactions"
        "  WHERE source_device_id=? AND user_key=?)",
        (user_id, device_id, profile_id),
    )


def get_user_has_claim_on_device(conn, device_id: str, user_id: str) -> bool:
    """Return True if the user already has any device profile claimed on this device."""
    return (
        conn.execute(
            "SELECT 1 FROM device_profile_map WHERE device_id=? AND user_id=?",
            (device_id, user_id),
        ).fetchone()
        is not None
    )


def get_auto_claim_profile(conn, device_id: str) -> tuple[str, str] | None:
    """Return (profile_id, profile_name) for auto-claim.

    Prefers the first globally-unclaimed profile (avoids cross-user save visibility).
    Falls back to co-claiming the first profile overall when all are already claimed —
    this is intentional: every user must always land with a default profile selected
    (family-trust model; users sharing a device implicitly share save visibility).
    Ordered by last_seen ASC, profile_id ASC for determinism.
    Callers must already have verified the user has no existing claim (get_user_has_claim_on_device).
    """
    row = conn.execute(
        "SELECT k.profile_id, k.profile_name FROM device_known_profiles k"
        " WHERE k.device_id=? AND k.profile_id != ?"
        " AND NOT EXISTS ("
        "  SELECT 1 FROM device_profile_map m"
        "  WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id)"
        " ORDER BY k.last_seen ASC, k.profile_id ASC LIMIT 1",
        (device_id, NULL_PROFILE_ID),
    ).fetchone()
    if row:
        return (row["profile_id"], row["profile_name"] or "")
    # All profiles claimed — co-claim the first so the user always has a default.
    # Design decision: co-claiming grants visibility into that profile's save history.
    row = conn.execute(
        "SELECT profile_id, profile_name FROM device_known_profiles"
        " WHERE device_id=? AND profile_id != ?"
        " ORDER BY last_seen ASC, profile_id ASC LIMIT 1",
        (device_id, NULL_PROFILE_ID),
    ).fetchone()
    return (row["profile_id"], row["profile_name"] or "") if row else None


def get_first_unclaimed_profile(conn, device_id: str, user_id: str) -> str | None:
    """Return the first device profile on this device not yet claimed by user_id.

    A profile is "unclaimed by this user" when no row exists in device_profile_map
    for (device_id, profile_id, user_id). Other users may have claimed the same profile.
    Excludes the Nintendo sentinel profile 0000000000000000 (no-account placeholder).
    Ordered by last_seen ascending so the oldest-known profile is preferred.
    """
    row = conn.execute(
        "SELECT k.profile_id FROM device_known_profiles k"
        " WHERE k.device_id=? AND k.profile_id != ?"
        " AND NOT EXISTS ("
        "  SELECT 1 FROM device_profile_map m"
        "  WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id AND m.user_id=?"
        " )"
        " ORDER BY k.last_seen ASC, k.profile_id ASC LIMIT 1",
        (device_id, NULL_PROFILE_ID, user_id),
    ).fetchone()
    return row["profile_id"] if row else None


def get_devices_for_user(conn, user_id: str) -> list[dict]:
    """Return all devices the user owns or has access to, including soft-deleted ones.

    Soft-deleted rows carry is_deleted=True so callers can hide them from active
    device lists while still resolving display_name for historical activity.
    """
    return [
        dict(r)
        for r in conn.execute(
            "SELECT DISTINCT d.device_id, d.display_name, d.hardware_type, d.client_type,"
            " d.last_seen, d.owner_user_id, d.deleted_at IS NOT NULL AS is_deleted,"
            " CASE WHEN d.owner_user_id=? THEN d.default_profile_uid"
            "      ELSE da.default_profile_uid END AS default_profile_uid"
            " FROM devices d"
            " LEFT JOIN device_access da ON da.device_id=d.device_id AND da.user_id=?"
            " WHERE d.owner_user_id=?"
            "   OR da.device_id IS NOT NULL"
            " ORDER BY d.last_seen DESC",
            (user_id, user_id, user_id),
        )
    ]


def user_has_device_access(conn, device_id: str, user_id: str) -> bool:
    """True if user owns the device or has been granted access."""
    row = conn.execute(
        "SELECT 1 FROM devices WHERE device_id=? AND owner_user_id=?"
        " UNION SELECT 1 FROM device_access WHERE device_id=? AND user_id=?",
        (device_id, user_id, device_id, user_id),
    ).fetchone()
    return row is not None


def set_device_owner(conn, device_id: str, user_id: str) -> None:
    conn.execute("UPDATE devices SET owner_user_id=? WHERE device_id=?", (user_id, device_id))


# ── Short-code helpers ─────────────────────────────────────────────────────────

_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32 chars — no 0/O/1/I/L


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def _expires_at(minutes: int = 15) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_pairing_code(conn, device_id: str) -> str:
    """Return existing valid pairing code or generate a new one."""
    existing = conn.execute(
        "SELECT code FROM device_pairing_codes WHERE device_id=? AND used=0 AND expires_at > ?",
        (device_id, _now()),
    ).fetchone()
    if existing:
        return existing["code"]
    # Expire any stale codes and issue a fresh one
    conn.execute(
        "UPDATE device_pairing_codes SET used=1 WHERE device_id=? AND used=0",
        (device_id,),
    )
    code = _gen_code()
    conn.execute(
        "INSERT INTO device_pairing_codes (code, device_id, expires_at) VALUES (?,?,?)",
        (code, device_id, _expires_at()),
    )
    return code


def claim_pairing_code(conn, code: str) -> str | None:
    """Validate and consume a pairing code. Returns device_id or None."""
    row = conn.execute(
        "SELECT device_id, expires_at FROM device_pairing_codes WHERE code=? AND used=0",
        (code.upper(),),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < _now():
        return None
    conn.execute("UPDATE device_pairing_codes SET used=1 WHERE code=?", (code.upper(),))
    return row["device_id"]


def create_share_code(conn, device_id: str, granted_by: str) -> str:
    """Generate a fresh 6-char share code. Prior unused codes for this device are expired."""
    conn.execute(
        "UPDATE device_share_codes SET used=1 WHERE device_id=? AND granted_by=? AND used=0",
        (device_id, granted_by),
    )
    code = _gen_code()
    conn.execute(
        "INSERT INTO device_share_codes (code, device_id, granted_by, expires_at) VALUES (?,?,?,?)",
        (code, device_id, granted_by, _expires_at()),
    )
    return code


def claim_share_code(conn, code: str) -> tuple[str, str] | None:
    """Validate and consume a share code. Returns (device_id, granted_by) or None."""
    row = conn.execute(
        "SELECT device_id, granted_by, expires_at FROM device_share_codes WHERE code=? AND used=0",
        (code.upper(),),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < _now():
        return None
    conn.execute("UPDATE device_share_codes SET used=1 WHERE code=?", (code.upper(),))
    return row["device_id"], row["granted_by"]


def grant_device_access(conn, device_id: str, user_id: str, granted_by: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO device_access (device_id, user_id, granted_by, created_at)"
        " VALUES (?,?,?,?)",
        (device_id, user_id, granted_by, _now()),
    )


def revoke_device_access(conn, device_id: str, user_id: str) -> None:
    conn.execute(
        "DELETE FROM device_access WHERE device_id=? AND user_id=?",
        (device_id, user_id),
    )


def list_device_access(conn, device_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT user_id, granted_by, created_at FROM device_access WHERE device_id=?"
            " ORDER BY created_at",
            (device_id,),
        )
    ]


def replace_device_catalog(conn, device_id: str, title_ids: list[str]) -> None:
    """Full replace of installed-game catalog for a device.

    Caller MUST wrap in BEGIN IMMEDIATE / COMMIT to prevent readers from
    observing a transient empty state between DELETE and INSERT.
    title_ids are uppercased to match sync_transactions convention.
    """
    conn.execute("DELETE FROM device_installed_games WHERE device_id=?", (device_id,))
    conn.executemany(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?, ?)",
        [(device_id, t.upper()) for t in title_ids],
    )


def get_catalog_members(conn, title_id: str, exclude_device_id: str) -> list[str]:
    """Return device_ids of all devices with title_id installed, excluding source device."""
    rows = conn.execute(
        "SELECT device_id FROM device_installed_games WHERE title_id=? AND device_id!=?",
        (title_id.upper(), exclude_device_id),
    ).fetchall()
    return [r["device_id"] for r in rows]


def upsert_virtual_device(
    conn,
    device_id: str,
    display_name: str,
    hardware_type: str,
    client_type: str = "",
    owner_user_id: str | None = None,
) -> None:
    """Insert or refresh a virtual (non-physical) device row.

    owner_user_id MUST be set to the admin username so get_devices_for_user
    returns this device only for admin. Without it, supplemental queries would
    expose the device to every authenticated user — a security violation.
    """
    now = _now()
    conn.execute(
        "INSERT INTO devices"
        "(device_id,display_name,hardware_type,client_type,owner_user_id,last_seen,created_at)"
        " VALUES(?,?,?,?,?,?,?)"
        " ON CONFLICT(device_id) DO UPDATE SET"
        "   display_name=excluded.display_name,"
        "   hardware_type=excluded.hardware_type,"
        "   client_type=CASE WHEN excluded.client_type!='' THEN excluded.client_type"
        "                    ELSE devices.client_type END,"
        "   owner_user_id=CASE WHEN excluded.owner_user_id IS NOT NULL THEN excluded.owner_user_id"
        "                      ELSE devices.owner_user_id END,"
        "   last_seen=excluded.last_seen",
        # deleted_at intentionally NOT updated — UI toggle owns that field exclusively.
        (device_id, display_name, hardware_type, client_type, owner_user_id, now, now),
    )


def sync_romm_catalog_to_device(conn, username: str, romm_device_id: str) -> None:
    """Rebuild device_installed_games for the RomM virtual device from romm_title_map.

    CATALOG SCOPE RULE: RomM's catalog = romm_title_map only. We never enumerate
    what RomM actually contains — that would fan out titles the user never enrolled.

    Caller must NOT hold an open write transaction; this function opens its own
    BEGIN IMMEDIATE to satisfy replace_device_catalog's atomicity requirement.
    """
    rows = get_romm_title_map(conn, username)
    title_ids = [r["title_id"] for r in rows]
    conn.execute("BEGIN IMMEDIATE")
    try:
        replace_device_catalog(conn, romm_device_id, title_ids)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def insert_play_events(conn, device_id: str, owner_user_id: str, events: list[dict]) -> int:
    """INSERT OR IGNORE raw activity events atomically. Returns count of rows actually inserted."""
    now = _now()
    inserted = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for e in events:
            cur = conn.execute(
                "INSERT OR IGNORE INTO device_play_events"
                " (device_id, owner_user_id, profile_id, application_id,"
                "  event_type, event_timestamp, monotonic_timestamp, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    owner_user_id,
                    e.get("profile_id") or "",
                    e.get("application_id") or "",
                    e["event_type"],
                    e["event_timestamp"],
                    e["monotonic_timestamp"],
                    now,
                ),
            )
            inserted += cur.rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return inserted


def get_play_events(
    conn,
    device_id: str | None = None,
    application_id: str | None = None,
    owner_user_id: str | None = None,
    since: int | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """Return raw device_play_events rows matching the given filters."""
    clauses: list[str] = []
    params: list = []
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if application_id is not None:
        clauses.append("application_id = ?")
        params.append(application_id)
    if owner_user_id is not None:
        clauses.append("owner_user_id = ?")
        params.append(owner_user_id)
    if since is not None:
        clauses.append("event_timestamp >= ?")
        params.append(since)
    sql = (
        "SELECT * FROM device_play_events"
        + (" WHERE " + " AND ".join(clauses) if clauses else "")
        + " ORDER BY event_timestamp ASC"
        + " LIMIT ? OFFSET ?"
    )
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return [dict(r) for r in rows]


def get_daily_playtime(
    conn,
    owner_user_id: str,
    application_id: str | None = None,
) -> list[dict]:
    """Return daily playtime totals in minutes derived from active-interval event pairs.

    Pairs each APPLICATION_FOCUSED with the nearest APPLICATION_UNFOCUSED on the same
    (device_id, application_id, profile_id) using monotonic_timestamp. These events mark
    when an application is actively in use (foreground/screen-on). Clients are expected to
    emit FOCUSED/UNFOCUSED to represent active time; STARTED/EXITED bracket the full
    lifecycle and may include background suspension.
    """
    sql = """
        WITH sessions AS (
          SELECT
            date(s.event_timestamp, 'unixepoch') AS play_date,
            s.application_id AS title_id,
            MIN(e.monotonic_timestamp) - s.monotonic_timestamp AS duration_sec
          FROM device_play_events s
          JOIN device_play_events e ON
            e.device_id = s.device_id
            AND e.application_id IS s.application_id
            AND e.profile_id IS s.profile_id
            AND e.event_type = 'APPLICATION_UNFOCUSED'
            AND e.monotonic_timestamp > s.monotonic_timestamp
            AND e.monotonic_timestamp - s.monotonic_timestamp <= 86400
          WHERE s.event_type = 'APPLICATION_FOCUSED'
            AND s.owner_user_id = ?
            AND (? IS NULL OR s.application_id = ?)
          GROUP BY s.device_id, s.application_id, s.event_timestamp, s.monotonic_timestamp
        )
        SELECT
          play_date AS date,
          title_id,
          COALESCE(l.label, title_id) AS display_name,
          SUM(duration_sec) AS total_sec
        FROM sessions
        LEFT JOIN labels l ON l.entity_type = 'game' AND l.entity_id = title_id
        WHERE duration_sec > 0
        GROUP BY play_date, title_id
        ORDER BY play_date, total_sec DESC
    """
    rows = conn.execute(sql, (owner_user_id, application_id, application_id)).fetchall()
    days: dict[str, dict] = {}
    for r in rows:
        date = r["date"]
        if date not in days:
            days[date] = {"date": date, "total_sec": 0, "games": []}
        days[date]["total_sec"] += r["total_sec"]
        days[date]["games"].append(
            {
                "title_id": r["title_id"],
                "display_name": r["display_name"],
                "minutes": r["total_sec"] // 60,
            }
        )
    return [
        {"date": d["date"], "minutes": d["total_sec"] // 60, "games": d["games"]}
        for d in days.values()
    ]


def list_device_profiles(conn, device_id: str, user_id: str = "") -> list[dict]:
    """Return one row per known profile with per-user claim status.

    user_id: the requesting user; drives is_mine and preferred user_id in the result.
    Source of truth: device_known_profiles (not transaction history).
    One row per profile — safe for co-claimed profiles (multiple users per profile).
    """
    rows = conn.execute(
        "SELECT k.profile_id, k.profile_name AS known_name,"
        "  (SELECT m.user_id FROM device_profile_map m"
        "   WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id AND m.user_id=? LIMIT 1) AS my_user_id,"
        "  (SELECT m.profile_name FROM device_profile_map m"
        "   WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id AND m.user_id=? LIMIT 1) AS my_claimed_name,"
        "  (SELECT m.user_id FROM device_profile_map m"
        "   WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id AND m.user_id!=? LIMIT 1) AS other_user_id,"
        "  (SELECT m.profile_name FROM device_profile_map m"
        "   WHERE m.device_id=k.device_id AND m.profile_id=k.profile_id AND m.user_id!=? LIMIT 1) AS other_claimed_name"
        " FROM device_known_profiles k"
        " WHERE k.device_id=?"
        " ORDER BY k.last_seen DESC",
        (user_id, user_id, user_id, user_id, device_id),
    ).fetchall()
    result = []
    for r in rows:
        is_mine = r["my_user_id"] is not None
        display_user_id = r["my_user_id"] if is_mine else r["other_user_id"]
        profile_name = r["my_claimed_name"] or r["other_claimed_name"] or r["known_name"] or ""
        result.append(
            {
                "profile_id": r["profile_id"],
                "profile_name": profile_name,
                "display_hint": r["known_name"] or "",
                "user_id": display_user_id,
                "is_mine": is_mine,
            }
        )
    return result
