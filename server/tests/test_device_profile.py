"""
Device profile mapping tests.
  DB helpers: set_device_config_pending, consume_pending_config, upsert_known_profile,
              upsert_device_profile, get_profile_owner,
              get_user_profile_on_device, delete_device_profile, list_device_profiles
  HTTP: POST /api/v1/sync/device-config
        GET/PUT/DELETE /api/v1/ui/devices/{device_id}/profiles/{profile_id}
        POST /api/v1/ui/devices/{device_id}/token  (sets config_pending)
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
import database as db
from helpers import (
    DEVICE_A,
    DEVICE_B,
    TITLE_1,
    auth_header,
    do_upload,
    login_admin,
    pair_device,
)

SAVE = b"profile-save" * 100
PROF_A = "00000000000000AA"
PROF_B = "00000000000000BB"


# ── helpers ───────────────────────────────────────────────────────────────────


def _login(client):
    return login_admin(client)


def _hdr(token):
    return auth_header(token)


def _seed(client, device_id=DEVICE_A, user_key="", user_display=""):
    """Register device via upload."""
    do_upload(client, device_id, TITLE_1, SAVE, user_key=user_key, user_display=user_display)


def _create_user(client, admin_token, username="player", password="pw"):
    client.post("/api/v1/ui/users", json={"username": username, "password": password}, headers=_hdr(admin_token))
    return client.post("/api/v1/ui/auth/login", json={"username": username, "password": password}).json()["admin_token"]


def _insert_device(conn, device_id=DEVICE_A):
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, '', '', ?, ?)",
        (device_id, now, now),
    )


# ── DB: config_pending ────────────────────────────────────────────────────────


def test_db_set_config_pending(conn):
    _insert_device(conn)
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    row = conn.execute("SELECT config_pending FROM device_auth WHERE device_id=?", (DEVICE_A,)).fetchone()
    assert row["config_pending"] == 1


def test_db_consume_pending_config_returns_token(conn):
    _insert_device(conn)
    token = db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    last_seen = datetime.now(UTC).isoformat()
    result = db.consume_pending_config(conn, DEVICE_A, last_seen)
    assert result == token


def test_db_consume_pending_config_clears_flag(conn):
    _insert_device(conn)
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    last_seen = datetime.now(UTC).isoformat()
    db.consume_pending_config(conn, DEVICE_A, last_seen)
    # Second call returns nothing — flag cleared
    result = db.consume_pending_config(conn, DEVICE_A, last_seen)
    assert result is None


def test_db_consume_pending_config_rejects_stale_last_seen(conn):
    _insert_device(conn)
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    old = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    result = db.consume_pending_config(conn, DEVICE_A, old)
    assert result is None


def test_db_consume_pending_config_no_flag(conn):
    _insert_device(conn)
    db.create_device_token(conn, DEVICE_A, "admin")
    last_seen = datetime.now(UTC).isoformat()
    # config_pending defaults to 0
    result = db.consume_pending_config(conn, DEVICE_A, last_seen)
    assert result is None


# ── DB: known profiles ────────────────────────────────────────────────────────


def test_db_upsert_known_profile_insert(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    rows = conn.execute("SELECT profile_name FROM device_known_profiles WHERE device_id=? AND profile_id=?", (DEVICE_A, PROF_A)).fetchall()
    assert len(rows) == 1
    assert rows[0]["profile_name"] == "Alice"


def test_db_upsert_known_profile_updates_name(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice Renamed")
    row = conn.execute("SELECT profile_name FROM device_known_profiles WHERE device_id=? AND profile_id=?", (DEVICE_A, PROF_A)).fetchone()
    assert row["profile_name"] == "Alice Renamed"



# ── DB: profile map CRUD ──────────────────────────────────────────────────────


def test_db_upsert_device_profile_and_get_owner(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user", "Alice")
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) == "alice_user"


def test_db_get_profile_owner_unknown(conn):
    _insert_device(conn)
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) is None


def test_db_upsert_device_profile_one_profile_per_user(conn):
    """One OmniSave user may only claim ONE profile per device — claiming a second evicts the first."""
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_known_profile(conn, DEVICE_A, PROF_B, "Bob")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user")
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) == "alice_user"
    db.upsert_device_profile(conn, DEVICE_A, PROF_B, "alice_user")  # evicts PROF_A claim
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) is None
    assert db.get_profile_owner(conn, DEVICE_A, PROF_B) == "alice_user"


def test_db_get_user_profile_on_device(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user")
    assert db.get_user_profile_on_device(conn, DEVICE_A, "alice_user") == PROF_A
    assert db.get_user_profile_on_device(conn, DEVICE_A, "nobody") is None


def test_db_delete_device_profile(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user")
    db.delete_device_profile(conn, DEVICE_A, PROF_A, "alice_user")
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) is None


def test_db_list_device_profiles_empty(conn):
    _insert_device(conn)
    assert db.list_device_profiles(conn, DEVICE_A) == []


def test_db_list_device_profiles_unclaimed(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    result = db.list_device_profiles(conn, DEVICE_A)
    assert len(result) == 1
    assert result[0]["profile_id"] == PROF_A
    assert result[0]["user_id"] is None


def test_db_list_device_profiles_claimed(conn):
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user", "Alice")
    result = db.list_device_profiles(conn, DEVICE_A)
    assert result[0]["user_id"] == "alice_user"
    assert result[0]["profile_name"] == "Alice"
    assert result[0]["is_mine"] is False  # no user_id passed → never mine


def test_db_list_device_profiles_is_mine(conn):
    """is_mine reflects the requesting user's own claim; one row per profile even when co-claimed."""
    _insert_device(conn)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "alice_user", "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "bob_user", "Alice")

    # Alice sees profile as hers
    result = db.list_device_profiles(conn, DEVICE_A, "alice_user")
    assert len(result) == 1, "co-claimed profile must appear only once"
    assert result[0]["is_mine"] is True
    assert result[0]["user_id"] == "alice_user"

    # Bob sees it as his too
    result = db.list_device_profiles(conn, DEVICE_A, "bob_user")
    assert len(result) == 1
    assert result[0]["is_mine"] is True

    # Carol (no claim) sees it as claimed by someone else, not mine
    result = db.list_device_profiles(conn, DEVICE_A, "carol_user")
    assert len(result) == 1
    assert result[0]["is_mine"] is False
    assert result[0]["user_id"] is not None  # some other claimant visible


# ── HTTP: POST /sync/device-config ────────────────────────────────────────────


def test_device_config_missing_device_id(client):
    r = client.post("/api/v1/sync/device-config", json={})
    assert r.status_code == 400


def test_device_config_unpaired_device_returns_pairing_code(client):
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": PROF_A, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    data = r.json()
    assert "pairing_code" in data
    assert len(data["pairing_code"]) == 6


def test_device_config_upserts_known_profiles(client):
    _seed(client)
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": PROF_A, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    # Verify profile stored via UI list endpoint
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token))
    assert r.status_code == 200
    ids = [p["profile_id"] for p in r.json()["profiles"]]
    assert PROF_A in ids


def test_device_config_no_pending_returns_empty_when_bearer_sent(client, conn):
    """Device sends its token as Bearer and config_pending=0 → {} (nothing to deliver)."""
    _seed(client)
    device_token = pair_device(client, DEVICE_A)
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (DEVICE_A,))
    r = client.post(
        "/api/v1/sync/device-config",
        json={},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.status_code == 200
    assert r.json() == {}


def test_device_config_delivers_token_when_pending(client):
    _seed(client)
    token = _login(client)
    pair_r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    assert pair_r.status_code == 200
    expected_token = pair_r.json()["token"]
    r = client.post(
        "/api/v1/sync/device-config",
        json={},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert r.json().get("device_token") == expected_token


def test_device_config_returns_empty_on_second_call_when_bearer_sent(client):
    """Once device has its token and sends Bearer, device-config returns {} (nothing to deliver)."""
    _seed(client)
    token = _login(client)
    pair_r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    device_token = pair_r.json()["token"]
    # First call (no Bearer): delivers token
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    # Second call (device now has its token, sends Bearer): nothing to do
    r = client.post(
        "/api/v1/sync/device-config",
        json={},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.json() == {}


# ── HTTP: GET /ui/devices/{id}/profiles ──────────────────────────────────────


def test_list_profiles_requires_auth(client):
    _seed(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles")
    assert r.status_code == 401


def test_list_profiles_device_not_found(client):
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token))
    assert r.status_code == 404


def test_list_profiles_empty(client):
    _seed(client)
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["profiles"] == []


def test_list_profiles_populated_via_upload(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token))
    assert r.status_code == 200
    profiles = r.json()["profiles"]
    assert any(p["profile_id"] == PROF_A for p in profiles)


def test_list_profiles_non_admin_masks_other_user(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    admin_token = _login(client)
    # admin claims PROF_A for themselves
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(admin_token))
    player_token = _create_user(client, admin_token, "player")
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(player_token))
    assert r.status_code == 200
    claimed = [p for p in r.json()["profiles"] if p["profile_id"] == PROF_A]
    assert claimed[0]["user_id"] == "__claimed__"


# ── HTTP: PUT /ui/devices/{id}/profiles/{profile_id} ─────────────────────────


def test_claim_profile_requires_auth(client):
    _seed(client, user_key=PROF_A)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}")
    assert r.status_code == 401


def test_claim_profile_device_not_found(client):
    token = _login(client)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    assert r.status_code == 404


def test_claim_profile_unknown_profile(client):
    _seed(client)
    token = _login(client)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    assert r.status_code == 404


def test_claim_profile_success(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    token = _login(client)
    r = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_claim_multiple_profiles_same_user(client):
    """A user may claim multiple profiles on the same device."""
    _seed(client, user_key=PROF_A, user_display="Alice")
    do_upload(client, DEVICE_A, TITLE_1, SAVE, user_key=PROF_B, user_display="Bob")
    admin_token = _login(client)
    player_token = _create_user(client, admin_token, "player")
    # player claims both profiles on the same device — both should succeed
    r1 = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(player_token))
    assert r1.status_code == 200
    r2 = client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_B}", headers=_hdr(player_token))
    assert r2.status_code == 200


def test_admin_can_claim_for_other_user(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    admin_token = _login(client)
    _create_user(client, admin_token, "player")
    r = client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}",
        json={"user_id": "player"},
        headers=_hdr(admin_token),
    )
    assert r.status_code == 200
    # Verify owner is player
    list_r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(admin_token))
    claimed = next(p for p in list_r.json()["profiles"] if p["profile_id"] == PROF_A)
    assert claimed["user_id"] == "player"


def test_non_admin_cannot_claim_for_other_user(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    admin_token = _login(client)
    player_token = _create_user(client, admin_token, "player")
    # Non-admin sends body.user_id=admin — should be ignored, claims for self
    r = client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}",
        json={"user_id": "admin"},
        headers=_hdr(player_token),
    )
    assert r.status_code == 200
    list_r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(admin_token))
    claimed = next(p for p in list_r.json()["profiles"] if p["profile_id"] == PROF_A)
    assert claimed["user_id"] == "player"


# ── HTTP: DELETE /ui/devices/{id}/profiles/{profile_id} ──────────────────────


def test_unclaim_profile_requires_auth(client):
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}")
    assert r.status_code == 401


def test_unclaim_profile_not_claimed(client):
    _seed(client, user_key=PROF_A)
    token = _login(client)
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    assert r.status_code == 404


def test_unclaim_profile_not_own_profile(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    admin_token = _login(client)
    player_token = _create_user(client, admin_token, "player")
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(admin_token))
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(player_token))
    assert r.status_code == 403


def test_unclaim_profile_success(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    token = _login(client)
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(token))
    assert r.status_code == 204
    # Profile still in known list but unclaimed
    list_r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token))
    profile = next((p for p in list_r.json()["profiles"] if p["profile_id"] == PROF_A), None)
    assert profile is not None
    assert profile["user_id"] is None


def test_admin_can_unclaim_any_profile(client):
    _seed(client, user_key=PROF_A, user_display="Alice")
    admin_token = _login(client)
    player_token = _create_user(client, admin_token, "player")
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(player_token))
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(admin_token))
    assert r.status_code == 204


def test_unclaim_profile_unclaimed_non_admin_404(client):
    """Non-admin deleting a known but fully unclaimed profile returns 404."""
    _seed(client, user_key=PROF_A)  # registers profile as known; no claim inserted
    admin_token = _login(client)
    player_token = _create_user(client, admin_token, "player")
    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROF_A}", headers=_hdr(player_token))
    assert r.status_code == 404


# ── HTTP: pair_device sets config_pending ─────────────────────────────────────


def test_pair_device_sets_config_pending_device_config_delivers_token(client):
    _seed(client)
    token = _login(client)
    pair_r = client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(token))
    device_token = pair_r.json()["token"]
    cfg_r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    assert cfg_r.json().get("device_token") == device_token


# ── Auto-claim: device-config populates device_profile_map ───────────────────


def test_device_config_auto_claims_profile_when_device_has_owner(client, conn):
    """Profiles reported via device-config are auto-claimed for the device owner."""
    pair_device(client, DEVICE_A)
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": PROF_A, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    owner = db.get_profile_owner(conn, DEVICE_A, PROF_A)
    assert owner == "admin", f"expected auto-claim to 'admin', got {owner!r}"


def test_device_config_auto_claim_does_not_evict_existing_claimant(client, conn):
    """Auto-claim co-claims the first profile without evicting existing claimants.

    When all profiles are taken, get_auto_claim_profile falls back to co-claiming the
    first profile so the device owner always has a default selected (family-trust model).
    Both claims coexist; co-claiming grants shared save visibility by design.
    """
    _create_user(client, _login(client), "otheruser")
    pair_device(client, DEVICE_A)
    db.upsert_known_profile(conn, DEVICE_A, PROF_A, "Alice")
    db.upsert_device_profile(conn, DEVICE_A, PROF_A, "otheruser", "Alice")

    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": PROF_A, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    # Both admin (co-claim fallback) and otheruser hold a claim on the same profile.
    rows = conn.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?",
        (DEVICE_A, PROF_A),
    ).fetchall()
    claimants = {r["user_id"] for r in rows}
    assert "otheruser" in claimants, "otheruser's claim must not be evicted"
    assert "admin" in claimants, "device owner must have been co-claimed as default"


def test_device_config_auto_claim_skips_unpaired_device(client, conn):
    """No auto-claim when the device has no owner yet (not paired)."""
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": PROF_A, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert db.get_profile_owner(conn, DEVICE_A, PROF_A) is None


# ── romm index refresh trigger ────────────────────────────────────────────────


def test_device_config_changed_catalog_triggers_index_refresh(client, monkeypatch):
    """device_config with a new title schedules an immediate background scan."""
    import romm_index as _ri
    calls = []
    monkeypatch.setattr(_ri, "request_index_run_now", lambda: calls.append(1))

    r = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": ["0100000000010000"], "known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert len(calls) == 1


def test_device_config_same_catalog_does_not_retrigger_index_refresh(client, monkeypatch):
    """Identical back-to-back catalog reports do not trigger repeated index scans."""
    import romm_index as _ri
    calls = []
    monkeypatch.setattr(_ri, "request_index_run_now", lambda: calls.append(1))

    payload = {"installed_titles": ["0100000000010000"], "known_profiles": []}
    headers = {"X-Device-ID": DEVICE_A}
    r1 = client.post("/api/v1/sync/device-config", json=payload, headers=headers)
    assert r1.status_code == 200
    r2 = client.post("/api/v1/sync/device-config", json=payload, headers=headers)
    assert r2.status_code == 200
    assert len(calls) == 1  # second identical report: no re-trigger


def test_device_config_without_catalog_does_not_trigger_index_refresh(client, monkeypatch):
    """device_config without installed_titles does NOT schedule an index scan."""
    import romm_index as _ri
    calls = []
    monkeypatch.setattr(_ri, "request_index_run_now", lambda: calls.append(1))

    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert len(calls) == 0


def test_device_config_empty_catalog_triggers_refresh_if_previously_nonempty(client, monkeypatch):
    """Clearing a catalog (empty list) schedules scan when previous catalog was non-empty."""
    import romm_index as _ri
    calls = []
    monkeypatch.setattr(_ri, "request_index_run_now", lambda: calls.append(1))

    headers = {"X-Device-ID": DEVICE_A}
    r1 = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": ["0100000000010000"], "known_profiles": []},
        headers=headers,
    )
    assert r1.status_code == 200
    calls.clear()
    r2 = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": [], "known_profiles": []},
        headers=headers,
    )
    assert r2.status_code == 200
    assert len(calls) == 1


# ── Schema migration coverage ─────────────────────────────────────────────────


def test_migration_deduplicates_device_profile_map(tmp_path):
    """Migration DELETE at database.py:460 fires when old 2-col PK schema is detected.

    The old schema allowed one OmniSave user to claim multiple profiles on the same device.
    The migration collapses duplicates to the oldest row per (device_id, user_id).
    """
    raw = sqlite3.connect(str(tmp_path / "old.db"))
    raw.row_factory = sqlite3.Row
    # Minimal stub required by _apply_migrations (preservation column check at db.py:355)
    raw.execute("""
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    raw.execute("""
        CREATE TABLE device_profile_map (
            device_id    TEXT NOT NULL,
            profile_id   TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            PRIMARY KEY (device_id, profile_id)
        )
    """)
    raw.execute(
        "INSERT INTO device_profile_map VALUES ('DEV1','PROF_A','alice','Alice','2026-01-01T00:00:00Z')"
    )
    raw.execute(
        "INSERT INTO device_profile_map VALUES ('DEV1','PROF_B','alice','Alice','2026-01-02T00:00:00Z')"
    )
    raw.commit()

    db._apply_migrations(raw)

    rows = raw.execute(
        "SELECT profile_id FROM device_profile_map WHERE device_id='DEV1' AND user_id='alice'"
    ).fetchall()
    # Only the oldest row (MIN rowid = PROF_A) must survive
    assert len(rows) == 1
    assert rows[0]["profile_id"] == "PROF_A"
    raw.close()


def test_first_unclaimed_profile_stable_under_last_seen_tie(conn):
    """profile_id ASC tiebreaker: when two profiles share the same last_seen, the
    lexicographically smaller profile_id is returned deterministically."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO device_known_profiles (device_id, profile_id, profile_name, last_seen)"
        " VALUES ('DEV_TIE', 'bbbb', '', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO device_known_profiles (device_id, profile_id, profile_name, last_seen)"
        " VALUES ('DEV_TIE', 'aaaa', '', ?)",
        (now,),
    )
    result = db.get_first_unclaimed_profile(conn, "DEV_TIE", "user1")
    assert result == "aaaa"


def test_migration_crash_recovery_promotes_orphan_new_table(tmp_path):
    """Crash-recovery: device_profile_map_new orphan is promoted when device_profile_map is absent.

    Simulates a crash that happened after DROP TABLE device_profile_map but before the
    RENAME — device_profile_map_new exists, device_profile_map does not.
    _apply_migrations must rename the orphan rather than creating a fresh empty table.
    """
    raw = sqlite3.connect(str(tmp_path / "crashed.db"))
    raw.row_factory = sqlite3.Row
    raw.execute("""
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    raw.execute("""
        CREATE TABLE device_profile_map_new (
            device_id    TEXT NOT NULL,
            profile_id   TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            PRIMARY KEY (device_id, profile_id, user_id),
            UNIQUE (device_id, user_id)
        )
    """)
    raw.execute(
        "INSERT INTO device_profile_map_new VALUES ('DEV1','PROF_A','alice','Alice','2026-01-01T00:00:00Z')"
    )
    raw.commit()

    db._apply_migrations(raw)

    # Orphan must be promoted; data must survive
    row = raw.execute(
        "SELECT user_id FROM device_profile_map WHERE device_id='DEV1' AND profile_id='PROF_A'"
    ).fetchone()
    assert row is not None and row["user_id"] == "alice"
    # Orphan table must be gone
    orphan = raw.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_profile_map_new'"
    ).fetchone()
    assert orphan is None
    raw.close()
