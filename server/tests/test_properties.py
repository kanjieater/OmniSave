"""
Hypothesis property-based tests.
Invariants that must hold regardless of input: sequence monotonicity,
assembly correctness, state machine unidirectional flow.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import database as db
import processing

# ── Helpers ────────────────────────────────────────────────────────────────────

DEVICE = "AA:BB:CC:DD:EE:FF"
TITLE = "0100F2C0115B6000"


def _fresh_db():
    tmp = tempfile.mkdtemp()
    return db.open_db(Path(tmp) / "test.db"), Path(tmp)


def _seed_save_bin(staging: Path, session_id: str, data: bytes) -> None:
    """Write a V2-style single staging file and set server_verified_bytes."""
    sess_dir = staging / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "save.zip").write_bytes(data)


# ── Properties ─────────────────────────────────────────────────────────────────


@given(st.integers(min_value=1, max_value=20))
@settings(max_examples=15, deadline=5000)
def test_sequence_numbers_are_monotonically_increasing(n_uploads):
    conn, tmp = _fresh_db()
    staging = tmp / "staging"
    archive = tmp / "archive"
    staging.mkdir()
    archive.mkdir()

    seqs = []
    for i in range(n_uploads):
        data = f"save-{i}".encode()
        txn_id, session_id = db.create_inbound_transaction(
            conn, DEVICE, TITLE, len(data), None
        )
        conn.execute(
            "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
        )
        conn.execute(
            "UPDATE upload_sessions SET session_state='COMPLETED',server_verified_bytes=? "
            "WHERE transaction_id=?",
            (len(data), txn_id),
        )
        seq = db.next_global_sequence(conn, TITLE)
        conn.execute(
            "UPDATE sync_transactions SET snapshot_sequence=? "
            "WHERE transaction_id=? AND snapshot_sequence IS NULL",
            (seq, txn_id),
        )
        _seed_save_bin(staging, session_id, data)
        processing._run(txn_id, session_id, staging, archive, conn.path)

        row = conn.execute(
            "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_id,)
        ).fetchone()
        seqs.append(row["snapshot_sequence"])

    assert seqs == sorted(seqs), f"sequences not monotone: {seqs}"
    assert len(set(seqs)) == len(seqs), f"duplicate sequences: {seqs}"


@given(st.binary(min_size=1, max_size=256 * 1024))
@settings(max_examples=20, deadline=10000)
def test_assembly_preserves_data_integrity(data):
    conn, tmp = _fresh_db()
    staging = tmp / "staging"
    archive = tmp / "archive"
    staging.mkdir()
    archive.mkdir()

    txn_id, session_id = db.create_inbound_transaction(
        conn, DEVICE, TITLE, len(data), None
    )
    _seed_save_bin(staging, session_id, data)

    conn.execute(
        "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
    )
    conn.execute(
        "UPDATE upload_sessions SET session_state='COMPLETED',server_verified_bytes=? "
        "WHERE transaction_id=?",
        (len(data), txn_id),
    )
    seq = db.next_global_sequence(conn, TITLE)
    conn.execute(
        "UPDATE sync_transactions SET snapshot_sequence=? "
        "WHERE transaction_id=? AND snapshot_sequence IS NULL",
        (seq, txn_id),
    )

    processing._run(txn_id, session_id, staging, archive, conn.path)

    row = conn.execute(
        "SELECT state, sha256, snapshot_path FROM sync_transactions WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"
    assembled = Path(row["snapshot_path"]).read_bytes()
    assert assembled == data
    assert row["sha256"] == hashlib.sha256(data).hexdigest()


@given(st.integers(min_value=0, max_value=5), st.integers(min_value=1, max_value=10))
@settings(max_examples=15, deadline=5000)
def test_has_conflict_is_always_zero(parent_seq, head_advance):
    """Invariant: has_conflict is always 0 regardless of divergence.
    Divergence is telemetry only (DIAG_DIVERGENCE log) — never stored, never blocks."""
    conn, tmp = _fresh_db()
    staging = tmp / "staging"
    archive = tmp / "archive"
    staging.mkdir()
    archive.mkdir()

    def _upload(device, data):
        txn_id, session_id = db.create_inbound_transaction(
            conn, device, TITLE, len(data), None
        )
        conn.execute(
            "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
        )
        conn.execute(
            "UPDATE upload_sessions SET session_state='COMPLETED',server_verified_bytes=? "
            "WHERE transaction_id=?",
            (len(data), txn_id),
        )
        seq = db.next_global_sequence(conn, TITLE)
        conn.execute(
            "UPDATE sync_transactions SET snapshot_sequence=? "
            "WHERE transaction_id=? AND snapshot_sequence IS NULL",
            (seq, txn_id),
        )
        _seed_save_bin(staging, session_id, data)
        processing._run(txn_id, session_id, staging, archive, conn.path)
        return txn_id

    for i in range(head_advance):
        _upload(f"peer-{i}", f"peer-save-{i}".encode())

    data = b"hello"
    txn_id, session_id = db.create_inbound_transaction(
        conn, DEVICE, TITLE, len(data), parent_seq
    )
    conn.execute(
        "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
    )
    conn.execute(
        "UPDATE upload_sessions SET session_state='COMPLETED',server_verified_bytes=? "
        "WHERE transaction_id=?",
        (len(data), txn_id),
    )
    seq = db.next_global_sequence(conn, TITLE)
    conn.execute(
        "UPDATE sync_transactions SET snapshot_sequence=? "
        "WHERE transaction_id=? AND snapshot_sequence IS NULL",
        (seq, txn_id),
    )
    _seed_save_bin(staging, session_id, data)
    processing._run(txn_id, session_id, staging, archive, conn.path)

    row = conn.execute(
        "SELECT has_conflict, state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()

    assert row["has_conflict"] == 0, "has_conflict must always be 0"
    assert row["state"] == "READY_FOR_RESTORE", "every upload must reach READY_FOR_RESTORE"
