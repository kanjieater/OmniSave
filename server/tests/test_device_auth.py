"""
Device pairing and token management tests.
POST/GET/DELETE /api/v1/ui/devices/{device_id}/token
"""

from helpers import DEVICE_A, DEVICE_B, do_upload, login_admin, auth_header, TITLE_1

SAVE = b"save-data" * 100
DEVICE_C = "CCDDEE112233"


def _login(client) -> str:
    return login_admin(client)


def _hdr(token: str) -> dict:
    return auth_header(token)


def _seed_device(client):
    """Register a device via bootstrap without pairing (device-config endpoint)."""
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})


# ── Token generation ──────────────────────────────────────────────────────────


def test_pair_device_returns_token(client):
    _seed_device(client)
    token = _login(client)
    r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    assert r.status_code == 200
    t = r.json()["token"]
    assert t.startswith("sk_device_")


def test_pair_device_404_if_device_not_registered(client):
    token = _login(client)
    r = client.post("/api/v1/ui/devices/NOTEXIST001/token", headers=_hdr(token))
    assert r.status_code == 404


def test_pair_device_requires_auth(client):
    r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token")
    assert r.status_code == 401


def test_pair_device_token_is_unique_per_call(client):
    _seed_device(client)
    token = _login(client)
    t1 = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token)).json()["token"]
    t2 = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token)).json()["token"]
    assert t1 != t2  # second call rotates


# ── Token status ──────────────────────────────────────────────────────────────


def test_device_token_status_unpaired(client):
    # Register device without pairing via bootstrap endpoint
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["has_token"] is False


def test_device_token_status_paired(client):
    _seed_device(client)
    token = _login(client)
    client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    data = r.json()
    assert data["has_token"] is True
    assert data["user_id"] == "admin"


def test_device_token_status_requires_auth(client):
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token")
    assert r.status_code == 401


# ── Token revocation ──────────────────────────────────────────────────────────


def test_revoke_device_token(client):
    _seed_device(client)
    token = _login(client)
    client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    assert r.status_code == 204
    # Status shows unpaired
    s = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token)).json()
    assert s["has_token"] is False


def test_revoke_nonexistent_token_404(client):
    _seed_device(client)
    token = _login(client)
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    assert r.status_code == 404


def test_revoke_requires_auth(client):
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/token")
    assert r.status_code == 401


# ── Admin pairing to another user ─────────────────────────────────────────────


def test_admin_can_pair_device_to_other_user(client):
    _seed_device(client)
    token = _login(client)
    # Create a secondary user
    client.post("/api/v1/ui/users", json={"username": "wife", "password": "pw"}, headers=_hdr(token))
    # Admin pairs device to wife
    r = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/token",
        json={"user_id": "wife"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    s = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token)).json()
    assert s["user_id"] == "wife"


def test_admin_pair_to_unknown_user_400(client):
    _seed_device(client)
    token = _login(client)
    r = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/token",
        json={"user_id": "nobody"},
        headers=_hdr(token),
    )
    assert r.status_code == 400


# ── Non-admin pairing ─────────────────────────────────────────────────────────


def test_non_admin_pairs_to_self(client):
    _seed_device(client)
    admin_token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "player", "password": "pw"}, headers=_hdr(admin_token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "player", "password": "pw"}).json()["admin_token"]
    # Non-admin pairs device — linked to their own user_id
    r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(user_token))
    assert r.status_code == 200
    # Status shows player's user_id (admin can see it)
    s = client.get(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(admin_token)).json()
    assert s["user_id"] == "player"


def test_non_admin_cannot_revoke_other_users_device(client):
    _seed_device(client)
    admin_token = _login(client)
    # Admin pairs device to admin
    client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(admin_token))
    # Non-admin tries to revoke it
    client.post("/api/v1/ui/users", json={"username": "intruder", "password": "pw"}, headers=_hdr(admin_token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "intruder", "password": "pw"}).json()["admin_token"]
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(user_token))
    assert r.status_code == 403


# ── DB helpers ────────────────────────────────────────────────────────────────


def test_db_create_and_get_device_auth(conn):
    from datetime import UTC, datetime
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)",
        (DEVICE_A, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    import database as db
    token = db.create_device_token(conn, DEVICE_A, "admin")
    assert token.startswith("sk_device_")
    row = db.get_device_auth(conn, DEVICE_A)
    assert row["user_id"] == "admin"
    row2 = db.get_device_auth_by_token(conn, token)
    assert row2["device_id"] == DEVICE_A


def test_db_rotate_device_token(conn):
    from datetime import UTC, datetime
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)",
        (DEVICE_A, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    import database as db
    t1 = db.create_device_token(conn, DEVICE_A, "admin")
    t2 = db.rotate_device_token(conn, DEVICE_A)
    assert t1 != t2
    assert db.get_device_auth_by_token(conn, t1) is None
    assert db.get_device_auth_by_token(conn, t2) is not None


def test_db_revoke_device_token(conn):
    from datetime import UTC, datetime
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)",
        (DEVICE_A, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    import database as db
    token = db.create_device_token(conn, DEVICE_A, "admin")
    db.revoke_device_token(conn, DEVICE_A)
    assert db.get_device_auth_by_token(conn, token) is None
    assert db.get_device_auth(conn, DEVICE_A) is None


def test_db_touch_last_seen(conn):
    from datetime import UTC, datetime
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)",
        (DEVICE_A, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    import database as db
    db.create_device_token(conn, DEVICE_A, "admin")
    db.touch_device_last_seen(conn, DEVICE_A)
    row = db.get_device_auth(conn, DEVICE_A)
    assert row["last_seen"] is not None


def test_db_create_inbound_transaction_with_owner(conn):
    import database as db
    txn_id, _ = db.create_inbound_transaction(
        conn, DEVICE_A, TITLE_1, 1024, None, owner_user_id="admin"
    )
    row = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["owner_user_id"] == "admin"


def test_db_create_inbound_transaction_without_owner(conn):
    import database as db
    txn_id, _ = db.create_inbound_transaction(conn, DEVICE_A, TITLE_1, 1024, None)
    row = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["owner_user_id"] is None


# ── Sync auth middleware integration ─────────────────────────────────────────


def _get_device_token(client, device_id: str = DEVICE_A) -> str:
    """Pair device and return token. Device must already be registered."""
    admin_token = login_admin(client)
    r = client.post(
        f"/api/v1/ui/devices/{device_id}/token",
        headers=auth_header(admin_token),
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_sync_with_valid_device_token_stamps_owner(client, conn):
    """TrustedDevice path: valid token → owner_user_id set at transaction creation."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE)  # registers + pairs as admin
    device_token = _get_device_token(client, DEVICE_A)  # rotates token

    # Now start a new inbound transaction with the device token
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={
            "X-Device-ID": DEVICE_A,
            "Authorization": f"Bearer {device_token}",
        },
    )
    assert r.status_code == 200
    txn_id = r.json()["transaction_id"]
    row = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["owner_user_id"] == "admin"


def test_sync_without_token_rejected(client):
    """No token → 401. Unpaired devices cannot upload."""
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 401


def test_sync_with_invalid_device_token_returns_401(client):
    """Invalid token → 401, not 200."""
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={
            "X-Device-ID": DEVICE_A,
            "Authorization": "Bearer sk_device_invalid_token_here",
        },
    )
    assert r.status_code == 401


def test_sync_with_token_from_wrong_device_returns_401(client):
    """Token is valid but belongs to a different device → 401."""
    do_upload(client, DEVICE_A, TITLE_1, SAVE)  # register DEVICE_A
    do_upload(client, DEVICE_B, TITLE_1, SAVE)  # register DEVICE_B
    device_a_token = _get_device_token(client, DEVICE_A)

    # Use DEVICE_A's token but claim to be DEVICE_B
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={
            "X-Device-ID": DEVICE_B,
            "Authorization": f"Bearer {device_a_token}",
        },
    )
    assert r.status_code == 401


def test_sync_device_token_updates_last_seen(client, conn):
    """last_seen is NULL right after pairing; set on first authenticated sync."""
    # Register device without syncing, then pair it
    import database as db
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)", (DEVICE_A, now, now),
    )
    device_token = _get_device_token(client, DEVICE_A)
    # last_seen is NULL immediately after pairing (no sync yet)
    row_before = conn.execute(
        "SELECT last_seen FROM device_auth WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row_before["last_seen"] is None

    client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    row_after = conn.execute(
        "SELECT last_seen FROM device_auth WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row_after["last_seen"] is not None
