OmniSave V1: Database Specification (SQLite)
1. devices
The human-first identity model. Hardware MACs remain the primary key, but the UI only interacts with display_name.

SQL


CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    hardware_type TEXT,
    last_seen TEXT NOT NULL,
    created_at TEXT NOT NULL
);
2. sync_transactions
The absolute source of truth for all save data movement. Files on disk do not dictate state.

SQL


CREATE TABLE sync_transactions (
    transaction_id TEXT PRIMARY KEY,
    title_id TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
    state TEXT NOT NULL,
    target_device_id TEXT,
    snapshot_sequence INTEGER,
    parent_sequence_num INTEGER,  -- NULL on first-boot seed; set by client from state/lineage.json
    has_conflict INTEGER NOT NULL DEFAULT 0,  -- 1 if PROCESSING detected divergent timeline
    sha256 TEXT,
    snapshot_path TEXT,
    total_size_bytes INTEGER,
    checkpoint_ledger TEXT,       -- V2: JSON uint32 array; set after processing
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (source_device_id) REFERENCES devices(device_id),
    FOREIGN KEY (target_device_id) REFERENCES devices(device_id)
);

-- PHYSICS CONSTRAINT: Outbound Uniqueness
-- At most one active outbound per (device, title) pair.
-- Downloads are read-only; the uniqueness constraint prevents duplicate delivery, not concurrent reads.
CREATE UNIQUE INDEX uniq_active_outbound_per_device_title
ON sync_transactions(target_device_id, title_id)
WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE';
3. upload_sessions
The durability tracking for inbound transfers. This isolates physical file tracking from the logical state machine and allows for safe garbage collection of orphaned uploads.

SQL


CREATE TABLE upload_sessions (
    session_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    session_state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(session_state IN ('ACTIVE', 'COMPLETED', 'FAILED', 'ABORTED')),
    total_size_bytes INTEGER NOT NULL,
    chunk_size_bytes INTEGER NOT NULL,
    expected_total_chunks INTEGER NOT NULL,
    last_active_at TEXT NOT NULL,
    
    FOREIGN KEY (transaction_id) REFERENCES sync_transactions(transaction_id)
);
4. upload_chunks
Guarantees idempotent writes at the database level, catches partial writes early, and eliminates row-locking contention during high-speed parallel chunk uploads.

SQL


CREATE TABLE upload_chunks (
    session_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_size_bytes INTEGER NOT NULL, -- PHYSICS CONSTRAINT: Integrity guard against partial/truncated chunk writes
    
    PRIMARY KEY (session_id, chunk_index),
    FOREIGN KEY (session_id) REFERENCES upload_sessions(session_id)
);
Implementation Note for the Application Layer (FastAPI)
Because we removed the complex SQL-based guard clauses to avoid overengineering the database, your backend application is now responsible for the Completeness Gate.

When the sysmodule hits POST /commit, the Python backend must execute the following logic within a standard DB transaction:

Count & Validate: Query upload_chunks to ensure COUNT(chunk_index) == expected_total_chunks.

State Check: Ensure upload_sessions.session_state == 'ACTIVE' and sync_transactions.state == 'UPLOADING'.

Execute Transition: If true, update the transaction to PROCESSING and the session to COMPLETED. If false, rollback the DB transaction and return a 409 Conflict (or 400 Bad Request) to the sysmodule.