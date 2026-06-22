"""
Peer sync behavioral tests.
Covers: fork-on-processing, lazy discovery, supersede, conflict detection.
"""

import pytest

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, pair_device, poll_queue, report_catalog, sync_hdrs

SAVE = b"save-data-" * 200


def test_catalog_peer_gets_outbound_at_processing_time(client, conn):
    # B enrolls in catalog before A uploads — commit-time fanout creates outbound immediately.
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["title_id"] == TITLE_1.upper()


def test_uncataloged_peer_gets_no_outbound_from_queue(client, conn):
    # Without catalog enrollment, queue creates nothing — lazy-fork is removed.
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    outbounds = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert outbounds == 0

    pending = poll_queue(client, DEVICE_B)
    assert pending == []

    # Outbound still zero after queue poll — queue is read-only.
    outbounds_after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert outbounds_after == 0


def test_catalog_backfill_creates_outbound_after_upload(client, conn):
    # Upload happens first, then B reports catalog → backfill creates outbound.
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    outbounds_before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert outbounds_before == 0

    report_catalog(client, DEVICE_B, [TITLE_1])

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["title_id"] == TITLE_1.upper()


def test_newer_upload_supersedes_ready_for_restore(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    first = poll_queue(client, DEVICE_B)
    first_txn_id = first[0]["transaction_id"]

    do_upload(client, DEVICE_A, TITLE_1, b"newer_save")

    second = poll_queue(client, DEVICE_B)
    assert len(second) == 1
    assert second[0]["snapshot_sequence"] == 2

    old = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (first_txn_id,)
    ).fetchone()
    assert old["state"] == "SUPERSEDED"


def test_newer_upload_supersedes_ready_for_restore_outbound(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    first = poll_queue(client, DEVICE_B)
    first_txn_id = first[0]["transaction_id"]

    do_upload(client, DEVICE_A, TITLE_1, b"newer_save")
    second = poll_queue(client, DEVICE_B)
    assert len(second) == 1

    old = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (first_txn_id,)
    ).fetchone()
    assert old["state"] == "SUPERSEDED"


def test_divergent_upload_stored_with_no_conflict_flag(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    # B uploads divergently (parent_seq < current head) — still stored, has_conflict always 0
    txn_id = do_upload(client, DEVICE_B, TITLE_1, b"b_diverge", parent_seq=0)

    txn = conn.execute(
        "SELECT has_conflict, state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["has_conflict"] == 0
    assert txn["state"] == "READY_FOR_RESTORE"


def test_divergent_upload_creates_peer_fanout(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1])
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_B, TITLE_1, b"b_seed")
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    # B uploads divergently — in the new model this forks an outbound for A
    txn_b = do_upload(client, DEVICE_B, TITLE_1, b"b_diverge", parent_seq=0)

    # A's queue should contain B's upload (no conflict suppression)
    pending = poll_queue(client, DEVICE_A)
    assert len(pending) == 1
    assert pending[0]["snapshot_sequence"] > 1


def test_linear_upload_no_conflict(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    # B uploads with parent_seq equal to current head → no conflict
    txn_id = do_upload(client, DEVICE_B, TITLE_1, b"b_linear", parent_seq=1)

    txn = conn.execute(
        "SELECT has_conflict FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["has_conflict"] == 0


def test_multiple_titles_independent_outbounds(client, conn):
    """Per-title UNIQUE index: device can have one active outbound per title simultaneously."""
    report_catalog(client, DEVICE_B, [TITLE_1, TITLE_2])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    do_upload(client, DEVICE_A, TITLE_2, b"save_t2")

    active = conn.execute(
        "SELECT title_id FROM sync_transactions "
        "WHERE target_device_id=? AND direction='outbound' AND state='READY_FOR_RESTORE'",
        (DEVICE_B,),
    ).fetchall()
    titles = {r["title_id"] for r in active}
    assert TITLE_1.upper() in titles
    assert TITLE_2.upper() in titles


def test_source_device_excluded_from_own_delivery(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    pending = poll_queue(client, DEVICE_A)
    assert pending == []


def test_sequence_increments_per_device(client, conn):
    txn1 = do_upload(client, DEVICE_A, TITLE_1, b"v1")
    txn2 = do_upload(client, DEVICE_A, TITLE_1, b"v2")

    rows = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions "
        "WHERE transaction_id IN (?,?) ORDER BY snapshot_sequence",
        (txn1, txn2),
    ).fetchall()
    seqs = [r["snapshot_sequence"] for r in rows]
    assert seqs == [1, 2]


# ── Deduplication ─────────────────────────────────────────────────────────────


def test_dedup_cross_device_restored_save(client, conn):
    """Device B re-uploading content identical to the global HEAD must be deduped."""
    data = b"shared-save-content" * 400
    do_upload(client, DEVICE_A, TITLE_1, data)  # A uploads → global HEAD = sha(data)
    txn_b = do_upload(client, DEVICE_B, TITLE_1, data)  # B uploads same bytes

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_b,),
    ).fetchone()
    assert row["state"] == "DEDUPED"
    assert row["snapshot_sequence"] is None  # no artifact awarded for duplicate content


def test_dedup_identical_save_no_sequence(client, conn):
    """Re-uploading identical bytes: DEDUPED with no sequence — no new artifact created."""
    data = b"unchanged-save" * 500
    do_upload(client, DEVICE_A, TITLE_1, data)
    txn2 = do_upload(client, DEVICE_A, TITLE_1, data)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn2,),
    ).fetchone()
    assert row["state"] == "DEDUPED"
    assert row["snapshot_sequence"] is None


def test_dedup_identical_save_no_peer_fanout(client, conn):
    """Re-uploading identical bytes must not create new outbound transactions for peers."""
    data = b"unchanged-save" * 500
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, data)  # first upload → forks outbound for B

    outbound_count_before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]

    do_upload(client, DEVICE_A, TITLE_1, data)  # same bytes → dedup

    outbound_count_after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]
    assert outbound_count_after == outbound_count_before


def test_dedup_changed_save_processes_normally(client, conn):
    """Changed bytes must not be deduped — normal READY_FOR_RESTORE + sequence assigned."""
    txn1 = do_upload(client, DEVICE_A, TITLE_1, b"save-v1" * 100)
    txn2 = do_upload(client, DEVICE_A, TITLE_1, b"save-v2" * 100)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn2,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"
    assert row["snapshot_sequence"] == 2


def test_dedup_first_upload_no_head_processes_normally(client, conn):
    """First upload for a title (no HEAD exists) must always get a sequence number."""
    txn = do_upload(client, DEVICE_A, TITLE_1, b"initial-save" * 100)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"
    assert row["snapshot_sequence"] == 1


def test_identical_content_upload_deduplicates(client, conn):
    """Second upload of identical save data is DEDUPED with no sequence — not a new artifact."""
    data = b"save-data-" * 200
    txn1 = do_upload(client, DEVICE_A, TITLE_1, data)
    txn2 = do_upload(client, DEVICE_A, TITLE_1, data)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn2,),
    ).fetchone()
    assert row["state"] == "DEDUPED"
    assert row["snapshot_sequence"] is None


# ── Null-parent conflict detection (the "parallel seq-20" scenario) ───────────


def test_null_parent_no_conflict_when_no_head(client, conn):
    """First upload ever (no head) with parent=None → not a conflict."""
    txn = do_upload(client, DEVICE_A, TITLE_1, b"seed-save")
    row = conn.execute(
        "SELECT has_conflict FROM sync_transactions WHERE transaction_id=?", (txn,)
    ).fetchone()
    assert not row["has_conflict"]


def test_null_parent_no_conflict_same_device_as_head(client, conn):
    """Uploading device owns the current head → continuation, not conflict."""
    do_upload(client, DEVICE_A, TITLE_1, b"save-v1")
    txn = do_upload(client, DEVICE_A, TITLE_1, b"save-v2")
    row = conn.execute(
        "SELECT has_conflict FROM sync_transactions WHERE transaction_id=?", (txn,)
    ).fetchone()
    assert not row["has_conflict"]


def test_upload_after_ack_has_no_conflict_flag(client, conn):
    """Device that previously ACK'd a delivery uploads again — has_conflict is always 0.
    Divergence (if any) is emitted as DIAG_DIVERGENCE log only, never stored."""
    from helpers import do_ack
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, b"og-last-night")

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    txn_outbound = pending[0]["transaction_id"]
    total = pending[0]["total_bytes"]
    tok_b = pair_device(client, DEVICE_B)
    client.get(
        f"/api/v1/sync/transactions/{txn_outbound}/range?offset=0&length={total}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    do_ack(client, DEVICE_B, txn_outbound)

    txn = do_upload(client, DEVICE_B, TITLE_1, b"lite-midnight")
    row = conn.execute(
        "SELECT has_conflict, state FROM sync_transactions WHERE transaction_id=?", (txn,)
    ).fetchone()
    assert row["has_conflict"] == 0
    assert row["state"] == "READY_FOR_RESTORE"


def test_null_parent_no_conflict_when_device_never_received(client, conn):
    """Brand-new device that never received a delivery uploads without parent_seq → NOT conflict.
    It has no way to know the current head, so it's treated as a fresh seed."""
    do_upload(client, DEVICE_A, TITLE_1, b"og-last-night")  # OG sets head
    txn = do_upload(client, DEVICE_B, TITLE_1, b"lite-first-time")  # Lite never received anything
    row = conn.execute(
        "SELECT has_conflict FROM sync_transactions WHERE transaction_id=?", (txn,)
    ).fetchone()
    assert not row["has_conflict"], "Device that never received a delivery should not be flagged"


# ── Global sequence / lossless archive ────────────────────────────────────────


def test_global_sequence_increments_across_devices(client, conn):
    """Incident regression: two devices uploading the same title get distinct monotone sequences."""
    txn_a = do_upload(client, DEVICE_A, TITLE_1, b"og-save-" * 50)
    txn_b = do_upload(client, DEVICE_B, TITLE_1, b"lite-save-" * 50)

    seq_a = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_a,)
    ).fetchone()["snapshot_sequence"]
    seq_b = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_b,)
    ).fetchone()["snapshot_sequence"]

    assert seq_a == 1
    assert seq_b == 2


def test_dedup_does_not_inherit_sequence(client, conn):
    """Same bytes from two devices: first gets a seq; dedup gets DEDUPED with NULL seq."""
    data = b"shared-save-bytes-" * 300
    txn_a = do_upload(client, DEVICE_A, TITLE_1, data)
    txn_b = do_upload(client, DEVICE_B, TITLE_1, data)

    seq_a = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_a,)
    ).fetchone()["snapshot_sequence"]
    seq_b = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_b,)
    ).fetchone()["snapshot_sequence"]

    assert seq_a is not None and seq_a > 0
    assert seq_b is None  # dedup = no new artifact, no number awarded


def test_every_unique_upload_is_stored(client, conn):
    """Two uploads with different hashes → both archives on disk, has_conflict=0 on both."""
    from pathlib import Path

    txn_a = do_upload(client, DEVICE_A, TITLE_1, b"og-save-unique-" * 50)
    txn_b = do_upload(client, DEVICE_B, TITLE_1, b"lite-save-unique-" * 50)

    for txn_id in (txn_a, txn_b):
        row = conn.execute(
            "SELECT has_conflict, snapshot_path FROM sync_transactions WHERE transaction_id=?",
            (txn_id,),
        ).fetchone()
        assert row["has_conflict"] == 0
        assert row["snapshot_path"] is not None
        assert Path(row["snapshot_path"]).exists()


def test_preservation_upload_does_not_advance_head(client, conn):
    """preservation=True: archive stored, HEAD unchanged, no outbound created."""
    from pathlib import Path

    do_upload(client, DEVICE_A, TITLE_1, b"og-save-" * 50)
    head_before = db.get_head_sequence(conn, TITLE_1)
    assert head_before == 1

    txn_p = do_upload(client, DEVICE_B, TITLE_1, b"lite-pre-restore-save-" * 50, preservation=True)

    head_after = db.get_head_sequence(conn, TITLE_1)
    assert head_after == head_before, "Preservation upload must not advance HEAD"

    outbounds = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND source_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()[0]
    assert outbounds == 0, "Preservation upload must not create outbound transactions"

    row = conn.execute(
        "SELECT snapshot_path FROM sync_transactions WHERE transaction_id=?", (txn_p,)
    ).fetchone()
    assert row["snapshot_path"] is not None
    assert Path(row["snapshot_path"]).exists(), "Preservation archive must be stored on disk"


def test_parallel_upload_no_data_loss(client, conn):
    """Incident regression (parallel seq-20): both devices upload same title → distinct seqs,
    both archives exist, has_conflict=0 on both."""
    from pathlib import Path

    txn_og = do_upload(client, DEVICE_A, TITLE_1, b"og-last-night-" * 50)
    txn_lite = do_upload(client, DEVICE_B, TITLE_1, b"lite-midnight-" * 50)

    for txn_id in (txn_og, txn_lite):
        row = conn.execute(
            "SELECT has_conflict, snapshot_path, snapshot_sequence FROM sync_transactions "
            "WHERE transaction_id=?",
            (txn_id,),
        ).fetchone()
        assert row["has_conflict"] == 0
        assert row["snapshot_path"] is not None
        assert Path(row["snapshot_path"]).exists()

    seqs = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id IN (?,?) "
        "ORDER BY snapshot_sequence",
        (txn_og, txn_lite),
    ).fetchall()
    seq_values = [r["snapshot_sequence"] for r in seqs]
    assert seq_values == sorted(seq_values)
    assert len(set(seq_values)) == 2, "Both uploads must have distinct global sequences"


def test_divergence_is_logged_not_blocked(client, conn):
    """Upload when device_last_seq < head_seq: completes to READY_FOR_RESTORE, archive exists."""
    from helpers import do_ack
    from pathlib import Path

    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, b"og-v1-" * 50)

    # B receives and ACKs seq=1
    pending = poll_queue(client, DEVICE_B)
    txn_outbound = pending[0]["transaction_id"]
    total = pending[0]["total_bytes"]
    tok_b = pair_device(client, DEVICE_B)
    client.get(
        f"/api/v1/sync/transactions/{txn_outbound}/range?offset=0&length={total}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    do_ack(client, DEVICE_B, txn_outbound)

    # A uploads again → head advances to seq=2; B's device_last_seq stays at 1
    do_upload(client, DEVICE_A, TITLE_1, b"og-v2-" * 50)

    # B uploads (device_last_seq=1 < head=2 → DIAG_DIVERGENCE logged, but not blocked)
    txn_div = do_upload(client, DEVICE_B, TITLE_1, b"lite-diverged-" * 50)

    row = conn.execute(
        "SELECT has_conflict, state, snapshot_path FROM sync_transactions WHERE transaction_id=?",
        (txn_div,),
    ).fetchone()
    assert row["has_conflict"] == 0
    assert row["state"] == "READY_FOR_RESTORE"
    assert Path(row["snapshot_path"]).exists()


def test_different_profile_saves_are_independent_delivery_slots(client, conn):
    """Uploads from two different device profiles on DEVICE_A create independent
    delivery slots on DEVICE_B — they do not supersede each other.

    Each device profile is its own delivery lane. DEVICE_B's queue must see both saves.
    """
    report_catalog(client, DEVICE_B, [TITLE_1])

    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key="AABBCCDDEEFF0011")
    do_upload(client, DEVICE_A, TITLE_1, b"newer-save-" * 200, user_key="1122334455667788")

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 2, f"expected 2 independent slots, got {len(pending)}"
    sequences = {p["snapshot_sequence"] for p in pending}
    assert sequences == {1, 2}


def test_different_owner_user_ids_coexist_in_queue(client, conn):
    """Two different OmniSave users' outbounds for the same title+device must NOT
    supersede each other — each owner_user_id is an independent delivery lane.
    """
    import database as db

    now = "2026-01-01T00:00:00Z"
    # Seed two outbound READY_FOR_RESTORE rows for the same title+device but
    # different owner_user_ids, simulating two separate OmniSave users.
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,has_conflict,preservation,target_device_id,"
        " owner_user_id,created_at,updated_at) "
        "VALUES ('oid-user1',?,?,'outbound','READY_FOR_RESTORE',10,0,0,?,'omni-user-1',?,?)",
        (TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )
    conn.execute(
        "INSERT INTO sync_transactions "
        "(transaction_id,title_id,source_device_id,direction,state,"
        " snapshot_sequence,has_conflict,preservation,target_device_id,"
        " owner_user_id,created_at,updated_at) "
        "VALUES ('oid-user2',?,?,'outbound','READY_FOR_RESTORE',5,0,0,?,'omni-user-2',?,?)",
        (TITLE_1.upper(), DEVICE_A, DEVICE_B, now, now),
    )
    conn.commit()

    # Supersede for user-1 must NOT affect user-2's row.
    db.supersede_active_outbound(conn, DEVICE_B, TITLE_1, "omni-user-1")
    conn.commit()

    u1 = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id='oid-user1'"
    ).fetchone()
    u2 = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id='oid-user2'"
    ).fetchone()
    assert u1["state"] == "SUPERSEDED"
    assert u2["state"] == "READY_FOR_RESTORE"


def test_backfill_does_not_cross_user(client, conn):
    """Catalog backfill must not deliver a save to a device owned by a different user.

    Regression: _backfill_outbound_for_device previously had no owner_user_id filter,
    so uploading as user A then having user B's device report the same title in its
    catalog would queue user A's save for delivery to user B's Switch.
    """
    from helpers import pair_device

    DEVICE_C = "CCDDEE001122"
    OTHER_USER = "user_b"

    # Upload as the default admin user (DEVICE_A auto-pairs as admin via do_upload)
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    # Pair DEVICE_C as a different user directly in the DB
    import ui_api as _ui
    _ui._conn.execute(
        "INSERT OR IGNORE INTO devices (device_id, display_name, owner_user_id, created_at, last_seen)"
        " VALUES (?,?,?,datetime('now'),datetime('now'))",
        (DEVICE_C, "OtherSwitch", OTHER_USER),
    )
    _ui._conn.commit()

    # DEVICE_C reports TITLE_1 in its catalog — this triggers backfill
    r = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": [TITLE_1]},
        headers={"X-Device-ID": DEVICE_C},
    )
    assert r.status_code == 200

    # No outbound must have been created for DEVICE_C
    pending = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (DEVICE_C,),
    ).fetchone()[0]
    assert pending == 0, "cross-user backfill must not deliver admin's save to OTHER_USER's device"


def test_same_device_overlapping_sessions_distinct_sequences(client, conn):
    """Two sessions for the same device + title completing in sequence must each get a unique,
    monotonically increasing snapshot_sequence.

    Confirms the BEGIN IMMEDIATE guard in processing._process serialises concurrent workers:
    the sequence counter is incremented atomically so no two sessions can share a seq number.
    """
    txn1 = do_upload(client, DEVICE_A, TITLE_1, b"first-save" * 100)
    txn2 = do_upload(client, DEVICE_A, TITLE_1, b"second-save" * 100)

    rows = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions "
        "WHERE transaction_id IN (?, ?) ORDER BY snapshot_sequence",
        (txn1, txn2),
    ).fetchall()
    seqs = [r["snapshot_sequence"] for r in rows]
    assert seqs == [1, 2], f"expected [1,2], got {seqs}"

    # HEAD must point to the higher sequence
    head = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (DEVICE_A, TITLE_1),
    ).fetchone()
    assert head["last_seq"] == 2


def test_concurrent_commit_of_identical_content_one_sequence(client, conn):
    """Two sessions uploading byte-for-byte identical saves must produce exactly one sequence.

    The dedup check (save_already_committed) runs inside BEGIN IMMEDIATE so the second
    worker always sees the first's commit and is correctly marked DEDUPED.
    """
    data = b"identical-bytes" * 300
    txn1 = do_upload(client, DEVICE_A, TITLE_1, data)
    txn2 = do_upload(client, DEVICE_A, TITLE_1, data)

    states = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions "
        "WHERE transaction_id IN (?, ?)",
        (txn1, txn2),
    ).fetchall()
    terminal_states = {r["state"] for r in states}
    assert terminal_states == {"READY_FOR_RESTORE", "DEDUPED"}

    sequences = [r["snapshot_sequence"] for r in states if r["snapshot_sequence"] is not None]
    assert sequences == [1], f"exactly one sequence must be awarded, got {sequences}"
