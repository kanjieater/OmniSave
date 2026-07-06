"""
Upload flow behavioral tests — V2 window API.
Covers: inbound initiation, manifest POST, window idempotency,
        completeness gate, resume offset, processing.
"""

import sync_api
from helpers import CHECKPOINT_SIZE, DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, WINDOW_SIZE, auth_header, compute_ledger, do_upload, get_uid, pair_device, start_inbound, sync_hdrs

SAVE_DATA = b"X" * 1024  # small save, fits in one checkpoint


def test_start_inbound_returns_session(client):
    _, session_id, token = start_inbound(client, DEVICE_A, TITLE_1, 1024)
    assert session_id is not None


def test_start_inbound_missing_device_header(client):
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": 1024},
    )
    assert r.status_code == 401


def test_start_inbound_invalid_title(client, device_token):
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": "not-a-title", "total_size_bytes": 1024},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 400


def test_device_id_colon_mac_normalized(client, conn, device_token):
    """Colon-format MAC is normalized to uppercase no-colon before storage."""
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": 1024},
        headers={"X-Device-ID": "aa:bb:cc:dd:ee:ff", "Authorization": f"Bearer {device_token}"},
    )
    assert r.status_code == 200
    stored = conn.execute("SELECT device_id FROM devices WHERE device_id='AABBCCDDEEFF'").fetchone()
    assert stored is not None
    ghost = conn.execute("SELECT device_id FROM devices WHERE device_id='aa:bb:cc:dd:ee:ff'").fetchone()
    assert ghost is None


def test_device_id_colon_mac_deduplicates(client, conn, device_token):
    """Repeated uploads from colon MAC and no-colon MAC map to the same device."""
    for fmt in ["AA:BB:CC:DD:EE:FF", "AABBCCDDEEFF"]:
        client.post(
            "/api/v1/sync/transactions/inbound",
            json={"title_id": TITLE_1, "total_size_bytes": 1024},
            headers={"X-Device-ID": fmt, "Authorization": f"Bearer {device_token}"},
        )
    devices = conn.execute("SELECT device_id FROM devices WHERE device_id LIKE 'AABB%'").fetchall()
    assert len(devices) == 1 and devices[0]["device_id"] == "AABBCCDDEEFF"


def test_start_inbound_zero_size_rejected(client, device_token):
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": 0},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 400


def test_manifest_post_freezes_ledger(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["server_verified_bytes"] == 0


def test_manifest_repost_returns_actual_svb(client, device_token):
    """Re-posting manifest after partial upload returns current server_verified_bytes, not 0.

    Scenario: Switch loses session.json (sysmodule restart), re-calls start_inbound
    (server reuses session), re-posts manifest. Server must return the real SVB so the
    Switch can resume from the correct offset instead of restarting from 0."""
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    manifest_body = {"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest", json=manifest_body, headers=h)
    client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    # Re-post manifest (simulates Switch losing session.json and starting over)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest", json=manifest_body, headers=h)
    assert r.status_code == 200
    assert r.json()["server_verified_bytes"] == len(SAVE_DATA)


def test_manifest_wrong_checkpoint_size_rejected(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": 1024, "checkpoint_ledger": [12345]},
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 400


def test_manifest_wrong_ledger_length_rejected(client, device_token):
    data = b"X" * (CHECKPOINT_SIZE + 1)
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(data), device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": [1]},
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 400


def test_window_upload_missing_device_header(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA)
    assert r.status_code == 401


def test_window_upload_without_manifest_rejected(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0",
                   content=SAVE_DATA, headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 400


def test_window_upload_offset_zero_advances_svb(client, conn, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    assert r.status_code == 200
    assert r.json()["server_verified_bytes"] == len(SAVE_DATA)


def test_window_upload_idempotent_below_svb(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    r2 = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    assert r2.status_code == 200
    assert r2.json()["server_verified_bytes"] == len(SAVE_DATA)


def test_window_upload_ahead_of_svb_returns_409(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    r2 = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset={CHECKPOINT_SIZE}",
                    content=SAVE_DATA, headers=h)
    assert r2.status_code == 409


def test_window_hash_mismatch_stalls_svb(client, device_token):
    data = b"Y" * CHECKPOINT_SIZE
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(data), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": [0xDEADBEEF]}, headers=h)
    r2 = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=data, headers=h)
    assert r2.status_code == 200
    assert r2.json()["server_verified_bytes"] == 0  # stalled — hash mismatch


def test_commit_completeness_gate_rejects_partial(client, device_token):
    data = b"P" * CHECKPOINT_SIZE
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(data), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(data)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/commit", headers=h)
    assert r.status_code == 400


def test_full_upload_reaches_ready_for_restore(client, conn):
    txn_id = do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    txn = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["state"] == "READY_FOR_RESTORE"


def test_upload_assigns_snapshot_sequence(client, conn):
    txn_id = do_upload(client, DEVICE_A, TITLE_1, b"save_v1")
    txn = conn.execute(
        "SELECT snapshot_sequence FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert txn["snapshot_sequence"] == 1


def test_commit_retry_is_idempotent(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    r1 = client.post(f"/api/v1/sync/sessions/{session_id}/commit", headers=h)
    r2 = client.post(f"/api/v1/sync/sessions/{session_id}/commit", headers=h)
    assert r1.status_code in (200, 202)
    assert r2.status_code == 200


def test_resume_returns_server_verified_bytes(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.get(f"/api/v1/sync/sessions/{session_id}/resume",
                   headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 200
    body = r.json()
    assert body["server_verified_bytes"] == 0
    assert body["total_bytes"] == len(SAVE_DATA)


def test_storage_full_rejects_inbound(client, device_token, monkeypatch):
    monkeypatch.setattr(sync_api, "_storage_ok", lambda: False)
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": 1024},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 507


def test_storage_full_rejects_window_upload(client, device_token, monkeypatch):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=h)
    monkeypatch.setattr(sync_api, "_storage_ok", lambda: False)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=SAVE_DATA, headers=h)
    assert r.status_code == 507


def test_upload_ledger_stored_after_processing(client, conn):
    txn_id = do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    row = conn.execute(
        "SELECT checkpoint_ledger FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["checkpoint_ledger"] is not None


def test_manifest_missing_device_header(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": compute_ledger(SAVE_DATA)})
    assert r.status_code == 401


def test_manifest_invalid_session_id(client, device_token):
    r = client.post(
        "/api/v1/sync/sessions/not-a-valid-uuid/manifest",
        json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": [1]},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 422


def test_manifest_session_not_found(client, device_token):
    r = client.post(
        "/api/v1/sync/sessions/00000000-0000-0000-0000-000000000001/manifest",
        json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": [1]},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 404


def test_manifest_session_not_active(client, conn, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    conn.execute("UPDATE upload_sessions SET session_state='COMPLETED' WHERE session_id=?", (session_id,))
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE,
                          "checkpoint_ledger": compute_ledger(SAVE_DATA)},
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 409


def test_manifest_out_of_range_hash_rejected(client, device_token):
    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA), device_token)
    r = client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                    json={"checkpoint_size": CHECKPOINT_SIZE,
                          "checkpoint_ledger": [0xFFFFFFFF + 1]},
                    headers=sync_hdrs(DEVICE_A, device_token))
    assert r.status_code == 400


def test_manifest_idempotent_if_already_posted(client):
    _, session_id, token = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA))
    hdrs = {"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"}
    ledger = compute_ledger(SAVE_DATA)
    manifest_body = {"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}
    r1 = client.post(f"/api/v1/sync/sessions/{session_id}/manifest", json=manifest_body, headers=hdrs)
    r2 = client.post(f"/api/v1/sync/sessions/{session_id}/manifest", json=manifest_body, headers=hdrs)
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_window_invalid_session_id(client, device_token):
    r = client.put(
        "/api/v1/sync/sessions/not-a-uuid/window?offset=0",
        content=b"data",
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 422


def test_window_negative_offset_rejected(client):
    _, session_id, token = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA))
    hdrs = {"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"}
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=hdrs)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=-1", content=SAVE_DATA, headers=hdrs)
    assert r.status_code == 400


def test_window_non_aligned_offset_rejected(client):
    data = b"X" * (CHECKPOINT_SIZE * 2)
    _, session_id, token = start_inbound(client, DEVICE_A, TITLE_1, len(data))
    hdrs = {"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"}
    ledger = compute_ledger(data)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=hdrs)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0",
                   content=data[:CHECKPOINT_SIZE], headers=hdrs)
    assert r.status_code == 200
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset={CHECKPOINT_SIZE + 1}",
                   content=data[CHECKPOINT_SIZE + 1:], headers=hdrs)
    assert r.status_code in (400, 409)


def test_window_empty_body_rejected(client):
    _, session_id, token = start_inbound(client, DEVICE_A, TITLE_1, len(SAVE_DATA))
    hdrs = {"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"}
    ledger = compute_ledger(SAVE_DATA)
    client.post(f"/api/v1/sync/sessions/{session_id}/manifest",
                json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger}, headers=hdrs)
    r = client.put(f"/api/v1/sync/sessions/{session_id}/window?offset=0", content=b"", headers=hdrs)
    assert r.status_code == 400


# ── Idempotent inbound open ───────────────────────────────────────────────────


def test_start_inbound_same_slot_reuses_session(client, conn):
    """Same device+title+parent_seq+size while UPLOADING → returns existing txn/session (no new row)."""
    token = pair_device(client, DEVICE_A)
    hdrs = sync_hdrs(DEVICE_A, token)
    body = {"title_id": TITLE_1, "total_size_bytes": 100}

    r1 = client.post("/api/v1/sync/transactions/inbound", json=body, headers=hdrs)
    r2 = client.post("/api/v1/sync/transactions/inbound", json=body, headers=hdrs)

    assert r1.status_code == r2.status_code == 200
    assert r1.json()["transaction_id"] == r2.json()["transaction_id"]
    assert r1.json()["session_id"] == r2.json()["session_id"]
    count = conn.execute(
        "SELECT count(*) FROM sync_transactions "
        "WHERE source_device_id=? AND title_id=? AND state='UPLOADING'",
        (DEVICE_A, TITLE_1),
    ).fetchone()[0]
    assert count == 1


def test_start_inbound_different_parent_seq_gets_new_txn(client):
    """Different parent_sequence_num → new transaction (genuine next save in chain)."""
    token = pair_device(client, DEVICE_A)
    hdrs = sync_hdrs(DEVICE_A, token)

    r1 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_1, "total_size_bytes": 100, "parent_sequence_num": 1},
                     headers=hdrs)
    r2 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_1, "total_size_bytes": 100, "parent_sequence_num": 2},
                     headers=hdrs)

    assert r1.json()["transaction_id"] != r2.json()["transaction_id"]


def test_start_inbound_different_title_gets_new_txn(client):
    """Different title → always a new transaction."""
    token = pair_device(client, DEVICE_A)
    hdrs = sync_hdrs(DEVICE_A, token)

    r1 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_1, "total_size_bytes": 100}, headers=hdrs)
    r2 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_2, "total_size_bytes": 100}, headers=hdrs)

    assert r1.json()["transaction_id"] != r2.json()["transaction_id"]


def test_start_inbound_different_size_gets_new_txn(client):
    """Same slot but different total_size_bytes → new transaction (save data changed)."""
    token = pair_device(client, DEVICE_A)
    hdrs = sync_hdrs(DEVICE_A, token)

    r1 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_1, "total_size_bytes": 100}, headers=hdrs)
    r2 = client.post("/api/v1/sync/transactions/inbound",
                     json={"title_id": TITLE_1, "total_size_bytes": 200}, headers=hdrs)

    assert r1.json()["transaction_id"] != r2.json()["transaction_id"]


def test_window_oversized_body_rejected(client, device_token):
    """Window body larger than (total - offset) must be rejected before any disk write.

    Bug: _write_at_offset runs before length check, so extra bytes land in the staging
    file; _validate_window still returns total_bytes (hash covers only the first N bytes
    which are correct), svb reaches total, commit succeeds, and the delivered archive is
    larger than declared.
    """
    total = 5
    correct = b"HELLO"
    oversized = correct + b"GARBAGE"  # 12 bytes; ledger is for "HELLO" only

    _, session_id, _ = start_inbound(client, DEVICE_A, TITLE_1, total, device_token)
    h = sync_hdrs(DEVICE_A, device_token)
    client.post(
        f"/api/v1/sync/sessions/{session_id}/manifest",
        json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": compute_ledger(correct)},
        headers=h,
    )
    r = client.put(
        f"/api/v1/sync/sessions/{session_id}/window?offset=0",
        content=oversized,
        headers=h,
    )
    assert r.status_code == 400


def test_validate_window_incomplete_checkpoint_deferred():
    from sync_api import _validate_window, CHECKPOINT_SIZE
    import xxhash as _xxhash
    # Data is half a checkpoint — no complete checkpoint, so svb stays at 0
    data = b"P" * (CHECKPOINT_SIZE // 2)
    ledger = [_xxhash.xxh32(b"P" * CHECKPOINT_SIZE).intdigest()]
    result = _validate_window(data, 0, ledger, CHECKPOINT_SIZE, CHECKPOINT_SIZE)
    assert result == 0  # incomplete — deferred


def test_validate_window_ledger_exhausted():
    from sync_api import _validate_window, CHECKPOINT_SIZE
    import xxhash as _xxhash
    # More data than ledger entries — should break at ledger bounds
    block = b"Q" * CHECKPOINT_SIZE
    ledger = [_xxhash.xxh32(block).intdigest()]  # only one entry
    # Two checkpoints of data but only one ledger entry
    data = block + block
    result = _validate_window(data, 0, ledger, CHECKPOINT_SIZE, CHECKPOINT_SIZE * 2)
    assert result == CHECKPOINT_SIZE  # only first validated


def test_start_inbound_auto_claims_profile(client, conn):
    """First upload with a user_key auto-claims the profile for the device owner
    and backfills any prior NULL-owner transactions for that profile."""
    tok = pair_device(client, DEVICE_A)
    profile_id = "AABBCCDDEEFF00112233445566778899"

    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id, title_id, source_device_id, direction, state, user_key, owner_user_id,"
        "  created_at, updated_at)"
        " VALUES ('pre-txn-111', ?, ?, 'inbound', 'READY_FOR_RESTORE', ?, NULL,"
        "  '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (TITLE_1, DEVICE_A, profile_id),
    )
    conn.commit()

    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_2, "total_size_bytes": 1024, "user_key": profile_id},
        headers=sync_hdrs(DEVICE_A, tok),
    )
    assert r.status_code == 200

    admin_uid = get_uid(conn, "admin")
    claim = conn.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?",
        (DEVICE_A, profile_id),
    ).fetchone()
    assert claim is not None and claim["user_id"] == admin_uid

    txn_id = r.json()["transaction_id"]
    row = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["owner_user_id"] == admin_uid

    pre = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id='pre-txn-111'"
    ).fetchone()
    assert pre["owner_user_id"] == admin_uid

def test_auto_claim_db_error_rolls_back(client, conn, monkeypatch):
    """Exception inside auto-claim transaction triggers ROLLBACK: no partial commit."""
    from main import app as _app
    from fastapi.testclient import TestClient
    import database as db_mod

    token = pair_device(client, DEVICE_A)
    original = db_mod.upsert_device_profile
    called = {"n": 0}

    def _raise(*args, **kwargs):
        called["n"] += 1
        if called["n"] == 1:
            raise RuntimeError("simulated DB failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(db_mod, "upsert_device_profile", _raise)
    nc = TestClient(_app, raise_server_exceptions=False)
    r = nc.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": "0100F2C0115B6000", "total_size_bytes": 1024, "user_key": "AABBCCDD11223344",
              "user_display": "Player"},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 500
    # ROLLBACK must have prevented any device_profile_map row from being written.
    rows = conn.execute(
        "SELECT * FROM device_profile_map WHERE device_id=? AND profile_id=?",
        (DEVICE_A, "AABBCCDD11223344"),
    ).fetchall()
    assert rows == [], "auto-claim row should have been rolled back"
