"""
Snapshot sequence assignment tests.
Invariant: snapshot_sequence is assigned atomically inside BEGIN IMMEDIATE in the
processing worker, after dedup check confirms content is new. Commit endpoint never
touches the counter.
"""

import database as db
import processing
from helpers import CHECKPOINT_SIZE, DEVICE_A, DEVICE_B, TITLE_1, compute_ledger, sync_hdrs, start_inbound


SAVE_DATA = b"x" * 100
SAVE_DATA_2 = b"y" * 100


def _setup_upload(client, device_token):
    """Start inbound, post manifest, upload window. Returns (session_id, txn_id).
    Does NOT commit — caller controls when commit fires."""
    txn_id, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)

    ledger = compute_ledger(SAVE_DATA)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    assert r.status_code == 200

    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0",
                   content=SAVE_DATA, headers=h)
    assert r.status_code == 200

    return session_id, txn_id


def test_commit_does_not_return_snapshot_sequence(client, device_token):
    """Commit returns 202 with no snapshot_sequence — seq is deferred to processing."""
    session_id, _ = _setup_upload(client, device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/commit",
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 202
    body = r.json()
    assert body == {"processing": True}
    assert "snapshot_sequence" not in body


def test_commit_idempotent_stable(client, conn, device_token):
    """Second commit on same session returns 200; counter only increments during processing."""
    session_id, _ = _setup_upload(client, device_token)
    h = sync_hdrs(DEVICE_A, device_token)

    r1 = client.post(f"/api/v1/sync/sessions/{session_id}/commit", headers=h)
    assert r1.status_code == 202
    assert r1.json() == {"processing": True}

    counter_after_first = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]
    assert counter_after_first >= 1

    r2 = client.post(f"/api/v1/sync/sessions/{session_id}/commit", headers=h)
    assert r2.status_code == 200
    assert r2.json() == {"processing": True}

    counter_after_second = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]
    assert counter_after_second == counter_after_first


def test_finalize_inbound_does_not_overwrite_seq(conn):
    """finalize_inbound IS NULL guard: an already-committed seq survives a second call."""
    txn_id, _ = db.create_processing_transaction(
        conn, DEVICE_A, TITLE_1, len(SAVE_DATA), parent_sequence_num=None
    )
    conn.execute(
        "UPDATE sync_transactions SET snapshot_sequence=1 WHERE transaction_id=?",
        (txn_id,),
    )
    conn.commit()

    db.finalize_inbound(
        conn,
        transaction_id=txn_id,
        sha256="a" * 64,
        snapshot_path="/fake/path",
        snapshot_sequence=99,
        has_conflict=False,
    )
    conn.commit()

    row = conn.execute(
        "SELECT snapshot_sequence, state FROM sync_transactions WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["snapshot_sequence"] == 1, "finalize_inbound must not overwrite an existing seq"
    assert row["state"] == "READY_FOR_RESTORE"


def test_seq_assigned_after_processing(client, conn, device_token):
    """Full upload cycle: snapshot_sequence > 0 only after processing completes."""
    session_id, txn_id = _setup_upload(client, device_token)
    pre = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert pre["snapshot_sequence"] is None

    r = client.post(f"/api/v1/sync/sessions/{session_id}/commit",
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 202

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"
    assert row["snapshot_sequence"] is not None and row["snapshot_sequence"] > 0


def test_dedup_transaction_has_no_seq(client, conn, device_token):
    """Duplicate upload gets state=DEDUPED, snapshot_sequence=NULL; counter incremented once."""
    session_a, txn_a = _setup_upload(client, device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_a}/commit",
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 202
    seq_a = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_a,)
    ).fetchone()["snapshot_sequence"]
    assert seq_a is not None and seq_a > 0

    counter_after_first = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]

    # Second upload of SAME content from device B — should dedup.
    txn_b, session_b, token_b = start_inbound(client, DEVICE_B, TITLE_1, len(SAVE_DATA))
    h_b = sync_hdrs(DEVICE_B, token_b)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_b}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h_b)
    client.put(f"/api/v1/sync/sessions/{session_b}/window?offset=0", content=SAVE_DATA, headers=h_b)
    r = client.post(f"/api/v1/sync/sessions/{session_b}/commit", headers=h_b)
    assert r.status_code == 202

    row_b = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_b,),
    ).fetchone()
    assert row_b["state"] == "DEDUPED"
    assert row_b["snapshot_sequence"] is None

    counter_after_second = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()["counter"]
    assert counter_after_second == counter_after_first, "counter must not increment for dedup"


def test_failed_processing_does_not_burn_seq(tmp_dirs, conn):
    """Processing failure before BEGIN IMMEDIATE leaves counter unchanged, txn=FAILED, seq=NULL."""
    staging_dir, archive_dir = tmp_dirs

    txn_id, session_id = db.create_processing_transaction(
        conn, DEVICE_A, TITLE_1, len(SAVE_DATA), parent_sequence_num=None
    )
    conn.commit()
    # Deliberately omit staging file → FileNotFoundError before SHA256 / BEGIN IMMEDIATE.

    before = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()
    before_val = before["counter"] if before else 0

    processing._run(txn_id, session_id, staging_dir, archive_dir, conn.path)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["state"] == "FAILED"
    assert row["snapshot_sequence"] is None

    after = conn.execute(
        "SELECT counter FROM snapshot_counters WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()
    after_val = after["counter"] if after else 0
    assert after_val == before_val, "counter must not increment on failure"


def test_concurrent_new_uploads_get_distinct_seqs(tmp_dirs, conn):
    """Two uploads of distinct content get unique, non-NULL sequences."""
    staging_dir, archive_dir = tmp_dirs

    def _run_upload(data):
        txn_id, session_id = db.create_processing_transaction(
            conn, DEVICE_A, TITLE_1, len(data), parent_sequence_num=None
        )
        conn.commit()
        staging_file = staging_dir / session_id / "save.zip"
        staging_file.parent.mkdir(parents=True, exist_ok=True)
        staging_file.write_bytes(data)
        processing._run(txn_id, session_id, staging_dir, archive_dir, conn.path)
        return txn_id

    txn1 = _run_upload(SAVE_DATA)
    txn2 = _run_upload(SAVE_DATA_2)

    rows = conn.execute(
        "SELECT transaction_id, state, snapshot_sequence FROM sync_transactions "
        "WHERE transaction_id IN (?, ?)",
        (txn1, txn2),
    ).fetchall()

    seqs = [r["snapshot_sequence"] for r in rows]
    assert all(s is not None and s > 0 for s in seqs), "both uploads must get a seq"
    assert len(set(seqs)) == 2, "sequences must be distinct"


def test_dedup_no_outbound_fanout(client, conn, device_token):
    """Duplicate upload must not fork any new outbound transactions.
    Peers already have (or are queued to receive) the content — re-fanning
    would re-deliver identical bytes and inflate the queue."""
    # First upload from A — unique content → may fork outbounds for any peers
    session_a, txn_a = _setup_upload(client, device_token)
    client.post(f"/api/v1/sync/sessions/{session_a}/commit",
                headers=sync_hdrs(DEVICE_A, device_token))

    outbound_before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]

    # Second upload of IDENTICAL content from device B → must DEDUP
    txn_dup, session_dup, token_dup = start_inbound(client, DEVICE_B, TITLE_1, len(SAVE_DATA))
    h_dup = sync_hdrs(DEVICE_B, token_dup)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_dup}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h_dup)
    client.put(f"/api/v1/sync/sessions/{session_dup}/window?offset=0", content=SAVE_DATA, headers=h_dup)
    client.post(f"/api/v1/sync/sessions/{session_dup}/commit", headers=h_dup)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_dup,),
    ).fetchone()
    assert row["state"] == "DEDUPED", "duplicate upload must be DEDUPED"
    assert row["snapshot_sequence"] is None, "DEDUPED transaction must have no sequence"

    outbound_after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert outbound_after == outbound_before, \
        "dedup upload must not create new outbound transactions for any peer"


def test_fail_transaction_does_not_overwrite_ready(tmp_dirs, conn, monkeypatch):
    """Post-commit side-effect failure leaves txn=READY_FOR_RESTORE and logs PROCESSING_SIDE_EFFECT_FAILED."""
    staging_dir, archive_dir = tmp_dirs

    # Force catalog fanout to throw — happens after conn.commit() in _process().
    monkeypatch.setattr(db, "get_catalog_members", lambda *_: (_ for _ in ()).throw(RuntimeError("catalog fault")))

    txn_id, session_id = db.create_processing_transaction(
        conn, DEVICE_A, TITLE_1, len(SAVE_DATA), parent_sequence_num=None
    )
    conn.commit()
    staging_file = staging_dir / session_id / "save.zip"
    staging_file.parent.mkdir(parents=True, exist_ok=True)
    staging_file.write_bytes(SAVE_DATA)

    processing._run(txn_id, session_id, staging_dir, archive_dir, conn.path)

    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE", "post-commit failure must not overwrite READY_FOR_RESTORE"
    assert row["snapshot_sequence"] is not None and row["snapshot_sequence"] > 0

    event_types = [
        r["event_type"]
        for r in conn.execute(
            "SELECT event_type FROM events WHERE transaction_id=?", (txn_id,)
        ).fetchall()
    ]
    assert "PROCESSING_SIDE_EFFECT_FAILED" in event_types
