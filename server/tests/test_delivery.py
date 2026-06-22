"""
Delivery flow behavioral tests.
Server is a passive snapshot ledger — no exclusive claim/lease.
Covers: queue poll, download range, ACK, permanent fail, queue hint.
"""

import hashlib

import pytest

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_ack, do_upload, pair_device, poll_queue, queue_get, report_catalog, start_inbound, sync_hdrs

SAVE_DATA = b"save-content-" * 500  # ~6.5 KB
DEVICE_C = "CCDDEEFF0011"


@pytest.fixture(autouse=True)
def enroll_devices(client):
    """Pre-enroll DEVICE_B (and DEVICE_C) in catalog for both test titles.

    The new architecture requires catalog membership for commit-time fanout and backfill.
    Tests that specifically verify "no catalog → no outbound" opt out by using a fresh
    device_id not covered here.
    """
    report_catalog(client, DEVICE_B, [TITLE_1, TITLE_2])
    report_catalog(client, DEVICE_C, [TITLE_1, TITLE_2])


def test_queue_empty_for_new_device(client):
    assert poll_queue(client, DEVICE_B) == []


def test_queue_returns_pending_outbound(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["title_id"] == TITLE_1.upper()


def test_queue_does_not_create_rows(client, conn):
    # Queue is a drain-only endpoint — it must never create outbound rows.
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    outbounds_before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    # Outbounds already created by commit-time fanout for all enrolled devices (B + C)
    assert outbounds_before >= 1

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1

    outbounds_after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert outbounds_after == outbounds_before  # queue added nothing


def test_queue_entry_contains_ledger_and_size(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    entry = pending[0]
    assert "total_bytes" in entry
    assert entry["total_bytes"] == len(SAVE_DATA)
    assert "checkpoint_size" in entry
    assert "checkpoint_ledger" in entry
    assert isinstance(entry["checkpoint_ledger"], list)
    assert len(entry["checkpoint_ledger"]) >= 1


def test_download_range_correct_bytes(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    total = len(SAVE_DATA)
    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length={total}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200
    assert r.content == SAVE_DATA


def test_download_range_partial_offset(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    offset, length = 10, 50
    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset={offset}&length={length}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200
    assert r.content == SAVE_DATA[offset : offset + length]


def test_download_range_integrity_full_reassembly(client):
    data = bytes(range(256)) * 100
    do_upload(client, DEVICE_A, TITLE_1, data)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    total = len(data)
    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length={total}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200
    assert hashlib.sha256(r.content).hexdigest() == hashlib.sha256(data).hexdigest()


def test_download_range_without_prior_claim_succeeds(client):
    """No claim required — any device with a valid outbound can download immediately."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200


def test_download_range_offset_beyond_end_rejected(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset={len(SAVE_DATA)}&length=1",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 416


def test_ack_completes_delivery(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    r = client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "COMPLETED"


def test_ack_event_includes_seq(client, conn):
    """RESTORE_ACKED event message must include seq= so the activity view can show save #."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers=sync_hdrs(DEVICE_B, tok_b),
    )

    row = conn.execute(
        "SELECT message FROM events WHERE event_type='RESTORE_ACKED'"
    ).fetchone()
    assert row is not None
    assert "seq=" in row["message"]


def test_ack_idempotent_when_already_completed(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    client.post("/api/v1/sync/ack", json={"transaction_id": txn_id}, headers=sync_hdrs(DEVICE_B, tok_b))
    r2 = client.post("/api/v1/sync/ack", json={"transaction_id": txn_id}, headers=sync_hdrs(DEVICE_B, tok_b))
    assert r2.status_code == 200


def test_ack_wrong_device_rejected(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    tok_a = pair_device(client, DEVICE_A)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers=sync_hdrs(DEVICE_A, tok_a),
    )
    assert r.status_code == 409


def test_ack_wrong_device_does_not_advance_head(client, conn):
    """Rejected cross-device ACK must not:
      - mark B's outbound COMPLETED (B never received the save)
      - advance B's device_title_head (B has not seen that sequence)
    Regression for Issue 3: complete_outbound + auth guard must both hold.
    """
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    tok_a = pair_device(client, DEVICE_A)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    # Device A (valid token, wrong target) attempts to ACK B's transaction
    r = client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers=sync_hdrs(DEVICE_A, tok_a),
    )
    assert r.status_code == 409

    # B's outbound must still be READY_FOR_RESTORE — not completed by A
    state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert state["state"] == "READY_FOR_RESTORE"

    # B's HEAD must be untouched (B has not received the save)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1),
    ).fetchone()
    assert row is None, "B HEAD should be untouched after rejected ACK"

    # B can still receive the save and advance its own HEAD
    do_ack(client, DEVICE_B, txn_id)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1),
    ).fetchone()
    assert row is not None
    assert row["last_seq"] == 1


def test_permanent_fail_removes_from_queue(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    r = client.post(
        "/api/v1/sync/fail",
        json={"transaction_id": txn_id, "error_code": "inject_fail"},
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 200

    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "FAILED"
    assert poll_queue(client, DEVICE_B) == []


def test_failed_delivery_not_requeued(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    client.post(
        "/api/v1/sync/fail",
        json={"transaction_id": txn_id, "error_code": "inject_fail"},
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert poll_queue(client, DEVICE_B) == []


def test_multiple_devices_can_download_concurrently(client, conn):
    """Two devices should both see the same snapshot in their queues."""
    from helpers import DEVICE_A as A, DEVICE_B as B
    do_upload(client, A, TITLE_1, SAVE_DATA)

    pending_b = poll_queue(client, B)
    pending_c = poll_queue(client, DEVICE_C)
    assert len(pending_b) == 1
    assert len(pending_c) == 1
    assert pending_b[0]["title_id"] == pending_c[0]["title_id"]

    tok_b = pair_device(client, B)
    tok_c = pair_device(client, DEVICE_C)

    # Both can download simultaneously — no exclusive ownership
    txn_b = pending_b[0]["transaction_id"]
    txn_c = pending_c[0]["transaction_id"]
    total = len(SAVE_DATA)
    rb = client.get(f"/api/v1/sync/transactions/{txn_b}/range?offset=0&length={total}", headers=sync_hdrs(B, tok_b))
    rc = client.get(f"/api/v1/sync/transactions/{txn_c}/range?offset=0&length={total}", headers=sync_hdrs(DEVICE_C, tok_c))
    assert rb.status_code == 200
    assert rc.status_code == 200


def test_download_range_invalid_params_rejected(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=0",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 400


def test_download_range_wrong_device_denied(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    tok_a = pair_device(client, DEVICE_A)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers=sync_hdrs(DEVICE_A, tok_a),
    )
    assert r.status_code == 404


def test_download_range_overrun_rejected(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    total = len(SAVE_DATA)
    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=10&length={total}",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 416


def test_queue_hint_when_processing_exists(client, conn):
    txn_id, _, _ = start_inbound(client, DEVICE_A, TITLE_1, 100)
    conn.execute(
        "UPDATE sync_transactions SET state='PROCESSING' WHERE transaction_id=?", (txn_id,)
    )
    r = queue_get(client, DEVICE_B)
    assert r.status_code == 200
    assert r.json().get("hint") == "queue_hint"


def test_queue_no_hint_when_idle(client):
    r = queue_get(client, DEVICE_B)
    assert r.json().get("hint") is None


def test_queue_returns_401_after_device_deleted(client, conn):
    """Regression: deleted device must get 401 on /queue so the sysmodule re-enters pairing."""
    token = pair_device(client, DEVICE_B)
    # Simulate server-side device deletion by wiping device_auth
    conn.execute("DELETE FROM device_auth WHERE device_id=?", (DEVICE_B,))
    r = client.get("/api/v1/sync/queue", headers=sync_hdrs(DEVICE_B, token))
    assert r.status_code == 401


def test_fail_idempotent_already_failed(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)

    client.post("/api/v1/sync/fail", json={"transaction_id": txn_id, "error_code": "e"}, headers=sync_hdrs(DEVICE_B, tok_b))
    r2 = client.post("/api/v1/sync/fail", json={"transaction_id": txn_id, "error_code": "e"}, headers=sync_hdrs(DEVICE_B, tok_b))
    assert r2.status_code == 200


def test_download_range_failed_outbound_denied(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]
    tok_b = pair_device(client, DEVICE_B)
    client.post("/api/v1/sync/fail", json={"transaction_id": txn_id, "error_code": "e"}, headers=sync_hdrs(DEVICE_B, tok_b))

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 404


# ── user_key routing ──────────────────────────────────────────────────────────


def test_user_key_stored_in_transaction(client, conn):
    """user_key and user_display are persisted when provided at upload time."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA,
              user_key="AABBCCDDAABBCCDD", user_display="Alice")
    row = conn.execute(
        "SELECT user_key, user_display FROM sync_transactions "
        "WHERE source_device_id=? AND direction='inbound'",
        (DEVICE_A,),
    ).fetchone()
    assert row["user_key"] == "AABBCCDDAABBCCDD"
    assert row["user_display"] == "Alice"


def test_user_key_present_in_queue_response(client):
    """Queue response includes target_profile_uid (device default, empty when unset)."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA, user_key="AABBCCDDAABBCCDD")
    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    # target_profile_uid is empty because DEVICE_B has no default profile set
    assert pending[0]["target_profile_uid"] == ""


def test_queue_empty_user_key_when_not_provided(client):
    """Queue returns target_profile_uid for the outbound (empty when device has no default)."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["target_profile_uid"] == ""


def test_different_profiles_have_independent_delivery_slots(client):
    """Uploads from two different device profiles create independent delivery slots.

    Each (device, title, profile) combination is its own delivery lane — the second
    profile's save does not supersede the first profile's save.
    """
    do_upload(client, DEVICE_A, TITLE_1, b"alice-save" * 100, user_key="AAAAAAAAAAAAAAAA")
    do_upload(client, DEVICE_A, TITLE_1, b"bob-save--" * 100, user_key="BBBBBBBBBBBBBBBB")

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 2  # each profile's save occupies an independent slot
    sequences = {p["snapshot_sequence"] for p in pending}
    assert sequences == {1, 2}


def test_supersede_replaces_older_save_same_owner(client):
    """A newer upload supersedes the previously queued save for the same owner."""
    do_upload(client, DEVICE_A, TITLE_1, b"v1-save--" * 100, user_key="AAAAAAAAAAAAAAAA")
    assert len(poll_queue(client, DEVICE_B)) == 1

    do_upload(client, DEVICE_A, TITLE_1, b"v2-save--" * 100, user_key="AAAAAAAAAAAAAAAA")

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["snapshot_sequence"] == 2  # v2 superseded v1


# ── Delivery auth ──────────────────────────────────────────────────────────────


def test_range_missing_device_id_returns_401(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.get(f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10")
    assert r.status_code == 401


def test_range_missing_token_returns_401(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers={"X-Device-ID": DEVICE_B},
    )
    assert r.status_code == 401


def test_range_invalid_token_returns_401(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers={"X-Device-ID": DEVICE_B, "Authorization": "Bearer sk_device_bad"},
    )
    assert r.status_code == 401


def test_range_deleted_device_returns_401(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    tok_b = pair_device(client, DEVICE_B)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    conn.execute("UPDATE devices SET deleted_at='2026-01-01' WHERE device_id=?", (DEVICE_B,))

    r = client.get(
        f"/api/v1/sync/transactions/{txn_id}/range?offset=0&length=10",
        headers=sync_hdrs(DEVICE_B, tok_b),
    )
    assert r.status_code == 401


def test_ack_missing_token_returns_401(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers={"X-Device-ID": DEVICE_B},
    )
    assert r.status_code == 401


def test_fail_missing_token_returns_401(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    r = client.post(
        "/api/v1/sync/fail",
        json={"transaction_id": txn_id, "error_code": "e"},
        headers={"X-Device-ID": DEVICE_B},
    )
    assert r.status_code == 401
