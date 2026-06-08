# OmniSave V1: Device Sync API Specification

This defines the strict protocol surface the Switch Sysmodule interacts with. The API acts as the stateless actuator for the SQLite state machine.

**Base URL:** `/api/v1/sync`
**Authentication:** All requests MUST include the header `X-Device-ID: <MAC_ADDRESS>`.
**Content Type:** `application/json` (unless uploading binary data).

---

## 0. Global Execution & State Invariants

These rules govern all API endpoints and enforce the physical correctness of the system.

* **Transaction Ownership Binding:** The backend MUST reject (`403 Forbidden`) any mutation request if `X-Device-ID` does not match the `source_device_id` (inbound) or `target_device_id` (outbound) of the transaction. A device cannot mutate or commit a transaction it does not own.
* **Session 1:1 Binding:** A `session_id` belongs to exactly one `transaction_id`. The database schema enforces a `UNIQUE` constraint on `upload_sessions.transaction_id` to prevent chunk bleed and session reuse across retries.
* **The Snapshot Sequence Contract:** `snapshot_sequence` is an atomic, monotonically increasing integer assigned to a game lineage per `(title_id, source_device_id)`. It MUST be assigned via a serialized `UPDATE ... RETURNING` or explicit atomic counter table during the `PROCESSING` phase to prevent parallel workers from generating duplicate sequence IDs.
* **Filesystem & Crash Recovery Contract:**
  * Chunk files are immutable once written. Overwrites of existing physical files are forbidden.
  * *Startup Reconciliation:* On server boot, the database is absolute truth. Any physical chunk file on disk that does not have a corresponding row in `upload_chunks` is strictly treated as an orphan and **deleted** by the startup routine to prevent storage leaks.
* **Upload Timeout & Retention:** Any `UPLOADING` transaction with no chunk activity for 12 hours is automatically transitioned to `FAILED`. Physical chunk files and DB rows are **retained for 7 days** in this `FAILED` state for recovery, after which a background job hard-deletes them. A `FAILED` session is permanently locked.

---

## 1. Inbound Phase (Upload: Switch → Server)

### `POST /transactions/inbound`

Initiates a new save data upload. Upserts `devices`, initializes `sync_transactions` (`state = 'UPLOADING'`) and `upload_sessions`.

* **Request Body:**
```json
{
  "title_id": "0100F2C0115B6000",
  "total_size_bytes": 10485760,
  "chunk_size_bytes": 2097152,
  "expected_total_chunks": 5,
  "hardware_type": "HEG-001",
  "parent_sequence_num": 42
}
```

`parent_sequence_num`: the sequence number of the snapshot the client last successfully synced. Send `null` on first boot or when `state/lineage.json` has no entry for this title+user — the server treats a null parent as an initial seed.

* **Response (201 Created):**
```json
{
  "transaction_id": "tx_abc123",
  "session_id": "sess_xyz789",
  "expected_total_chunks": 5
}
```

### `PUT /sessions/{session_id}/chunks/{chunk_index}`

Uploads a specific binary chunk. **Strictly Idempotent.**

* **Headers:** `Content-Type: application/octet-stream`
* **Request Body:** Raw binary bytes of the chunk.
* **Response (202 Accepted):** Empty body.
* **Backend Contract:**
  1. Write file to disk and guarantee OS-level physical durability (`fsync`) *before* acknowledging the DB.
  2. Idempotently register `chunk_index` and validate `chunk_size_bytes` in the `upload_chunks` table.
  3. Update session activity timestamp.

### `POST /sessions/{session_id}/commit`

Signals that the sysmodule has finished uploading all chunks.

* **Request Body:** Empty body.
* **Response (202 Accepted):** Upload accepted and moved to background processing.
* **Response (409 Conflict):** If the Completeness Gate fails.
* **Backend Contract (The Completeness Gate):**
  Executed entirely within a single exclusive database lock. The backend MUST verify contiguous completeness.
  **Completeness is strictly defined as:** contiguous chunk index coverage from `0` to `expected_total_chunks - 1`.
  1. If complete: Transition state to `PROCESSING` and commit.
  2. If incomplete: Rollback DB transaction, return `409 Conflict`, do not mutate state.

---

## 2. Processing Phase (Internal Server Logic)

*(Not a device-facing API, but the immutability contract here dictates safety for the Outbound Phase.)*

* **The Artifact Immutability Contract:** A transaction MUST NOT transition from `PROCESSING` to `READY_FOR_RESTORE` until its final canonical archive is fully materialized, written to disk, and the file descriptor safely closed. This guarantees that `GET /transactions/{id}/chunks/{n}` can never serve a partial or corrupted view of an archive mid-creation.

* **Conflict Detection (during `PROCESSING`):** The server evaluates `parent_sequence_num`:

| Condition | Result |
| --- | --- |
| `parent_sequence_num IS NULL` | Initial seed. Advance HEAD. |
| `parent_sequence_num == head_sequence_num` | Linear continuation. Advance HEAD. |
| `parent_sequence_num < head_sequence_num` | Divergent timeline. Archive upload, assign sequence, set `has_conflict = true`. Do NOT advance HEAD. |
| `parent_sequence_num` is invalid/nonexistent | `FAILED`. |

---

## 3. Outbound Phase (Restore: Server → Switch)

### `GET /queue`

The primary polling endpoint for pending restores. Returns all information needed to begin downloading — no separate claim step.

* **Response (200 OK):**
```json
{
  "pending": [
    {
      "transaction_id": "tx_def456",
      "title_id": "0100F2C0115B6000",
      "snapshot_sequence": 6,
      "total_bytes": 14500000,
      "checkpoint_ledger": [2547384827, 1839201945, 3094827163]
    }
  ]
}
```

* **Backend Contract:**
  1. Pure read — no state mutations of any kind.
  2. Queries and returns transactions where `target_device_id = X-Device-ID` and `state = 'READY_FOR_RESTORE'`.
  3. `checkpoint_ledger` is the xxHash32 array for the 4 MB checkpoint boundaries (used by the client for inline integrity validation during download).

### `GET /transactions/{transaction_id}/range`

Downloads a byte range of the canonical save payload. **Device-identity protected. Resumable.**

* **Query Parameters:** `?offset=0&length=67108864` (offset + length in bytes)
* **Response (200 OK):** Raw binary (`application/octet-stream`) for the requested byte range.
* **Response (403 Forbidden):** If `X-Device-ID` does not match `target_device_id`.
* **Response (404 Not Found):** If the transaction does not exist or is not `READY_FOR_RESTORE`.
* **Response (416 Range Not Satisfiable):** If the requested range exceeds `total_size_bytes`.
* **Backend Contract:** Validates `X-Device-ID` matches `target_device_id` before streaming. Bytes are served from the immutable archive. No state mutation occurs — reading is a side-effect-free operation.

### `POST /ack`

Confirms successful save injection. **Idempotent.**

* **Request Body:**
```json
{
  "transaction_id": "tx_def456"
}
```
* **Response (200 OK):** Empty body.
* **Backend Contract:**
  1. Validates `X-Device-ID` matches `target_device_id`.
  2. Atomically transitions `READY_FOR_RESTORE` → `COMPLETED`.
  3. If state is already `COMPLETED`, return `200 OK` (safely handles retried ACKs).
  4. If state is anything else, return `409`.

### `POST /fail`

Signals that the restore cannot be completed (permanent failure — inject failed, game not installed, etc.).

* **Request Body:** `{"transaction_id": "tx_def456", "error_code": "inject_fail"}`
* **Response (200 OK):** Empty body.
* **Backend Contract:** Validates `X-Device-ID`. Transitions `READY_FOR_RESTORE` → `FAILED`. Idempotent if already `FAILED`. Persists `error_code` in the events log.

---

## 4. Execution Semantics (Concurrency Rules)

* **The Single Writer Invariant (`BEGIN IMMEDIATE`):** Only one writer may transition a transaction state at a time. Any endpoint that evaluates conditions to transition state (`POST /sessions/{id}/commit`, `POST /ack`, `POST /fail`) MUST execute within an exclusive database lock. If two overlapping requests hit, the DB serializes them.
* **Parallel Chunk Concurrency:** Chunk writes are commutative and do not block state evaluations. `PUT /sessions/{id}/chunks/{n}` endpoints do not require exclusive locks over the transaction. They utilize row-level upserts on the `upload_chunks` table, allowing high-speed parallel uploads without bottlenecking SQLite.
* **Read Isolation (`BEGIN DEFERRED`):** Reads must never return partial state transitions. Endpoints like `GET /queue` MUST execute within a read transaction to ensure a consistent snapshot.
