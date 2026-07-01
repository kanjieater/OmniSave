"""
Snapshot management tests: deletion via UI API.
"""

from pathlib import Path

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, do_upload, poll_queue, login_admin, report_catalog, auth_header

SAVE = b"snapshot-mgmt-save"


def _bootstrap(client) -> str:
    return login_admin(client)


def _auth(token: str) -> dict:
    return auth_header(token)


def test_delete_requires_auth(client, conn, tmp_dirs):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    txn_id = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='inbound' AND state='READY_FOR_RESTORE'"
    ).fetchone()["transaction_id"]
    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}")
    assert r.status_code == 401


def test_delete_nonexistent_returns_404(client):
    token = _bootstrap(client)
    r = client.delete("/api/v1/ui/snapshots/00000000-0000-0000-0000-000000000000", headers=_auth(token))
    assert r.status_code == 404


def test_delete_removes_archive_file(client, conn, tmp_dirs):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    txn = conn.execute(
        "SELECT transaction_id, snapshot_path FROM sync_transactions "
        "WHERE direction='inbound' AND state='READY_FOR_RESTORE'"
    ).fetchone()
    assert Path(txn["snapshot_path"]).exists()

    token = _bootstrap(client)
    r = client.delete(f"/api/v1/ui/snapshots/{txn['transaction_id']}", headers=_auth(token))

    assert r.status_code == 200
    assert r.json()["deleted"] == txn["transaction_id"]
    assert not Path(txn["snapshot_path"]).exists()
    state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?",
        (txn["transaction_id"],),
    ).fetchone()["state"]
    assert state == "FAILED"


def test_delete_fails_pending_outbounds(client, conn, tmp_dirs):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    pending = poll_queue(client, DEVICE_B)
    outbound_id = pending[0]["transaction_id"]

    inbound_id = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='inbound' AND state='READY_FOR_RESTORE'"
    ).fetchone()["transaction_id"]

    token = _bootstrap(client)
    client.delete(f"/api/v1/ui/snapshots/{inbound_id}", headers=_auth(token))

    outbound_state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (outbound_id,)
    ).fetchone()["state"]
    assert outbound_state == "FAILED"


def test_delete_uploading_returns_404(client, conn, tmp_dirs):
    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1, 100, None
    )
    token = _bootstrap(client)
    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_auth(token))
    assert r.status_code == 404


def test_delete_after_full_upload_lifecycle(client, conn, tmp_dirs):
    """Lifecycle test: upload → processing → UI delete → verify final state.

    Exercises the exact HTTP calls the frontend makes, through the real processing
    path (sync_processing fixture makes _run() synchronous). Confirms snapshot_sequence
    is preserved and snapshot_path is cleared on delete — the behaviour observed in
    production when saves were deleted via the UI.
    """
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    txn = conn.execute(
        "SELECT transaction_id, snapshot_path, snapshot_sequence "
        "FROM sync_transactions WHERE direction='inbound' AND state='READY_FOR_RESTORE'"
    ).fetchone()
    assert txn is not None, "processing did not complete to READY_FOR_RESTORE"
    assert txn["snapshot_path"] is not None
    assert Path(txn["snapshot_path"]).exists(), "archive file must exist before delete"
    assert txn["snapshot_sequence"] is not None

    archive_path = txn["snapshot_path"]
    seq = txn["snapshot_sequence"]
    txn_id = txn["transaction_id"]

    token = _bootstrap(client)
    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_auth(token))

    assert r.status_code == 200
    assert r.json()["deleted"] == txn_id
    assert not Path(archive_path).exists(), "archive file must be deleted from disk"

    row = conn.execute(
        "SELECT state, snapshot_path, snapshot_sequence FROM sync_transactions WHERE transaction_id=?",
        (txn_id,),
    ).fetchone()
    assert row["state"] == "FAILED"
    assert row["snapshot_path"] is None
    assert row["snapshot_sequence"] == seq, "snapshot_sequence must be preserved after delete"
