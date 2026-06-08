Monotonic snapshot sequence per game per device scope — not global save graph.

## Correct model for OmniSave V1

### 1. Single concept: `snapshot_sequence`

Drop: branches, save names, DAGs, timestamps-as-identity.

Each successful commit produces incrementing integer per (title_id, device scope).

---

## 2. What it should be

Add to `sync_transactions`:

```sql
snapshot_sequence INTEGER NOT NULL
```

Better — new table (recommended):

```sql
CREATE TABLE snapshot_counters (
    title_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    counter INTEGER NOT NULL,
    PRIMARY KEY (title_id, device_id)
);
```

---

## 3. How it works

On inbound commit (upload success), when save becomes `PROCESSING → READY_FOR_RESTORE`:

```sql
UPDATE snapshot_counters
SET counter = counter + 1
WHERE title_id = ? AND device_id = ?;
```

Assign `snapshot_sequence = counter`. Snapshot = "Mario Kart 8 Deluxe – Save #6 (on this device lineage)"

---

## 4. Why this works

Not modeling: branching histories, multi-restore trees, user-defined save slots.

Modeling: linear progression of backups per game per ecosystem.

---

## 5. Scope decision (critical)

### Option A (recommended for V1) — counter per `(title_id, device_id)`

Each Switch has own snapshot history per game. Restores contextual to device lineage.

### Option B (harder) — counter per `(title_id only)`

All devices share single timeline per game. Gets messy with multiple users, conflicting restores, divergence.

---

## 6. UI implication

Clean labels: "Save #1", "Save #2", "Save #3" — optionally `Save #6 (From Switch OLED)`. No hashes, no timestamps.

---

## 7. Key insight

Deterministic backup ledger, not version control. No branching IDs, no graph model, just per-key counter.

---

## Bottom line

Correct instinct. Benefits: immediate UX improvement, no restore confusion, deterministic ordering, avoids timestamp sort bugs.

Follow-up: how `snapshot_sequence` interacts with "best save per game" selection on restore UI.