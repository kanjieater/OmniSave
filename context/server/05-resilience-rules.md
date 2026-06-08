OmniSave V1: Resilience & Failure Recovery Spec

SQLite = source of truth. Filesystem = untrusted shadow cache.

**1. Crash Recovery (Server Startup)**
On startup run reconciliation:
- Orphan Sweep: chunk file w/o `upload_chunks` row → delete
- Missing File Sweep: `upload_chunks` row w/o physical file → parent transaction → FAILED

**2. Idempotency Rules**
- `PUT /chunk/{index}`: `chunk_index` already registered → return 202, skip disk I/O. No overwrites.
- `POST /ack` (late): re-offer restore on next poll if ACK drops. Accept late ACKs if sequence nums match.
- `POST /commit` retry: transaction in PROCESSING/READY_FOR_RESTORE/COMPLETED → return 200, no action.

**3. Upload Timeout & Recovery**
- Cron every 15min: UPLOADING + `last_activity_at` > 12h → FAILED
- FAILED chunks/rows kept 7 days → hard-delete
- No "dead"/"locked" states. Transaction = active or FAILED.

**4. Conflict Detection & Lineage**
`POST /inbound` MUST include `parent_sequence_num`.
- `parent_sequence_num == head_sequence_num`: linear. Advance HEAD.
- `parent_sequence_num < head_sequence_num`: divergent. Archive upload, assign new seq num, set `has_conflict = true`, halt HEAD advancement. Surface to Level 2 UI for manual resolution (UI API only — device never resolves conflicts).

**5. Client Execution & Error Handling**
- `POST /fail` (inject_fail or any permanent error): transition READY_FOR_RESTORE → FAILED. Persists error_code in events.
- Error triggers UI Notification Bell. Client re-polls; server forks fresh outbound on next processing cycle.

**6. Storage Protection (507 Rule)**
- High-water: host volume > 95% → Read-Only mode.
- `POST /inbound`, `PUT /chunk` → 507 Insufficient Storage.
- Restores (`GET /queue`, `GET /download`) continue.
- Server status pinned to UI dashboard until Storage Pruner used.
