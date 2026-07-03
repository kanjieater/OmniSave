"""
Profile mapping tests.
DB layer: device_known_profiles, device_profile_map, ownership resolution.
HTTP: GET/PUT/DELETE /api/v1/ui/devices/{id}/profiles
Inbound ownership stamping in start_inbound.
"""

import sqlite3

import pytest

import database as db
from helpers import DEVICE_A, TITLE_1, auth_header, do_upload, login_admin, sync_hdrs

SAVE = b"save-data" * 100
PROFILE_A = "AAAA000011112222"
PROFILE_B = "BBBB000011112222"
PROFILE_C = "CCCC000011112222"


def _hdr(token):
    return auth_header(token)


def _seed(client, device_id=DEVICE_A, user_key=""):
    do_upload(client, device_id, TITLE_1, SAVE, user_key=user_key)


def _pair(client, device_id=DEVICE_A, user_id=None):
    admin = login_admin(client)
    body = {"user_id": user_id} if user_id else None
    r = client.post(f"/api/v1/ui/devices/{device_id}/token", json=body, headers=_hdr(admin))
    assert r.status_code == 200
    return r.json()["token"]


def _create_user(client, username, password="pw"):
    admin = login_admin(client)
    client.post("/api/v1/ui/users", json={"username": username, "password": password}, headers=_hdr(admin))


def _login(client, username, password="pw"):
    return client.post("/api/v1/ui/auth/login", json={"username": username, "password": password}).json()["admin_token"]


# ── DB layer ──────────────────────────────────────────────────────────────────


def test_db_upsert_known_profile_creates_and_updates(conn):
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")
    row = conn.execute(
        "SELECT profile_name FROM device_known_profiles WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROFILE_A),
    ).fetchone()
    assert row["profile_name"] == "Alice"
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice Renamed")
    row2 = conn.execute(
        "SELECT profile_name FROM device_known_profiles WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROFILE_A),
    ).fetchone()
    assert row2["profile_name"] == "Alice Renamed"



def test_db_upsert_and_get_profile_owner(conn):
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "user_alice", "Alice")
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) == "user_alice"


def test_db_get_profile_owner_unclaimed_returns_none(conn):
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "")
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) is None


def test_db_get_profile_owner_unknown_returns_none(conn):
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_C) is None


def test_db_user_can_claim_only_one_profile_per_device(conn):
    """One OmniSave account may only claim ONE profile per device — second claim evicts first."""
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "")
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_B, "")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "user_alice")
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) == "user_alice"
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_B, "user_alice")  # evicts PROFILE_A
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) is None
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_B) == "user_alice"


def test_db_list_device_profiles_merges_known_and_claimed(conn):
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_B, "Bob")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "user_alice")
    profiles = db.list_device_profiles(conn, DEVICE_A)
    assert len(profiles) == 2
    by_id = {p["profile_id"]: p for p in profiles}
    assert by_id[PROFILE_A]["user_id"] == "user_alice"
    assert by_id[PROFILE_B]["user_id"] is None


def test_db_delete_profile_leaves_known_profile(conn):
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "user_alice")
    db.delete_device_profile(conn, DEVICE_A, PROFILE_A, "user_alice")
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) is None
    row = conn.execute(
        "SELECT * FROM device_known_profiles WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROFILE_A),
    ).fetchone()
    assert row is not None


# ── Ownership stamping in start_inbound ──────────────────────────────────────


def test_ownership_claimed_profile_stamps_owner(client, conn, device_token):
    _create_user(client, "alice")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}",
        json={"user_id": "alice"},
        headers=_hdr(admin),
    )
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE), "user_key": PROFILE_A},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 200
    txn_id = r.json()["transaction_id"]
    owner = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["owner_user_id"]
    assert owner == "alice"


def test_ownership_unclaimed_profile_auto_claimed_for_device_owner(client, conn, device_token):
    """Single-owner device: first upload auto-claims profile for device owner."""
    _seed(client, user_key=PROFILE_A)
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE), "user_key": PROFILE_A},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 200
    txn_id = r.json()["transaction_id"]
    owner = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["owner_user_id"]
    assert owner == "admin"  # auto-claimed for device owner on first upload


def test_ownership_first_seen_profile_auto_claimed_for_device_owner(client, conn, device_token):
    """First-seen profile on a single-owner device → auto-claimed for device owner."""
    _seed(client)
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE), "user_key": PROFILE_C},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    assert r.status_code == 200
    txn_id = r.json()["transaction_id"]
    owner = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["owner_user_id"]
    assert owner == "admin"  # auto-claimed for device owner (no multi-user claims on device)


def test_ownership_no_user_key_stamps_device_owner(client, conn, device_token):
    """No user_key at all → always stamps the device's paired user."""
    _seed(client, user_key=PROFILE_A)
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers=sync_hdrs(DEVICE_A, device_token),
    )
    txn_id = r.json()["transaction_id"]
    owner = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["owner_user_id"]
    assert owner == "admin"


def test_ownership_unpaired_device_rejected(client):
    """No token → 401. Unpaired devices cannot upload."""
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": TITLE_1, "total_size_bytes": len(SAVE)},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 401


# ── HTTP: GET /profiles ───────────────────────────────────────────────────────


def test_http_list_profiles_empty(client):
    _seed(client)
    admin = login_admin(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(admin))
    assert r.status_code == 200
    assert r.json()["profiles"] == []


def test_http_list_profiles_admin_sees_real_user_id(client):
    _create_user(client, "alice")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", json={"user_id": "alice"}, headers=_hdr(admin))
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(admin))
    profiles = r.json()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["user_id"] == "alice"


def test_http_list_profiles_non_admin_masks_other_users(client):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _seed(client, user_key=PROFILE_A)
    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key=PROFILE_B)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", json={"user_id": "alice"}, headers=_hdr(admin))
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_B}", json={"user_id": "bob"}, headers=_hdr(admin))

    alice_token = _login(client, "alice")
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(alice_token))
    by_id = {p["profile_id"]: p["user_id"] for p in r.json()["profiles"]}
    assert by_id[PROFILE_A] == "alice"
    assert by_id[PROFILE_B] == "__claimed__"


def test_http_list_profiles_non_admin_sees_own_profile(client):
    _create_user(client, "alice")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", json={"user_id": "alice"}, headers=_hdr(admin))

    alice_token = _login(client, "alice")
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(alice_token))
    assert r.json()["profiles"][0]["user_id"] == "alice"


# ── HTTP: PUT /profiles/{id} ──────────────────────────────────────────────────


def test_http_claim_profile_ok(client):
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_http_claim_profile_unknown_profile_404(client):
    _seed(client)
    admin = login_admin(client)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    assert r.status_code == 404


def test_http_claim_multiple_profiles_same_user(client):
    """Same user can claim multiple profiles on the same device."""
    _seed(client, user_key=PROFILE_A)
    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key=PROFILE_B)
    admin = login_admin(client)
    r1 = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    assert r1.status_code == 200
    r2 = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_B}", headers=_hdr(admin))
    assert r2.status_code == 200


# ── HTTP: DELETE /profiles/{id} ───────────────────────────────────────────────


def test_http_unclaim_profile_204(client, conn):
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    assert r.status_code == 204
    assert db.get_profile_owner(conn, DEVICE_A, PROFILE_A) is None


def test_http_unclaim_profile_not_yours_403(client):
    _create_user(client, "alice")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    alice_token = _login(client, "alice")
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(alice_token))
    assert r.status_code == 403


def test_http_unclaim_leaves_known_profile(client, conn):
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    row = conn.execute(
        "SELECT * FROM device_known_profiles WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROFILE_A),
    ).fetchone()
    assert row is not None


# ── Golden-path integration ───────────────────────────────────────────────────


def test_golden_path_ownership_model(client, conn, device_token):
    """Full ownership: two claimed profiles stamp correct users; unknown key falls back to device owner."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key=PROFILE_A)
    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key=PROFILE_B)
    admin = login_admin(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", json={"user_id": "alice"}, headers=_hdr(admin))
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_B}", json={"user_id": "bob"}, headers=_hdr(admin))

    def _owner(user_key):
        r = client.post(
            "/api/v1/sync/transactions/inbound",
            json={"title_id": TITLE_1, "total_size_bytes": len(SAVE), "user_key": user_key},
            headers=sync_hdrs(DEVICE_A, device_token),
        )
        assert r.status_code == 200
        return conn.execute(
            "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?",
            (r.json()["transaction_id"],),
        ).fetchone()["owner_user_id"]

    assert _owner(PROFILE_A) == "alice"
    assert _owner(PROFILE_B) == "bob"
    assert _owner(PROFILE_C) is None  # unknown key → NULL (T6), not device owner


# ── Admin unclaim multi-claim disambiguation ──────────────────────────────────


def test_admin_unclaim_target_user_id_removes_specific_claimant(client, conn):
    """Admin DELETE with ?target_user_id= removes only that user's claim."""
    _create_user(client, "alice")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    # Insert two claims directly — the claim_profile API auto-evicts the assigner's own claim
    # when assigning to another user, so we bypass it to create a genuine multi-claim state.
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Profile A")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "admin", "Profile A")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "alice", "Profile A")
    r = client.delete(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}?target_user_id=alice",
        headers=_hdr(admin),
    )
    assert r.status_code == 204
    # alice's claim is gone; admin's claim remains
    rows = conn.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROFILE_A),
    ).fetchall()
    claimants = {r["user_id"] for r in rows}
    assert "alice" not in claimants
    assert "admin" in claimants


def test_admin_unclaim_multiple_claimants_no_target_returns_409(client, conn):
    """Admin DELETE without ?target_user_id= returns 409 when multiple users share a profile."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    _seed(client, user_key=PROFILE_A)
    admin = login_admin(client)
    # Insert alice and bob claims directly so admin has no own claim on PROFILE_A —
    # only then does the 409 multi-claimant path trigger (admin's own claim bypasses it).
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Profile A")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "alice", "Profile A")
    db.upsert_device_profile(conn, DEVICE_A, PROFILE_A, "bob", "Profile A")
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", headers=_hdr(admin))
    assert r.status_code == 409
    body = r.json()
    assert "claimants" in body
    assert set(body["claimants"]) == {"alice", "bob"}
