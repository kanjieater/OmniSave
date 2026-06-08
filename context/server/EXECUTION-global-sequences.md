# Execution: Cloud Save System — Lossless Archive + Silent Safety Layer

## Database Changes
- [ ] Migration in `database.py` `open_db()`: create `snapshot_counters_new (title_id TEXT PRIMARY KEY, counter INTEGER NOT NULL DEFAULT 0)`, seed with `SELECT title_id, MAX(counter) FROM snapshot_counters GROUP BY title_id`, drop old table, rename
- [ ] Migration in `database.py` `open_db()`: create `device_title_head (title_id TEXT NOT NULL, device_id TEXT NOT NULL, last_seq INTEGER NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (title_id, device_id))`
- [ ] Add `next_global_sequence(conn, title_id: str) -> int` — upsert-increment `snapshot_counters` with no `device_id`
- [ ] Add `upsert_device_title_head(conn, title_id: str, device_id: str, seq: int) -> None`
- [ ] Add `get_device_last_seq(conn, title_id: str, device_id: str) -> int | None`
- [ ] `has_conflict` column kept; add schema comment: "diagnostic telemetry only — never controls behavior, never shown to user"

## Sync API Changes
- [ ] Replace `db.next_device_sequence(_conn, txn["title_id"], device_id)` with `db.next_global_sequence(_conn, txn["title_id"])` in `sync_api.py` commit handler
- [ ] Add `preservation: bool = False` to `InboundBody` in `sync_api.py`; store on the transaction (via new `preservation` column — add migration, default 0)

## Processing Logic Changes
- [ ] Replace `db.next_device_sequence(...)` with `db.next_global_sequence(...)` in `processing.py` `ingest_direct()`
- [ ] Wrap from `get_head_sequence` through `finalize_inbound` + `upsert_device_title_head` in `BEGIN IMMEDIATE` / `conn.commit()` in `_process()`
- [ ] Remove all logic that sets `has_conflict = True` based on parent/head comparison; replace with telemetry-only: if `device_last_seq is not None and device_last_seq < head_seq` → `log.warning("DIAG_DIVERGENCE ...")` only; always pass `has_conflict=0` to `finalize_inbound`. **Invariant: divergence is emitted as telemetry only — no branching, no retries, no rejection.**
- [ ] Dedup path: before `complete_dedup_transaction`, query existing `snapshot_sequence` for matching sha256+title_id and `UPDATE sync_transactions SET snapshot_sequence=<existing> WHERE transaction_id=?` — same hash always carries same sequence number
- [ ] After `finalize_inbound` (non-preservation): call `db.upsert_device_title_head(conn, title_id, source_device, seq)`. **Invariant: HEAD always advances on every successful non-preservation snapshot insertion.**
- [ ] Preservation path: if `txn["preservation"]`: after archiving and hashing, skip peer fanout and `push_async`; do NOT call `upsert_device_title_head` (HEAD is unchanged); log `PRESERVE_STORED seq=<seq>`. **Preservation uploads never affect HEAD.**

## Server Changes
- [ ] In `sync_deliver_api.py` ACK: after `complete_outbound()`, call `db.upsert_device_title_head(_conn, txn["title_id"], device_id, txn["snapshot_sequence"])`
- [ ] In `startup.py` `hard_delete_old_failed()`: add comment — "Only FAILED transactions (never completed processing) are eligible for GC. All transactions that reached READY_FOR_RESTORE or later are retained permanently unless user explicitly deletes."

## UI Changes
- [x] In `ui_api.py` `_game_status()`: remove `CONFLICT` return path — count conflicts is kept for telemetry but never returned to UI; return only `NO_DATA`, `SYNCED`, `ERROR`
- [x] In `GamePage.tsx`: remove conflict banner block and `ConflictWorkspace` modal trigger from primary page flow
- [x] In `GamePage.tsx` `HistoryTab`: all snapshots (any state, any `has_conflict` value) render in flat timeline with Push button — no filtering by conflict flag

## Sysmodule Changes
- [x] In `state.cpp`: verify `state_write_last_restore` receives the server-assigned `snapshot_counter` from delivery metadata — fix if it receives 0 or a locally computed value
- [x] In `fsm.cpp` `do_delivering()`: add pre-restore preservation as a **blocking FSM pre-step** before any delivery write to partition. **Invariant: no delivery may proceed until preservation upload completes or is confirmed unnecessary.** Steps: (1) `save_extract` detects local change via CRC32 fingerprint, (2) if different: call `transport_upload(..., preservation=true)` — block until server confirms receipt, log `PRESERVE_OK` on success or `PRESERVE_FAIL` on error (do NOT proceed with delivery on PRESERVE_FAIL, FSM stays DELIVERING), (3) apply delivery, (4) call `state_write_last_restore` with delivery's global sequence. `transport_upload.cpp` extended with `bool preservation` param that injects `"preservation":true` into the inbound POST body.

## Test Changes
- [x] `test_global_sequence_increments_across_devices` — OG upload → seq=1; Lite upload same title → seq=2; both distinct, both archives on disk
- [x] `test_dedup_preserves_sequence_number` — same bytes twice from different devices → both rows have identical `snapshot_sequence`
- [x] `test_every_unique_upload_is_stored` — two uploads, different hashes → both `snapshot_path` files exist, both rows in DB, `has_conflict=0` on both
- [x] `test_preservation_upload_does_not_advance_head` — inbound with `preservation=True` → HEAD sequence unchanged, no outbound created, archive file exists
- [x] **Incident regression** `test_parallel_upload_no_data_loss` — OG uploads (seq=N), Lite uploads (seq=N+1), both archives exist on disk, `has_conflict=0` on both rows
- [x] `test_divergence_is_logged_not_blocked` — upload when `device_last_seq < head_seq` → transaction completes to READY_FOR_RESTORE, archive exists, `has_conflict=0`
- [x] Update `test_properties.py` `test_conflict_detection_is_correct`: new invariant is `has_conflict=0` always; divergence is telemetry only
- [x] `docker compose run --rm test` — all tests pass, diff-cover ≥ 95%

## Migration / Rollout
- [x] `docker compose run --rm test` baseline before any changes
- [x] Deploy server `./scripts/server.sh up` — verify via `./scripts/db.sh "SELECT title_id, counter FROM snapshot_counters"` (one row per title, no device_id column) and `device_title_head` table exists
- [x] Build and deploy sysmodule `./deploy.sh` — binary built clean; FTP deploy pending (switches offline)
- [ ] Post-deploy: fetch both switch logs and confirm `PRESERVE_OK` events appear on delivery with differing local save
