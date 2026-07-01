"""
UI outbound lifecycle endpoint tests.
POST /api/v1/ui/outbounds/{id}/retry
"""

import database as db
import pytest
from helpers import DEVICE_A, DEVICE_B, TITLE_1, do_upload, pair_device, poll_queue, login_admin, auth_header, report_catalog, sync_hdrs


@pytest.fixture(autouse=True)
def enroll_device_b(client):
    report_catalog(client, DEVICE_B, [TITLE_1])


SAVE_V1 = b"save-version-retry"
SAVE_V2 = b"save-version-retry-v2"


def _bootstrap(client) -> str:
    return login_admin(client)


def _auth(token: str) -> dict:
    return auth_header(token)


def _retry(client, token, txn_id):
    return client.post(
        f"/api/v1/ui/outbounds/{txn_id}/retry",
        headers=_auth(token),
    )


def _outbound_id(conn, source_device: str, target_device: str) -> str:
    row = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='outbound' AND source_device_id=? AND target_device_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (source_device, target_device),
    ).fetchone()
    return row["transaction_id"]


def _fail_outbound(client, device_id, txn_id):
    token = pair_device(client, device_id)
    client.post(
        "/api/v1/sync/fail",
        json={"transaction_id": txn_id, "error_code": "inject_fail"},
        headers=sync_hdrs(device_id, token),
    )


# ── Happy paths ───────────────────────────────────────────────────────────────


def test_retry_resets_ready_outbound(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    token = _bootstrap(client)

    r = _retry(client, token, oid)

    assert r.status_code == 200
    assert r.json()["ok"] is True
    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?",
        (oid,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"


def test_retry_resets_failed_outbound(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    _fail_outbound(client, DEVICE_B, oid)
    token = _bootstrap(client)

    r = _retry(client, token, oid)

    assert r.status_code == 200
    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (oid,)
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"


def test_retry_logs_event(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    _fail_outbound(client, DEVICE_B, oid)
    token = _bootstrap(client)

    _retry(client, token, oid)

    event = conn.execute(
        "SELECT event_type FROM events WHERE transaction_id=? AND event_type='OUTBOUND_RETRY'",
        (oid,),
    ).fetchone()
    assert event is not None


def test_retry_is_idempotent(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    token = _bootstrap(client)

    r1 = _retry(client, token, oid)
    r2 = _retry(client, token, oid)

    assert r1.status_code == 200
    assert r2.status_code == 200


# ── Error paths ───────────────────────────────────────────────────────────────


def test_retry_requires_auth(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    assert client.post(f"/api/v1/ui/outbounds/{oid}/retry").status_code == 401


def test_retry_unknown_transaction_returns_404(client):
    token = _bootstrap(client)
    r = _retry(client, token, "00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_retry_completed_outbound_returns_404(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    pending = poll_queue(client, DEVICE_B)
    oid = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)
    client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": oid},
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    token = _bootstrap(client)

    r = _retry(client, token, oid)
    assert r.status_code == 404


# ── retry-all (bulk) ──────────────────────────────────────────────────────────


def _retry_all(client, token, device_id):
    return client.post(
        f"/api/v1/ui/devices/{device_id}/outbounds/retry-failed",
        headers=_auth(token),
    )


def test_retry_all_resets_failed_outbound(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid = _outbound_id(conn, DEVICE_A, DEVICE_B)
    _fail_outbound(client, DEVICE_B, oid)
    token = _bootstrap(client)

    r = _retry_all(client, token, DEVICE_B)

    assert r.status_code == 200
    assert r.json()["retried"] == 1
    state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (oid,)
    ).fetchone()
    assert state["state"] == "READY_FOR_RESTORE"


def test_retry_all_skips_ghost_failure_superseded_by_completed(client, conn):
    """FAILED at seq 1, COMPLETED at seq 2 — retry-all must not reset the ghost."""
    token = _bootstrap(client)

    # seq 1 → fail
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid1 = _outbound_id(conn, DEVICE_A, DEVICE_B)
    _fail_outbound(client, DEVICE_B, oid1)

    # seq 2 → ACK (ACK handler auto-supersedes oid1 → SUPERSEDED)
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V2)
    pending = poll_queue(client, DEVICE_B)
    oid2 = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)
    client.post("/api/v1/sync/ack", json={"transaction_id": oid2},
                headers=sync_hdrs(DEVICE_B, tok_b))

    # Simulate legacy ghost row that predated auto-supersede
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED' WHERE transaction_id=?", (oid1,)
    )
    conn.commit()

    r = _retry_all(client, token, DEVICE_B)

    assert r.status_code == 200
    assert r.json()["retried"] == 0
    state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (oid1,)
    ).fetchone()
    assert state["state"] == "FAILED"  # ghost must not be requeued


def test_retry_all_only_retries_highest_seq_failed(client, conn):
    """Two FAILEDs at seq 1 and seq 2 — only the higher seq is reset."""
    token = _bootstrap(client)

    # seq 1 → fail
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    poll_queue(client, DEVICE_B)
    oid1 = _outbound_id(conn, DEVICE_A, DEVICE_B)
    _fail_outbound(client, DEVICE_B, oid1)

    # seq 2 → fail (seq 1 FAILED stays; supersede_active_outbound skips FAILED rows)
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V2)
    pending = poll_queue(client, DEVICE_B)
    oid2 = pending[0]["transaction_id"]
    _fail_outbound(client, DEVICE_B, oid2)

    r = _retry_all(client, token, DEVICE_B)

    assert r.status_code == 200
    assert r.json()["retried"] == 1
    s1 = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (oid1,)
    ).fetchone()
    s2 = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (oid2,)
    ).fetchone()
    assert s1["state"] == "FAILED"           # old seq — left alone
    assert s2["state"] == "READY_FOR_RESTORE"  # highest seq — reset
