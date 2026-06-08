"""
UI push-to-device endpoint tests.
POST /api/v1/ui/snapshots/{transaction_id}/push
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, poll_queue, login_admin, auth_header, report_catalog

SAVE_V1 = b"save-version-one"
SAVE_V2 = b"save-version-two"

DEVICE_C = "CC:CC:CC:CC:CC:CC"


def _bootstrap(client) -> str:
    return login_admin(client)


def _auth(token: str) -> dict:
    return auth_header(token)


def _push(client, token, txn_id, device_ids=None) -> dict:
    body = {}
    if device_ids is not None:
        body["targets"] = [{"device_id": did} for did in device_ids]
    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json=body,
        headers=_auth(token),
    )
    return r


def _get_ready_inbound(conn):
    return conn.execute(
        "SELECT transaction_id, snapshot_sequence, title_id, source_device_id "
        "FROM sync_transactions "
        "WHERE direction='inbound' AND state='READY_FOR_RESTORE' "
        "ORDER BY snapshot_sequence DESC LIMIT 1"
    ).fetchone()


# ── Happy paths ───────────────────────────────────────────────────────────────


def test_push_to_explicit_device(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    token = _bootstrap(client)

    r = _push(client, token, txn["transaction_id"], device_ids=[DEVICE_B])

    assert r.status_code == 202
    body = r.json()
    assert body["ok"] is True
    assert len(body["outbound_ids"]) == 1
    outbound_id = body["outbound_ids"][0]

    row = conn.execute(
        "SELECT state, target_device_id FROM sync_transactions WHERE transaction_id=?",
        (outbound_id,),
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"
    assert row["target_device_id"] == DEVICE_B


def test_push_to_multiple_devices(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    token = _bootstrap(client)

    r = _push(client, token, txn["transaction_id"], device_ids=[DEVICE_B, DEVICE_C])

    assert r.status_code == 202
    assert len(r.json()["outbound_ids"]) == 2


def test_push_deduplicates_device_ids(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    token = _bootstrap(client)

    r = _push(client, token, txn["transaction_id"], device_ids=[DEVICE_B, DEVICE_B])

    assert r.status_code == 202
    assert len(r.json()["outbound_ids"]) == 1


def test_push_to_all_excludes_source_device(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    # Register DEVICE_B so it appears in get_all_devices (pair it via device-config)
    report_catalog(client, DEVICE_B, [TITLE_1])
    token = _bootstrap(client)

    # Push to all (empty device_ids)
    r = _push(client, token, txn["transaction_id"])

    assert r.status_code == 202
    outbound_ids = r.json()["outbound_ids"]
    targets = conn.execute(
        f"SELECT target_device_id FROM sync_transactions "
        f"WHERE transaction_id IN ({','.join('?'*len(outbound_ids))})",
        outbound_ids,
    ).fetchall()
    target_devices = {row["target_device_id"] for row in targets}
    assert DEVICE_A not in target_devices   # source excluded
    assert DEVICE_B in target_devices


def test_push_is_idempotent(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    token = _bootstrap(client)

    r1 = _push(client, token, txn["transaction_id"], device_ids=[DEVICE_B])
    r2 = _push(client, token, txn["transaction_id"], device_ids=[DEVICE_B])

    assert r1.status_code == 202
    assert r2.status_code == 202
    # Same outbound reused on second call
    assert r1.json()["outbound_ids"] == r2.json()["outbound_ids"]
    # Still only one active outbound for this device+title
    count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=? "
        "AND state='READY_FOR_RESTORE'",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()[0]
    assert count == 1


def test_push_supersedes_existing_outbound_for_different_snapshot(client, conn):
    # Upload v1 → commit-time fanout creates outbound for DEVICE_B (must be in catalog)
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    v1_outbound = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (DEVICE_B,),
    ).fetchone()["transaction_id"]

    # Upload v2 → different save → new sequence
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V2)
    v2_inbound = _get_ready_inbound(conn)

    # Push v2 to DEVICE_B; should supersede v1 outbound
    token = _bootstrap(client)
    r = _push(client, token, v2_inbound["transaction_id"], device_ids=[DEVICE_B])

    assert r.status_code == 202
    v1_state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (v1_outbound,)
    ).fetchone()["state"]
    assert v1_state == "SUPERSEDED"


# ── Error paths ───────────────────────────────────────────────────────────────


def test_push_requires_auth(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    r = client.post(
        f"/api/v1/ui/snapshots/{txn['transaction_id']}/push",
        json={"device_ids": [DEVICE_B]},
    )
    assert r.status_code == 401


def test_push_unknown_transaction_returns_404(client):
    token = _bootstrap(client)
    r = _push(client, token, "does-not-exist", device_ids=[DEVICE_B])
    assert r.status_code == 404


def test_push_wrong_state_returns_400(client, conn):
    txn_id, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 100, None)
    token = _bootstrap(client)
    r = _push(client, token, txn_id, device_ids=[DEVICE_B])
    assert r.status_code == 400
    assert "not pushable" in r.json()["error"]


def test_push_to_all_no_devices_returns_400(client, conn):
    # Only DEVICE_A (source) registered — no eligible targets
    do_upload(client, DEVICE_A, TITLE_1, SAVE_V1)
    txn = _get_ready_inbound(conn)
    token = _bootstrap(client)
    r = _push(client, token, txn["transaction_id"])
    assert r.status_code == 400
    assert "no eligible" in r.json()["error"]
