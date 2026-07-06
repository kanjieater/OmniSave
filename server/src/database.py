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


def is_retail_app_id(app_id: str, client_type: str) -> bool:
    """True if app_id is a retail title (Switch: must start with 0100; other clients: always true)."""
    if client_type == "switch":
        return app_id.upper().startswith("0100")
    return True


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
    user_id TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS auth_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    session_token TEXT,
    created_at    TEXT NOT NULL,
    id            TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    token      TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
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
    device_id      TEXT    NOT NULL,
    profile_id     TEXT    NOT NULL,
    user_id        TEXT    NOT NULL,
    profile_name   TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    is_auto_claimed BOOLEAN NOT NULL DEFAULT 0,
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
    user_id  TEXT NOT NULL,
    title_id TEXT NOT NULL,
    rom_id   INTEGER NOT NULL,
    mapped_at TEXT,
    PRIMARY KEY (user_id, title_id)
);

CREATE TABLE IF NOT EXISTS romm_game_cache (
    user_id    TEXT NOT NULL,
    rom_id     INTEGER NOT NULL,
    name       TEXT,
    icon_url   TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (user_id, rom_id)
);

CREATE TABLE IF NOT EXISTS labels (
    entity_type TEXT NOT NULL CHECK(entity_type IN ('game')),
    entity_id   TEXT NOT NULL,
    label       TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS romm_save_sync (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    rom_id         INTEGER NOT NULL,
    romm_save_id   INTEGER NOT NULL,
    direction      TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    transaction_id TEXT,
    synced_at      TEXT NOT NULL,
    UNIQUE(user_id, rom_id, romm_save_id, direction)
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

-- PDM offset the server has durably received for each device.
-- Monotonically increasing; never regresses.
CREATE TABLE IF NOT EXISTS device_activity_offset (
    device_id   TEXT    PRIMARY KEY,
    last_offset INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL
);
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

    # Add is_auto_claimed to device_profile_map (new installs have it via SCHEMA)
    if "device_profile_map" in existing:
        dpm_cols = {r[1] for r in conn.execute("PRAGMA table_info(device_profile_map)").fetchall()}
        if "is_auto_claimed" not in dpm_cols:
            conn.execute(
                "ALTER TABLE device_profile_map ADD COLUMN is_auto_claimed BOOLEAN NOT NULL DEFAULT 0"
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
            "  user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            "  PRIMARY KEY (user_id, key)"
            ")"
        )

    # Hard-reset romm tables that lack either identity column (pre-release; no data to preserve).
    # Rebuilds with user_id schema. Tables with username are handled later by UUID migration.
    _ROMM_TABLE_DDL = {
        "romm_title_map": (
            "CREATE TABLE romm_title_map ("
            "  user_id TEXT NOT NULL, title_id TEXT NOT NULL,"
            "  rom_id INTEGER NOT NULL, mapped_at TEXT,"
            "  PRIMARY KEY (user_id, title_id)"
            ")"
        ),
        "romm_game_cache": (
            "CREATE TABLE romm_game_cache ("
            "  user_id TEXT NOT NULL, rom_id INTEGER NOT NULL,"
            "  name TEXT, icon_url TEXT, fetched_at TEXT NOT NULL,"
            "  PRIMARY KEY (user_id, rom_id)"
            ")"
        ),
        "romm_save_sync": (
            "CREATE TABLE romm_save_sync ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,"
            "  rom_id INTEGER NOT NULL, romm_save_id INTEGER NOT NULL,"
            "  direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),"
            "  transaction_id TEXT, synced_at TEXT NOT NULL,"
            "  UNIQUE(user_id, rom_id, romm_save_id, direction)"
            ")"
        ),
    }
    for tbl, ddl in _ROMM_TABLE_DDL.items():
        if tbl in existing:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "user_id" not in cols and "username" not in cols:
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

    # Enforce one title_id per rom_id per user in romm_title_map (pre-UUID schema guard).
    if "romm_title_map" in existing:
        rtm_pre = {r[1] for r in conn.execute("PRAGMA table_info(romm_title_map)").fetchall()}
        group_col = "username" if "username" in rtm_pre else "user_id"
        conn.execute(
            f"DELETE FROM romm_title_map WHERE rowid NOT IN"
            f" (SELECT MIN(rowid) FROM romm_title_map GROUP BY {group_col}, rom_id)"
        )
        try:
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uniq_romm_title_map_rom"
                f" ON romm_title_map({group_col}, rom_id)"
            )
        except sqlite3.OperationalError:  # pragma: no cover
            pass

    # V-UUID: stable UUID user identity.
    # Replace username string FK with stable UUID in all ownership tables.
    # Guard: only runs when auth_users.id column is absent (old schema).
    au_cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
    if au_cols and "id" not in au_cols:
        users = conn.execute("SELECT username FROM auth_users").fetchall()
        user_uuids = {r[0]: str(uuid.uuid4()) for r in users}

        sc_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='server_config'"
        ).fetchone()
        if sc_exists:
            admin_id_row = conn.execute(
                "SELECT value FROM server_config WHERE key='admin_user_id'"
            ).fetchone()
            admin_user_id = admin_id_row["value"] if admin_id_row else str(uuid.uuid4())
            admin_name_row = conn.execute(
                "SELECT value FROM server_config WHERE key='admin_username'"
            ).fetchone()
            old_admin_name = admin_name_row["value"] if admin_name_row else "admin"
        else:
            admin_id_row = None
            admin_user_id = str(uuid.uuid4())
            old_admin_name = "admin"

        conn.execute("SAVEPOINT uuid_migration")
        try:
            if sc_exists and not admin_id_row:
                conn.execute(
                    "INSERT OR REPLACE INTO server_config (key,value) VALUES ('admin_user_id',?)",
                    (admin_user_id,),
                )
            conn.execute("ALTER TABLE auth_users ADD COLUMN id TEXT NOT NULL DEFAULT ''")
            for uname, uid in user_uuids.items():
                conn.execute("UPDATE auth_users SET id=? WHERE username=?", (uid, uname))
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_id ON auth_users(id)")
            # Simple FK tables: only update values, column names stay the same
            _SIMPLE_FK = [
                ("devices", "owner_user_id"),
                ("sync_transactions", "owner_user_id"),
                ("events", "owner_user_id"),
                ("device_auth", "user_id"),
                ("device_access", "user_id"),
                ("device_play_events", "owner_user_id"),
                ("device_profile_map", "user_id"),
            ]
            for _tbl, _col in _SIMPLE_FK:
                if _tbl in existing:
                    conn.execute(
                        f"UPDATE {_tbl} SET {_col} = ("
                        f"  SELECT id FROM auth_users WHERE username = {_tbl}.{_col}"
                        f") WHERE {_col} IS NOT NULL AND EXISTS ("
                        f"  SELECT 1 FROM auth_users WHERE username = {_tbl}.{_col}"
                        f")"
                    )
            # Admin rows: admin is in server_config, not auth_users — backfill separately
            for _tbl, _col in _SIMPLE_FK:
                if _tbl in existing:
                    conn.execute(
                        f"UPDATE {_tbl} SET {_col}=? WHERE {_col}=?",  # noqa: S608
                        (admin_user_id, old_admin_name),
                    )
            # auth_sessions: rename username → user_id column
            as_cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_sessions)").fetchall()}
            if "username" in as_cols:
                conn.execute("""
                    CREATE TABLE auth_sessions_new (
                        session_id TEXT PRIMARY KEY,
                        user_id    TEXT NOT NULL,
                        token      TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute(
                    "INSERT INTO auth_sessions_new (session_id, user_id, token, created_at)"
                    " SELECT s.session_id,"
                    "  CASE WHEN s.username=? THEN ?"
                    "       ELSE (SELECT id FROM auth_users WHERE username=s.username) END,"
                    "  s.token, s.created_at"
                    " FROM auth_sessions s"
                    " WHERE s.username=?"
                    "    OR EXISTS (SELECT 1 FROM auth_users WHERE username=s.username)",
                    (old_admin_name, admin_user_id, old_admin_name),
                )
                conn.execute("DROP TABLE auth_sessions")
                conn.execute("ALTER TABLE auth_sessions_new RENAME TO auth_sessions")
            # user_config: rename username → user_id column
            uc_cols = {r[1] for r in conn.execute("PRAGMA table_info(user_config)").fetchall()}
            if "username" in uc_cols:
                conn.execute("""
                    CREATE TABLE user_config_new (
                        user_id TEXT NOT NULL,
                        key     TEXT NOT NULL,
                        value   TEXT NOT NULL,
                        PRIMARY KEY (user_id, key)
                    )
                """)
                conn.execute(
                    "INSERT INTO user_config_new (user_id, key, value)"
                    " SELECT CASE WHEN uc.username=? THEN ?"
                    "             ELSE (SELECT id FROM auth_users WHERE username=uc.username) END,"
                    "  uc.key, uc.value"
                    " FROM user_config uc"
                    " WHERE uc.username=?"
                    "    OR EXISTS (SELECT 1 FROM auth_users WHERE username=uc.username)",
                    (old_admin_name, admin_user_id, old_admin_name),
                )
                conn.execute("DROP TABLE user_config")
                conn.execute("ALTER TABLE user_config_new RENAME TO user_config")
            # romm_title_map: rename username → user_id column
            rtm_cols = {r[1] for r in conn.execute("PRAGMA table_info(romm_title_map)").fetchall()}
            if "username" in rtm_cols:
                has_pi = "pull_initialized" in rtm_cols
                conn.execute("""
                    CREATE TABLE romm_title_map_new (
                        user_id          TEXT NOT NULL,
                        title_id         TEXT NOT NULL,
                        rom_id           INTEGER NOT NULL,
                        mapped_at        TEXT,
                        pull_initialized INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (user_id, title_id)
                    )
                """)
                pi_col = "COALESCE(r.pull_initialized,0)" if has_pi else "0"
                conn.execute(
                    "INSERT INTO romm_title_map_new (user_id,title_id,rom_id,mapped_at,pull_initialized)"
                    f" SELECT CASE WHEN r.username=? THEN ?"
                    f"             ELSE (SELECT id FROM auth_users WHERE username=r.username) END,"
                    f"  r.title_id, r.rom_id, r.mapped_at, {pi_col}"
                    " FROM romm_title_map r"
                    " WHERE r.username=?"
                    "    OR EXISTS (SELECT 1 FROM auth_users WHERE username=r.username)",
                    (old_admin_name, admin_user_id, old_admin_name),
                )
                conn.execute("DROP TABLE romm_title_map")
                conn.execute("ALTER TABLE romm_title_map_new RENAME TO romm_title_map")
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_romm_title_map_rom"
                    " ON romm_title_map(user_id, rom_id)"
                )
            # romm_game_cache: rename username → user_id column
            rgc_cols = {r[1] for r in conn.execute("PRAGMA table_info(romm_game_cache)").fetchall()}
            if "username" in rgc_cols:
                conn.execute("""
                    CREATE TABLE romm_game_cache_new (
                        user_id    TEXT NOT NULL,
                        rom_id     INTEGER NOT NULL,
                        name       TEXT,
                        icon_url   TEXT,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, rom_id)
                    )
                """)
                conn.execute(
                    "INSERT INTO romm_game_cache_new (user_id,rom_id,name,icon_url,fetched_at)"
                    " SELECT CASE WHEN r.username=? THEN ?"
                    "             ELSE (SELECT id FROM auth_users WHERE username=r.username) END,"
                    "  r.rom_id, r.name, r.icon_url, r.fetched_at"
                    " FROM romm_game_cache r"
                    " WHERE r.username=?"
                    "    OR EXISTS (SELECT 1 FROM auth_users WHERE username=r.username)",
                    (old_admin_name, admin_user_id, old_admin_name),
                )
                conn.execute("DROP TABLE romm_game_cache")
                conn.execute("ALTER TABLE romm_game_cache_new RENAME TO romm_game_cache")
            # romm_save_sync: rename username → user_id column
            rss_cols = {r[1] for r in conn.execute("PRAGMA table_info(romm_save_sync)").fetchall()}
            if "username" in rss_cols:
                conn.execute("""
                    CREATE TABLE romm_save_sync_new (
                        id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id        TEXT NOT NULL,
                        rom_id         INTEGER NOT NULL,
                        romm_save_id   INTEGER NOT NULL,
                        direction      TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                        transaction_id TEXT,
                        synced_at      TEXT NOT NULL,
                        UNIQUE(user_id, rom_id, romm_save_id, direction)
                    )
                """)
                conn.execute(
                    "INSERT INTO romm_save_sync_new (user_id,rom_id,romm_save_id,direction,transaction_id,synced_at)"
                    " SELECT CASE WHEN r.username=? THEN ?"
                    "             ELSE (SELECT id FROM auth_users WHERE username=r.username) END,"
                    "  r.rom_id, r.romm_save_id, r.direction, r.transaction_id, r.synced_at"
                    " FROM romm_save_sync r"
                    " WHERE r.username=?"
                    "    OR EXISTS (SELECT 1 FROM auth_users WHERE username=r.username)",
                    (old_admin_name, admin_user_id, old_admin_name),
                )
                conn.execute("DROP TABLE romm_save_sync")
                conn.execute("ALTER TABLE romm_save_sync_new RENAME TO romm_save_sync")
            # device_share_codes.granted_by / device_access.granted_by — these columns
            # store who created/approved the share.  COALESCE fallback is intentional:
            # granted_by is display-only metadata; no access-control path reads it.
            for _tbl in ("device_share_codes", "device_access"):
                if _tbl in existing:
                    conn.execute(
                        f"UPDATE {_tbl} SET granted_by ="  # noqa: S608
                        " CASE WHEN granted_by=? THEN ?"
                        "  ELSE COALESCE((SELECT id FROM auth_users WHERE username=granted_by), granted_by)"
                        " END",
                        (old_admin_name, admin_user_id),
                    )
            conn.execute("RELEASE SAVEPOINT uuid_migration")
            log.info("UUID identity migration: %d user(s) migrated", len(user_uuids))
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT uuid_migration")
            conn.execute("RELEASE SAVEPOINT uuid_migration")
            raise

    # Admin ownership backfill — idempotent, runs every startup.
    # Admin is not in auth_users so the UUID migration JOIN skips admin rows.
    # This step fixes any ownership column still holding the admin username string.
    # Safe no-op once all rows are already UUIDs.
    if sc_tables:
        _auid_row = conn.execute(
            "SELECT value FROM server_config WHERE key='admin_user_id'"
        ).fetchone()
        _aname_row = conn.execute(
            "SELECT value FROM server_config WHERE key='admin_username'"
        ).fetchone()
        if _auid_row and _aname_row:
            _auid = _auid_row["value"]
            _aname = _aname_row["value"]
            for _tbl, _col in [
                ("devices", "owner_user_id"),
                ("sync_transactions", "owner_user_id"),
                ("events", "owner_user_id"),
                ("device_auth", "user_id"),
                ("device_access", "user_id"),
                ("device_share_codes", "granted_by"),
                ("device_access", "granted_by"),
                ("device_play_events", "owner_user_id"),
                ("device_profile_map", "user_id"),
                ("user_config", "user_id"),
                ("romm_title_map", "user_id"),
                ("romm_game_cache", "user_id"),
                ("romm_save_sync", "user_id"),
                ("auth_sessions", "user_id"),
            ]:
                if _tbl in existing:
                    _tcols = {
                        r[1]
                        for r in conn.execute(
                            f"PRAGMA table_info({_tbl})"  # noqa: S608
                        ).fetchall()
                    }
                    if _col in _tcols:
                        conn.execute(
                            f"UPDATE {_tbl} SET {_col}=? WHERE {_col}=?",  # noqa: S608
                            (_auid, _aname),
                        )

    # Idempotent: backfill granted_by username→UUID for instances that already ran the migration.
    # The migration SAVEPOINT runs once (guarded by "id" not in au_cols); this catches rows
    # written pre-upgrade or on instances that upgraded before this fix shipped.
    for _tbl in ("device_share_codes", "device_access"):
        if _tbl in existing:
            _gb_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_tbl})").fetchall()}  # noqa: S608
            if "granted_by" in _gb_cols:
                conn.execute(
                    f"UPDATE {_tbl} SET granted_by = ("  # noqa: S608
                    f"  SELECT id FROM auth_users WHERE username = {_tbl}.granted_by"
                    f") WHERE EXISTS ("
                    f"  SELECT 1 FROM auth_users WHERE username = {_tbl}.granted_by"
                    f")"
                )

    # Idempotent — must exist for both fresh installs and post-migration upgrades.
    # Not in SCHEMA because it would fail on legacy DBs before the migration adds auth_users.id.
    au_cols_now = {r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
    if "id" in au_cols_now:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_id ON auth_users(id)")

    # Idempotent: pin romm_source_id and canonicalise stale romm:username device IDs.
    # RomM shipped in v1.3.0 using romm:{username} as the virtual device ID.
    # UUID migration changed the fallback to romm:{uuid}. On upgrade, old
    # romm:username entries in sync_transactions / device_title_head have no
    # display_name and show as truncated device_id strings in the UI.
    # For each user with a registered canonical romm device: pin romm_source_id
    # (prevents future drift), then merge stale romm:* references to canonical.
    if "devices" in existing and "sync_transactions" in existing:
        _txn_cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_transactions)").fetchall()}
        _dth_cols = {r[1] for r in conn.execute("PRAGMA table_info(device_title_head)").fetchall()}
        _uc_cols = {r[1] for r in conn.execute("PRAGMA table_info(user_config)").fetchall()}
        _canonical_romm = conn.execute(
            "SELECT device_id, owner_user_id FROM devices"
            " WHERE device_id LIKE 'romm:%' AND client_type='romm'"
            "   AND owner_user_id IS NOT NULL AND deleted_at IS NULL"
            " ORDER BY created_at ASC"
        ).fetchall()
        for _crow in _canonical_romm:
            _cid = _crow["device_id"]
            _ouid = _crow["owner_user_id"]
            if "user_config" in existing and "user_id" in _uc_cols:
                conn.execute(
                    "INSERT OR IGNORE INTO user_config (user_id, key, value) VALUES (?,?,?)",
                    (_ouid, "romm_source_id", _cid),
                )
            if "source_device_id" in _txn_cols:
                conn.execute(
                    "UPDATE sync_transactions SET source_device_id=?"
                    " WHERE source_device_id LIKE 'romm:%' AND source_device_id!=?"
                    "   AND owner_user_id=?",
                    (_cid, _cid, _ouid),
                )
            if "target_device_id" in _txn_cols:
                conn.execute(
                    "UPDATE sync_transactions SET target_device_id=?"
                    " WHERE target_device_id LIKE 'romm:%' AND target_device_id!=?"
                    "   AND owner_user_id=?",
                    (_cid, _cid, _ouid),
                )
            if "device_title_head" in existing and "device_id" in _dth_cols:
                conn.execute(
                    "INSERT INTO device_title_head (title_id, device_id, last_seq, updated_at)"
                    " SELECT title_id, ?, last_seq, updated_at"
                    " FROM device_title_head"
                    " WHERE device_id LIKE 'romm:%' AND device_id!=?"
                    "   AND title_id IN ("
                    "     SELECT title_id FROM sync_transactions WHERE owner_user_id=?"
                    "   )"
                    " ON CONFLICT (title_id, device_id) DO UPDATE"
                    "   SET last_seq = MAX(last_seq, excluded.last_seq),"
                    "       updated_at = MAX(updated_at, excluded.updated_at)",
                    (_cid, _cid, _ouid),
                )
                conn.execute(
                    "DELETE FROM device_title_head"
                    " WHERE device_id LIKE 'romm:%' AND device_id!=?"
                    "   AND device_id NOT IN ("
                    "     SELECT device_id FROM devices WHERE client_type='romm' AND deleted_at IS NULL"
                    "   )"
                    "   AND title_id IN ("
                    "     SELECT title_id FROM sync_transactions WHERE owner_user_id=?"
                    "   )",
                    (_cid, _ouid),
                )


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


def get_user_config(conn, user_id: str, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM user_config WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    return row["value"] if row else None


def set_user_config(conn, user_id: str, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO user_config (user_id,key,value) VALUES (?,?,?)"
        " ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
        (user_id, key, value),
    )


def get_romm_users(conn) -> list[dict]:
    """Users with RomM enabled. Returns [{user_id, username}]; username may be None for admin."""
    rows = conn.execute(
        "SELECT uc.user_id, a.username"
        " FROM user_config uc"
        " LEFT JOIN auth_users a ON a.id = uc.user_id"
        " WHERE uc.key='romm_enabled' AND uc.value='1'"
    ).fetchall()
    return [{"user_id": r["user_id"], "username": r["username"] or r["user_id"]} for r in rows]


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


def get_romm_rom_id(conn, user_id: str, title_id: str) -> int | None:
    row = conn.execute(
        "SELECT rom_id FROM romm_title_map WHERE user_id=? AND title_id=?",
        (user_id, title_id.upper()),
    ).fetchone()
    return row["rom_id"] if row else None


def upsert_romm_title_map(conn, user_id: str, title_id: str, rom_id: int) -> None:
    conn.execute(
        "INSERT INTO romm_title_map(user_id,title_id,rom_id,mapped_at) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id,title_id) DO UPDATE SET rom_id=excluded.rom_id, mapped_at=excluded.mapped_at",
        (user_id, title_id.upper(), rom_id, _now()),
    )


def delete_romm_title_map(conn, user_id: str, title_id: str) -> None:
    conn.execute(
        "DELETE FROM romm_title_map WHERE user_id=? AND title_id=?",
        (user_id, title_id.upper()),
    )


def delete_romm_title_map_by_rom_id(conn, user_id: str, rom_id: int) -> None:
    conn.execute(
        "DELETE FROM romm_title_map WHERE user_id=? AND rom_id=?",
        (user_id, rom_id),
    )


def get_romm_title_map(conn, user_id: str) -> list:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT title_id, rom_id, mapped_at, pull_initialized FROM romm_title_map"
            " WHERE user_id=? ORDER BY mapped_at DESC",
            (user_id,),
        ).fetchall()
    ]


def mark_romm_pull_initialized(conn, user_id: str, rom_id: int) -> None:
    conn.execute(
        "UPDATE romm_title_map SET pull_initialized=1 WHERE user_id=? AND rom_id=?",
        (user_id, rom_id),
    )


# ── RomM game cache ────────────────────────────────────────────────────────────


def get_romm_game_cache(conn, user_id: str, rom_id: int) -> dict | None:
    row = conn.execute(
        "SELECT rom_id, name, icon_url, fetched_at FROM romm_game_cache"
        " WHERE user_id=? AND rom_id=?",
        (user_id, rom_id),
    ).fetchone()
    return dict(row) if row else None


def get_all_romm_game_cache(conn, user_id: str) -> dict:
    return {
        r["rom_id"]: {"name": r["name"], "icon_url": r["icon_url"], "fetched_at": r["fetched_at"]}
        for r in conn.execute(
            "SELECT rom_id, name, icon_url, fetched_at FROM romm_game_cache WHERE user_id=?",
            (user_id,),
        ).fetchall()
    }


def upsert_romm_game_cache(
    conn, user_id: str, rom_id: int, name: str | None, icon_url: str | None
) -> None:
    if name and len(name) > 512:
        name = name[:512]
    if icon_url and len(icon_url) > 2048:
        icon_url = None
    conn.execute(
        "INSERT INTO romm_game_cache(user_id,rom_id,name,icon_url,fetched_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(user_id,rom_id) DO UPDATE SET name=excluded.name, icon_url=excluded.icon_url, "
        "fetched_at=excluded.fetched_at",
        (user_id, rom_id, name, icon_url, _now()),
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


def has_romm_sync(conn, user_id: str, rom_id: int, romm_save_id: int, direction: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM romm_save_sync"
        " WHERE user_id=? AND rom_id=? AND romm_save_id=? AND direction=?",
        (user_id, rom_id, romm_save_id, direction),
    ).fetchone()
    return row is not None


def record_romm_sync(
    conn,
    user_id: str,
    rom_id: int,
    romm_save_id: int,
    direction: str,
    transaction_id: str | None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO romm_save_sync"
        "(user_id,rom_id,romm_save_id,direction,transaction_id,synced_at) "
        "VALUES(?,?,?,?,?,?)",
        (user_id, rom_id, romm_save_id, direction, transaction_id, _now()),
    )


def get_romm_undelivered_head_txns(conn, user_id: str, romm_device_id: str) -> list:
    """Return inbound HEAD transactions where all delivery attempts to romm_device_id failed.

    Retry-only: only fires when at least one FAILED outbound exists for this title+device.
    Never bootstraps on initial connection — new outbounds are created by processing fanout."""
    return conn.execute(
        "SELECT st.transaction_id, st.title_id, st.snapshot_sequence"
        " FROM sync_transactions st"
        " JOIN romm_title_map rtm ON rtm.title_id = st.title_id AND rtm.user_id = ?"
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
        (user_id, user_id, romm_device_id, romm_device_id),
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
        "INSERT INTO auth_users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), username, password_hash, _now()),
    )


def get_auth_user(conn, username: str) -> dict | None:
    row = conn.execute(
        "SELECT id, username, password_hash, session_token, created_at"
        " FROM auth_users WHERE username=?",
        (username,),
    ).fetchone()
    return dict(row) if row else None


def get_auth_user_by_token(conn, token: str) -> dict | None:
    """Return {id, username} for the session token. username is None for admin sessions."""
    row = conn.execute(
        "SELECT s.user_id AS id, a.username"
        " FROM auth_sessions s"
        " LEFT JOIN auth_users a ON a.id = s.user_id"
        " WHERE s.token=?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def insert_auth_session(conn, user_id: str, token: str) -> None:
    conn.execute(
        "INSERT INTO auth_sessions (session_id, user_id, token, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, token, _now()),
    )


def delete_auth_session_by_token(conn, token: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE token=?", (token,))


def delete_auth_sessions_for_user(conn, user_id: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))


def list_auth_users(conn) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, username, created_at FROM auth_users ORDER BY created_at ASC"
        ).fetchall()
    ]


def delete_auth_user(conn, username: str) -> bool:
    row = conn.execute("SELECT id FROM auth_users WHERE username=?", (username,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["id"],))
    n = conn.execute("DELETE FROM auth_users WHERE username=?", (username,)).rowcount
    return n > 0


def set_auth_user_password(conn, username: str, password_hash: str) -> None:
    conn.execute(
        "UPDATE auth_users SET password_hash=? WHERE username=?",
        (password_hash, username),
    )


def rename_auth_user(conn, user_id: str, new_username: str) -> None:
    """Rename display name only. UUID identity is stable — no cascade needed.
    Raises sqlite3.IntegrityError if new_username already exists."""
    conn.execute("UPDATE auth_users SET username=? WHERE id=?", (new_username, user_id))


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


def get_device_client_type(conn, device_id: str) -> str:
    row = conn.execute(
        "SELECT client_type FROM devices WHERE device_id=?",
        (device_id,),
    ).fetchone()
    return row["client_type"] if row else ""


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
    conn,
    device_id: str,
    profile_id: str,
    user_id: str,
    profile_name: str = "",
    is_auto_claimed: bool = False,
) -> None:
    """Claim a device profile for an OmniSave user.

    One OmniSave user claims exactly ONE device profile per device (UNIQUE device_id, user_id).
    Multiple OmniSave users may claim the same device profile (PK includes user_id).
    INSERT OR REPLACE atomically evicts any prior claim by the same user on this device.

    Explicit claims (is_auto_claimed=False) also evict any lazy upload auto-claims on this
    profile so the explicit assignment takes sole ownership.
    """
    if not is_auto_claimed:
        conn.execute(
            "DELETE FROM device_profile_map WHERE device_id=? AND profile_id=? AND is_auto_claimed=1",
            (device_id, profile_id),
        )
    conn.execute(
        "INSERT OR REPLACE INTO device_profile_map"
        " (device_id, profile_id, user_id, profile_name, created_at, is_auto_claimed)"
        " VALUES (?,?,?,?,?,?)",
        (device_id, profile_id, user_id, profile_name, _now(), int(is_auto_claimed)),
    )


def get_profile_owner(conn, device_id: str, profile_id: str) -> str | None:
    """Return the authoritative owner for a profile, or None if unclaimed.

    Explicit claims (is_auto_claimed=0) take priority over lazy upload auto-claims
    (is_auto_claimed=1). Within each tier the oldest claim wins for determinism.
    """
    row = conn.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?"
        " ORDER BY is_auto_claimed ASC, created_at ASC LIMIT 1",
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


def has_non_owner_claims(conn, device_id: str, owner_user_id: str) -> bool:
    """Return True if any user other than owner_user_id has a claim on this device.

    Used to detect managed multi-user devices where the owner should not auto-claim
    unclaimed profiles — they may be intended for assignment to another user.
    """
    return (
        conn.execute(
            "SELECT 1 FROM device_profile_map WHERE device_id=? AND user_id!=?",
            (device_id, owner_user_id),
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


def sync_romm_catalog_to_device(conn, user_id: str, romm_device_id: str) -> None:
    """Rebuild device_installed_games for the RomM virtual device from romm_title_map.

    CATALOG SCOPE RULE: RomM's catalog = romm_title_map only. We never enumerate
    what RomM actually contains — that would fan out titles the user never enrolled.

    Caller must NOT hold an open write transaction; this function opens its own
    BEGIN IMMEDIATE to satisfy replace_device_catalog's atomicity requirement.
    """
    rows = get_romm_title_map(conn, user_id)
    title_ids = [r["title_id"] for r in rows]
    conn.execute("BEGIN IMMEDIATE")
    try:
        replace_device_catalog(conn, romm_device_id, title_ids)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def insert_play_events(
    conn,
    device_id: str,
    owner_user_id: str,
    events: list[dict],
    next_offset: int | None = None,
) -> int:
    """INSERT OR IGNORE raw activity events, optionally advancing the watermark in the same transaction."""
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
        if next_offset is not None:
            conn.execute(
                """
                INSERT INTO device_activity_offset (device_id, last_offset, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE
                    SET last_offset = MAX(last_offset, excluded.last_offset),
                        updated_at  = excluded.updated_at
                """,
                (device_id, next_offset, now),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return inserted


def get_activity_offset(conn, device_id: str) -> int:
    row = conn.execute(
        "SELECT last_offset FROM device_activity_offset WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    return row[0] if row else 0


def set_activity_offset(conn, device_id: str, last_offset: int) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO device_activity_offset (device_id, last_offset, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE
                SET last_offset = MAX(last_offset, excluded.last_offset),
                    updated_at  = excluded.updated_at
            """,
            (device_id, last_offset, _now()),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


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
    """Return daily playtime totals by reconstructing valid play sessions from the
    activity event stream using a per-device state machine.

    A session spans APPLICATION_STARTED → APPLICATION_EXITED. Active time is the
    sum of APPLICATION_FOCUSED → APPLICATION_UNFOCUSED intervals (monotonic duration).
    Sessions with no PROFILE_ACTIVE or PROFILE_INACTIVE event are excluded. Consecutive
    UNFOCUSED events are collapsed. Zero-duration and negative intervals are ignored.
    A new APPLICATION_STARTED while a session is open closes the prior session (crash
    recovery). A backward monotonic_timestamp resets all state (device reboot boundary).
    Streams from different devices are never mixed.

    Profile attribution: if the last PROFILE_ACTIVE in a session maps to a different
    OmniSave user via device_profile_map, the session is excluded. Sessions on unowned
    devices (reached via device_profile_map) are only included when the active profile
    explicitly maps to this user. Latest PROFILE_ACTIVE wins for mid-session switches.
    """
    # Load profile→user mappings for all devices that could appear in the event stream:
    # owned devices + devices where this user has a claimed profile.
    profile_map: dict[tuple[str, str], str] = {}
    for row in conn.execute(
        """
        SELECT dpm.device_id, dpm.profile_id, dpm.user_id
        FROM device_profile_map dpm
        WHERE dpm.user_id = ?
           OR dpm.device_id IN (
               SELECT DISTINCT device_id FROM device_play_events WHERE owner_user_id = ?
           )
        """,
        (owner_user_id, owner_user_id),
    ):
        profile_map[(row["device_id"], row["profile_id"])] = row["user_id"]

    device_client_type: dict[str, str] = {
        row["device_id"]: row["client_type"]
        for row in conn.execute(
            """
            SELECT device_id, client_type FROM devices
            WHERE device_id IN (
                SELECT DISTINCT device_id FROM device_play_events
                WHERE owner_user_id = ?
                   OR device_id IN (SELECT device_id FROM device_profile_map WHERE user_id = ?)
            )
            """,
            (owner_user_id, owner_user_id),
        )
    }

    rows = conn.execute(
        """
        SELECT event_type, application_id, profile_id,
               event_timestamp, monotonic_timestamp, device_id,
               owner_user_id AS device_owner
        FROM device_play_events
        WHERE owner_user_id = ?
           OR device_id IN (SELECT device_id FROM device_profile_map WHERE user_id = ?)
        ORDER BY device_id, id
        """,
        (owner_user_id, owner_user_id),
    ).fetchall()

    # accumulated[(date, app_id)] → total seconds across all valid sessions
    accumulated: dict[tuple[str, str], int] = {}

    # Per-device state: IDLE | IN_SESSION | FOCUSED
    state = "IDLE"
    session_app = ""
    has_profile = False
    session_profile_id: str | None = None
    session_acc: dict[tuple[str, str], int] = {}
    focus_mono: int | None = None
    focus_wall: int | None = None
    prev_mono: int | None = None
    prev_device: str | None = None
    current_device: str = ""
    current_device_owner: str = ""
    is_retail: bool = True
    current_client_type: str = ""

    def _emit() -> None:
        if not is_retail:
            return
        # Owned devices are attributed even without a PROFILE event (first boot, profile not yet registered).
        if not has_profile and current_device_owner != owner_user_id:
            return
        if session_profile_id:
            mapped_user = profile_map.get((current_device, session_profile_id))
            if mapped_user is not None and mapped_user != owner_user_id:
                return  # session belongs to a different OmniSave user
            if mapped_user is None and current_device_owner != owner_user_id:
                return  # unowned device, active profile unmapped — don't claim
        elif current_device_owner != owner_user_id:
            # has_profile via PROFILE_INACTIVE only, unowned device — skip
            return
        if application_id is None or session_app == application_id:
            for k, v in session_acc.items():
                accumulated[k] = accumulated.get(k, 0) + v

    def _open(app: str) -> None:
        nonlocal \
            state, \
            session_app, \
            has_profile, \
            session_profile_id, \
            session_acc, \
            focus_mono, \
            focus_wall, \
            is_retail
        state = "IN_SESSION"
        session_app = app
        has_profile = False
        session_profile_id = None
        session_acc = {}
        focus_mono = None
        focus_wall = None
        is_retail = is_retail_app_id(app, current_client_type)

    def _reset() -> None:
        nonlocal \
            state, \
            session_app, \
            has_profile, \
            session_profile_id, \
            session_acc, \
            focus_mono, \
            focus_wall, \
            prev_mono, \
            is_retail
        state = "IDLE"
        session_app = ""
        has_profile = False
        session_profile_id = None
        session_acc = {}
        focus_mono = None
        focus_wall = None
        prev_mono = None
        is_retail = True

    for row in rows:
        et = row["event_type"]
        device = row["device_id"]
        mono = row["monotonic_timestamp"]
        wall = row["event_timestamp"]
        app = row["application_id"] or ""
        raw_profile = row["profile_id"] or ""
        # Normalize to 16 chars: device_profile_map stores first 64 bits of the 128-bit UID
        profile_id_normalized = raw_profile[:16] if raw_profile else None

        if device != prev_device:
            _reset()
            prev_device = device
            current_device = device
            current_client_type = device_client_type.get(device, "")

        current_device_owner = row["device_owner"]

        # Strict backward mono = reboot boundary; emit completed intervals before
        # discarding state so already-computed FOCUSED→UNFOCUSED durations are kept.
        if prev_mono is not None and mono < prev_mono:
            _emit()
            _reset()

        prev_mono = mono

        if state == "IDLE":
            if et == "APPLICATION_STARTED":
                _open(app)

        elif state == "IN_SESSION":
            if et == "APPLICATION_STARTED":
                _emit()
                _open(app)
            elif et in ("PROFILE_ACTIVE", "PROFILE_INACTIVE"):
                has_profile = True
                if et == "PROFILE_ACTIVE" and profile_id_normalized:
                    session_profile_id = profile_id_normalized  # latest wins
            elif et == "APPLICATION_FOCUSED":
                focus_mono = mono
                focus_wall = wall
                state = "FOCUSED"
            elif et == "APPLICATION_EXITED":
                _emit()
                _reset()

        elif state == "FOCUSED":
            if et == "APPLICATION_FOCUSED":
                focus_mono = mono
                focus_wall = wall
            elif et in ("PROFILE_ACTIVE", "PROFILE_INACTIVE"):
                has_profile = True
                if et == "PROFILE_ACTIVE" and profile_id_normalized:
                    session_profile_id = profile_id_normalized  # latest wins
            elif et == "APPLICATION_UNFOCUSED":
                dur = mono - (focus_mono or mono)
                if dur > 0 and focus_wall is not None:
                    # Local time intentional: server TZ (set via TZ env var) matches the
                    # user's timezone so heatmap cells align with the user's calendar day.
                    # The frontend also uses local dates (new Date(), toLocaleDateString).
                    date = datetime.fromtimestamp(focus_wall).strftime("%Y-%m-%d")
                    key = (date, session_app)
                    session_acc[key] = session_acc.get(key, 0) + dur
                focus_mono = None
                focus_wall = None
                state = "IN_SESSION"
                # Consecutive UNFOCUSED in IN_SESSION are no-ops — no special handling needed
            elif et == "APPLICATION_STARTED":
                focus_mono = None
                focus_wall = None
                _emit()
                _open(app)
            elif et == "APPLICATION_EXITED":
                focus_mono = None
                focus_wall = None
                _emit()
                _reset()

    # Open sessions (no EXITED received) are not emitted per the contract

    if not accumulated:
        return []

    days_sec: dict[str, int] = {}
    days_games: dict[str, dict[str, int]] = {}
    for (date, app_id), secs in accumulated.items():
        days_sec[date] = days_sec.get(date, 0) + secs
        if date not in days_games:
            days_games[date] = {}
        days_games[date][app_id] = days_games[date].get(app_id, 0) + secs

    result = []
    for date in sorted(days_sec):
        games = [
            {
                "title_id": app_id,
                "display_name": app_id,
                "total_sec": secs,
                "minutes": secs // 60,
            }
            for app_id, secs in sorted(days_games[date].items(), key=lambda x: -x[1])
        ]
        secs = days_sec[date]
        result.append(
            {"date": date, "minutes": max(1, secs // 60) if secs > 0 else 0, "games": games}
        )
    return result


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
