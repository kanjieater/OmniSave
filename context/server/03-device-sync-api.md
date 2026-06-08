# OmniSave V1: Device Sync API Specification

Protocol surface Switch Sysmodule uses. API = stateless actuator for SQLite state machine.

**Base URL:** `/api/v1/sync`
**Authentication:** All requests MUST include `X-Device-ID: <MAC_ADDRESS>`.
**Content Type:** `application/json` (unless uploading binary data).

---

## 0. Global Execution & State Invariants

Governs all endpoints, enforces physical correctness.

* **Transaction Ownership Binding:** Backend MUST reject (`403`) if `X-Device-ID` ≠ `source_device_id` (inbound) or `target_device_id` (outbound). Device cannot mutate/commit transaction it doesn't own.
* **Session 1:1 Binding:** `session_id` belongs to exactly one `transaction_id`. DB schema enforces `UNIQUE` on `upload_sessions.transaction_id`. Prevents chunk bleed + session reuse.
* **Snapshot Sequence Contract:** `snapshot_sequence` = atomic monotonically increasing int per `(title_id, source_device_id)`. MUST assign via serialized `UPDATE ... RETURNING` or atomic counter table in `PROCESSING` phase. Prevents duplicate seq IDs from parallel workers.
* **Filesystem & Crash Recovery Contract:** Chunk files immutable once written; overwrites forbidden. On boot: DB is truth. Physical chunk file with no `upload_chunks` row = orphan → deleted by startup routine.
* **Upload Timeout & Retention:** `UPLOADING` tx idle 12h → auto-`FAILED`. Physical files + DB rows retained 7 days in `FAILED` for recovery; background job hard-deletes after. `FAILED` session permanently locked.

---

## 1. Inbound Phase (Upload: Switch → Server)

### `POST /transactions/inbound`

Initiate save upload.

* **Request Body:**
```json
{
  "title_id": "0100F2C0115B6000",
  "total_size_bytes": 10485760,
  "chunk_size_bytes": 2097152,
  "hardware_type": "HEG-001"
}
