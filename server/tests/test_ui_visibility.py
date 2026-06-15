"""
Per-user visibility tests.
Ownership determines visibility — no admin bypass for content endpoints.
"""

import database as db
from helpers import (
    DEVICE_A, DEVICE_B, TITLE_1, TITLE_2,
    auth_header, do_upload, login_admin, pair_device,
)

SAVE_A = b"alice-save" * 100
SAVE_B = b"bob-save" * 100
PROFILE_A = "AAAA000011112222"
PROFILE_B = "BBBB000011112222"


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _create_user(client, username, password="pw"):
    admin = login_admin(client)
    client.post(
        "/api/v1/ui/users",
        json={"username": username, "password": password},
        headers=auth_header(admin),
    )


def _login(client, username, password="pw") -> str:
    r = client.post("/api/v1/ui/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["admin_token"]


def _pair_to_user(client, device_id: str, user_id: str) -> str:
    """Register device, pair it, and assign ownership to user_id. Returns device token."""
    # Register the device via the sync config endpoint
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": device_id})
    admin = login_admin(client)
    r = client.post(
        f"/api/v1/ui/devices/{device_id}/token",
        json={"user_id": user_id},
        headers=auth_header(admin),
    )
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["token"]


# ── Visibility — games ─────────────────────────────────────────────────────────

def test_non_admin_games_filtered_by_owner(client):
    """Alice sees only her own games; Bob's games are invisible to her."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    tok_b = _pair_to_user(client, DEVICE_B, "bob")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)
    do_upload(client, DEVICE_B, TITLE_2, SAVE_B, device_token=tok_b)

    alice_tok = _login(client, "alice")
    r = client.get("/api/v1/ui/games", headers=auth_header(alice_tok))
    titles = [g["title_id"] for g in r.json()["games"]]
    assert TITLE_1 in titles
    assert TITLE_2 not in titles


def test_admin_games_also_filtered_by_owner(client):
    """Admin is subject to the same ownership filter — cannot see other users' games."""
    _create_user(client, "alice")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)

    admin_tok = login_admin(client)
    r = client.get("/api/v1/ui/games", headers=auth_header(admin_tok))
    titles = [g["title_id"] for g in r.json()["games"]]
    assert TITLE_1 not in titles  # admin's own games only; alice owns this


def test_non_admin_game_detail_snapshots_filtered(client):
    """User B cannot see User A's snapshots for the same title."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    tok_b = _pair_to_user(client, DEVICE_B, "bob")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)
    do_upload(client, DEVICE_B, TITLE_1, SAVE_B, device_token=tok_b)

    bob_tok = _login(client, "bob")
    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=auth_header(bob_tok))
    owners = [s["owner_user_id"] for s in r.json()["snapshots"]]
    assert all(o == "bob" for o in owners), f"bob sees non-owned snapshots: {owners}"


# ── Visibility — events ────────────────────────────────────────────────────────

def test_events_not_leaked_across_shared_title(client):
    """Two users owning the same game do not see each other's events."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    tok_b = _pair_to_user(client, DEVICE_B, "bob")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)
    do_upload(client, DEVICE_B, TITLE_1, SAVE_B, device_token=tok_b)

    alice_tok = _login(client, "alice")
    r = client.get("/api/v1/ui/events", headers=auth_header(alice_tok))
    for evt in r.json()["events"]:
        assert evt["title_id"] != TITLE_1 or evt.get("device_id") == DEVICE_A, (
            f"alice sees an event from {evt.get('device_id')} (not her device)"
        )


# ── Visibility — dashboard ─────────────────────────────────────────────────────

def test_dashboard_counts_scoped_to_user(client):
    """Dashboard stats reflect only the requesting user's data."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    tok_b = _pair_to_user(client, DEVICE_B, "bob")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)
    do_upload(client, DEVICE_B, TITLE_2, SAVE_B, device_token=tok_b)

    alice_tok = _login(client, "alice")
    r = client.get("/api/v1/ui/dashboard", headers=auth_header(alice_tok))
    stats = r.json()["stats"]
    assert stats["total_games"] == 1  # only TITLE_1
    recent_titles = [g["title_id"] for g in r.json()["recent_games"]]
    assert TITLE_1 in recent_titles
    assert TITLE_2 not in recent_titles


# ── Backfill ──────────────────────────────────────────────────────────────────

def test_backfill_on_claim_makes_history_visible(client, conn):
    """Claiming a profile backfills owner_user_id on historical saves."""
    _create_user(client, "alice")

    # Upload with PROFILE_A — owner_user_id goes to device owner (admin) by default
    pair_device(client, DEVICE_A)
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, user_key=PROFILE_A)

    # Simulate pre-claim NULL state (saves existed before profile system)
    conn.execute("UPDATE sync_transactions SET owner_user_id=NULL WHERE user_key=?", (PROFILE_A,))
    conn.execute("UPDATE events SET owner_user_id=NULL WHERE owner_user_id='admin'")

    alice_tok = _login(client, "alice")
    r = client.get("/api/v1/ui/games", headers=auth_header(alice_tok))
    assert r.json()["games"] == [], "alice should see nothing before claiming"

    # Register profile so claim endpoint accepts it
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice Profile")

    # Alice claims her profile
    r = client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}",
        headers=auth_header(alice_tok),
    )
    assert r.status_code == 200, r.text

    # History should now be visible
    r = client.get("/api/v1/ui/games", headers=auth_header(alice_tok))
    titles = [g["title_id"] for g in r.json()["games"]]
    assert TITLE_1 in titles, "alice should see TITLE_1 after claiming profile"


def test_unclaim_does_not_strip_ownership(client, conn):
    """Unclaiming a profile does not remove owner_user_id from past transactions."""
    _create_user(client, "alice")
    tok_a = _pair_to_user(client, DEVICE_A, "alice")
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, user_key=PROFILE_A, device_token=tok_a)

    # Register + claim profile for alice
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")
    alice_tok = _login(client, "alice")
    client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}",
        headers=auth_header(alice_tok),
    )

    # Unclaim
    client.delete(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}",
        headers=auth_header(alice_tok),
    )

    # owner_user_id must remain on past transactions
    row = conn.execute(
        "SELECT owner_user_id FROM sync_transactions WHERE user_key=?", (PROFILE_A,)
    ).fetchone()
    assert row["owner_user_id"] == "alice", "unclaim must not strip historical ownership"


# ── Device discoverability ─────────────────────────────────────────────────────

def test_device_list_only_shows_accessible_devices(client):
    """Under the ownership model, users only see devices they own or have been shared with."""
    _create_user(client, "alice")
    _create_user(client, "bob")
    # alice pairs DEVICE_A (becomes owner)
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    r = client.post("/api/v1/ui/devices/pair",
                    json={"code": client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A}).json().get("pairing_code", "")},
                    headers=auth_header(alice_tok))
    # bob has no access
    bob_tok = _login(client, "bob")
    r = client.get("/api/v1/ui/devices", headers=auth_header(bob_tok))
    assert r.status_code == 200
    assert r.json()["devices"] == []


# ── Admin management powers unaffected ────────────────────────────────────────

def test_admin_can_pair_device(client):
    """Admin device pairing still works."""
    admin_tok = login_admin(client)
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    r = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/token",
        headers=auth_header(admin_tok),
    )
    assert r.status_code == 200
    assert "token" in r.json()


def test_admin_can_reassign_profile(client, conn):
    """Admin can assign a profile to a specific user."""
    _create_user(client, "alice")
    pair_device(client, DEVICE_A)
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_A, "Alice")

    admin_tok = login_admin(client)
    r = client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}",
        json={"user_id": "alice"},
        headers=auth_header(admin_tok),
    )
    assert r.status_code == 200
    owner = db.get_profile_owner(conn, DEVICE_A, PROFILE_A)
    assert owner == "alice"


# ── Game detail badge visibility without claimed profile ───────────────────────


def test_game_detail_shows_uploader_badge_without_profile_claim(client):
    """device_sync_matrix includes the uploading device even when device_profile_map is empty."""
    tok = pair_device(client, DEVICE_A)
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok)

    admin_tok = login_admin(client)
    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=auth_header(admin_tok))
    assert r.status_code == 200, r.text
    matrix_ids = [e["device_id"] for e in r.json()["device_sync_matrix"]]
    assert DEVICE_A in matrix_ids, f"uploader not in matrix: {matrix_ids}"


def test_game_detail_shows_recipient_badge_without_profile_claim(client, conn):
    """device_sync_matrix includes the outbound target even when device_profile_map is empty."""
    tok_a = pair_device(client, DEVICE_A)
    pair_device(client, DEVICE_B)
    do_upload(client, DEVICE_A, TITLE_1, SAVE_A, device_token=tok_a)

    # Simulate a completed outbound delivery to DEVICE_B
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id, direction, state, source_device_id, target_device_id,"
        "  title_id, snapshot_sequence, owner_user_id, created_at, updated_at)"
        " VALUES ('test-out-1','outbound','COMPLETED',?,?,?,1,'admin',datetime('now'),datetime('now'))",
        (DEVICE_A, DEVICE_B, TITLE_1),
    )

    admin_tok = login_admin(client)
    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=auth_header(admin_tok))
    assert r.status_code == 200, r.text
    matrix_ids = [e["device_id"] for e in r.json()["device_sync_matrix"]]
    assert DEVICE_B in matrix_ids, f"recipient not in matrix: {matrix_ids}"
