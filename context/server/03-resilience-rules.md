These six additions are the exact bolts needed to lock the state machine down completely. They close the final "implementation trapdoors" where a developer might be forced to invent logic on the fly—which is exactly where silent corruption usually creeps in.

Here is the final, hardened **OmniSave V1: Resilience & Failure Recovery Spec (`05-resilience-rules.md`)**, fully integrated with these explicit invariants.

---

# OmniSave V1: Resilience & Failure Recovery Spec

This specification defines the deterministic rules for handling failures, concurrency, corruption, and transport instability. The goal is to preserve data integrity while keeping the synchronization pipeline restartable and idempotent.

---

## 1. State & Crash Recovery (Boot Rules)

The SQLite database is the absolute source of truth. The filesystem is treated as an untrusted binary cache. On application startup, before binding the HTTP listener, the backend MUST execute a synchronous reconciliation pass.

### 1.1 Source of Truth Declaration

Authority ordering is strict:

1. SQLite transactional state
2. Physical chunk files on disk
3. Client-reported transient state

Filesystem state MUST NEVER override database state.

### 1.2 Orphan Cleanup

If a physical chunk file exists on disk but no corresponding row exists in `upload_chunks`:

* Delete the file immediately.
* Do not attempt recovery or reinsertion.

### 1.3 Missing File Sweep

If a row exists in `upload_chunks` but the physical file is missing:

* Transition the parent `sync_transaction` to `FAILED`.
* Mark the transaction unrecoverable.
* Surface a diagnostic event in `/events`.
* The system MUST NOT attempt partial reconstruction.

### 1.4 In-Flight Reset Rules

Any ephemeral execution state MUST be reset on boot.

| Previous State | Recovery Action |
| --- | --- |
| `PROCESSING` | Recovery is only permitted if all required chunks are present and the transaction can be deterministically resumed without ambiguity. Otherwise, the transaction MUST transition to `FAILED`. |

There are no lease or DELIVERING states to reset; the state machine has no ephemeral ownership tokens.

---

## 2. Network & Transport Idempotency (Retry Rules)

Clients are expected to retry requests aggressively due to unstable Wi-Fi. The backend MUST safely absorb duplicate traffic without mutating state multiple times.

### 2.1 Chunk Upload Idempotency

**Endpoint:** `PUT /chunk/{index}`
If `chunk_index` is already registered for the `transaction_id`:

* Return `202 Accepted`
* Skip all disk I/O and hash recalculation.
* Chunk overwrites are strictly forbidden.

### 2.2 ACK Idempotency

**Endpoint:** `POST /ack`
A restore ACK MUST only be accepted from the device that owns the transaction (`X-Device-ID` must match `target_device_id`).

The server MUST accept late/retried ACKs and return `200 OK` without further mutation if:

* The `transaction_id` matches.
* The current state is already `COMPLETED`.

### 2.3 Commit Safety & Integrity Verification

**Endpoint:** `POST /commit`

* **Integrity Boundary:** Before transitioning from `UPLOADING` to `PROCESSING`, the backend MUST verify that all expected chunks are present and match the declared upload manifest.
* **Idempotency:** If a retry occurs after the transaction already entered `PROCESSING`, `READY_FOR_RESTORE`, or `COMPLETED`, the server MUST return `200 OK` and perform no additional work.

### 2.4 Duplicate Poll Safety & Consistency

* **Idempotency:** Repeated polling requests from unstable clients MUST NOT generate duplicate outbound transactions or mutate queue ordering.
* **Consistency Rule:** Polling endpoints MUST expose only committed transactional state. Partially processed or intermediate transitions MUST NEVER be externally visible.

---

## 3. Resource & Capacity Limits (Garbage Collection Rules)

### 3.1 Zombie Upload Timeouts

A background cleanup task runs every 15 minutes. Any transaction in `UPLOADING` where `last_activity_at > 12 hours` MUST transition atomically to `FAILED`. The session becomes invalid permanently.

### 3.2 Failed Transaction Retention

Failed uploads are quarantined temporarily for diagnostics. Both `FAILED` transaction metadata and physical chunk files are retained for **7 days**. After expiration, DB rows and physical files are hard-deleted.

### 3.3 Dead Session Recovery

If a client attempts to resume a `FAILED` upload session, the server MUST return `403 Forbidden` and require a completely new `/inbound` transaction.

### 3.4 Storage High-Water Protection & Recovery

Before accepting uploads, the server checks host disk utilization.

* **Lock:** If utilization exceeds **95%**, the server enters global Read-Only mode and rejects new uploads with `507 Insufficient Storage`. (Restores and queue polling remain allowed).
* **Recovery:** The server MUST automatically exit Read-Only mode once disk usage falls below the high-water mark. No restart or manual administrative action is required.

---

## 4. Concurrency & Race Conditions (Locking Rules)

### 4.1 Single-Writer Invariant & Atomic Transitions

All state transitions that modify transaction state, snapshot lineage, or global HEAD assignment MUST execute under a single atomic database transaction (`BEGIN IMMEDIATE` or equivalent).

**Exclusive Transition Operations (Require Locks):**

* Assigning `snapshot_sequence`
* Advancing `head_sequence_num`
* Conflict evaluation
* Restore ACK completion

**Parallel-Safe Operations (No Exclusive Locks):**

* Chunk uploads and existence checks
* Polling endpoints
* Dashboard and event log reads

### 4.2 HEAD Invariance

For a given `title_id`, exactly ONE snapshot may be designated as the active HEAD at any time. The backend MUST guarantee this invariant atomically. The system MUST NEVER expose an intermediate state where multiple HEADs exist or no HEAD exists after initialization.

---

## 5. Client & Physical World Failures (Execution Blocks)

### 5.1 Execution Failures

If a client cannot execute a restore (game running, storage full), it reports the failure via `POST /fail`:

* The transaction transitions to `FAILED` permanently (the client must re-poll for a fresh outbound transaction on next tick).
* The raw error payload MUST be persisted in the events log for diagnostics.
* The UI Notification Bell MUST surface the failure.

There are no transient "revert to READY_FOR_RESTORE" paths — the server is stateless with respect to client execution blocks. If a restore cannot proceed, the client re-polls and the server forks a new outbound transaction.

### 5.2 Unknown Error Handling

If a device reports an unknown or unsupported error code:

* The transaction MUST transition to `FAILED`.
* The raw error payload MUST be persisted for diagnostics.
* The UI Notification Bell MUST surface a generic device failure notification.
* The server MUST fail safely rather than assuming recoverability semantics.

### 5.3 Divergent Reality (Conflict Detection)

The system deterministically identifies divergent offline timelines. `POST /inbound` MUST include `parent_sequence_num`.

**Conflict Evaluation (During `PROCESSING`):**

| Condition | Result |
| --- | --- |
| `head_sequence_num IS NULL` | Initial seed (Linear). Advance HEAD. |
| `parent_sequence_num == head_sequence_num` | Linear continuation. Advance HEAD. |
| `parent_sequence_num < head_sequence_num` | Divergent timeline. |
| `parent_sequence_num` is invalid/nonexistent | Invalid Lineage. |

**Conflict Handling Rules:**

* **If Divergence is Detected:** Fully process and archive the upload, assign a new sequence number, set `has_conflict = true`, and DO NOT advance global HEAD. Emit a Level 2 UI conflict exception and wait for explicit user action.
* **If Invalid Lineage is Detected:** The upload MUST transition to `FAILED` and MUST NOT advance HEAD.

---

## 6. Deterministic State Machine Guarantees

### 6.1 Snapshot Immutability

Once a snapshot has been assigned a `snapshot_sequence` and committed:

* Its binary data MUST NEVER be modified.
* Its lineage metadata MUST NEVER be rewritten.
* HEAD assignment may change, but the snapshot history itself is strictly immutable.

### 6.2 Convergence Guarantees

The synchronization pipeline MUST remain restartable and deterministic under all failure conditions. The system guarantees:

* No silent overwrite behavior.
* No duplicate HEAD advancement.
* No partial restore commitment.
* No automatic conflict resolution.
* No ephemeral ownership state of any kind.

All failure handling MUST converge back toward `READY_FOR_RESTORE`, `FAILED`, or `COMPLETED`. No hidden intermediary states may exist outside the documented state machine.