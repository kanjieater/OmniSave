"""
Device ownership model tests.
Covers: pairing codes, share codes, device_access visibility, migration backfill.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, auth_header, login_admin, pair_device


def _create_user(client, username, password="pw"):
    admin = login_admin(client)
    client.post("/api/v1/ui/users", json={"username": username, "password": password}, headers=auth_header(admin))


def _login(client, username, password="pw") -> str:
    r = client.post("/api/v1/ui/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["admin_token"]


def _register_device(client, device_id: str) -> None:
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": device_id})


# ── Pairing code flow ─────────────────────────────────────────────────────────

def test_device_config_returns_pairing_code_when_unpaired(client):
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    assert r.status_code == 200
    data = r.json()
    assert "pairing_code" in data
    assert len(data["pairing_code"]) == 6
    assert data["pairing_expires_in"] == 900


def test_device_config_no_code_when_already_paired(client):
    pair_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    assert "pairing_code" not in r.json()


def test_pair_by_code_sets_owner(client, conn):
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    code = r.json()["pairing_code"]

    alice_tok = _login(client, "alice")
    r = client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(alice_tok))
    assert r.status_code == 200, r.text
    assert r.json()["device_id"] == db.normalize_device_id(DEVICE_A)

    device = db.get_device(conn, db.normalize_device_id(DEVICE_A))
    assert device["owner_user_id"] == "alice"


def test_pairing_code_single_use(client):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    code = r.json()["pairing_code"]

    alice_tok = _login(client, "alice")
    r1 = client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(alice_tok))
    assert r1.status_code == 200

    bob_tok = _login(client, "bob")
    r2 = client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(bob_tok))
    assert r2.status_code == 400
    assert "expired" in r2.json()["error"] or "invalid" in r2.json()["error"]


def test_pairing_code_invalid(client):
    admin_tok = login_admin(client)
    r = client.post("/api/v1/ui/devices/pair", json={"code": "XXXXXX"}, headers=auth_header(admin_tok))
    assert r.status_code == 400


def test_pairing_code_expired(client, conn):
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)
    conn.execute(
        "INSERT INTO device_pairing_codes (code, device_id, expires_at, used)"
        " VALUES ('EXPIRE', ?, '2000-01-01T00:00:00Z', 0)",
        (device_id,),
    )
    alice_tok = _login(client, "alice")
    r = client.post("/api/v1/ui/devices/pair", json={"code": "EXPIRE"}, headers=auth_header(alice_tok))
    assert r.status_code == 400


# ── Share code flow ───────────────────────────────────────────────────────────

def test_share_code_grants_access(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    # alice pairs device (becomes owner)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    code = r.json()["pairing_code"]
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(alice_tok))

    # alice generates share code
    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    assert r.status_code == 200
    share_code = r.json()["code"]
    assert len(share_code) == 6
    assert r.json()["expires_in"] == 900

    # bob accepts share code
    bob_tok = _login(client, "bob")
    r = client.post("/api/v1/ui/devices/accept-share", json={"code": share_code}, headers=auth_header(bob_tok))
    assert r.status_code == 200

    # verify access row exists
    access = db.list_device_access(conn, device_id)
    assert any(a["user_id"] == "bob" for a in access)


def test_share_code_single_use(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _create_user(client, "charlie")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    code = r.json()["pairing_code"]
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(alice_tok))
    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    share_code = r.json()["code"]

    bob_tok = _login(client, "bob")
    r1 = client.post("/api/v1/ui/devices/accept-share", json={"code": share_code}, headers=auth_header(bob_tok))
    assert r1.status_code == 200

    charlie_tok = _login(client, "charlie")
    r2 = client.post("/api/v1/ui/devices/accept-share", json={"code": share_code}, headers=auth_header(charlie_tok))
    assert r2.status_code == 400


def test_owner_cannot_accept_own_share_code(client, conn):
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    share_code = r.json()["code"]
    r = client.post("/api/v1/ui/devices/accept-share", json={"code": share_code}, headers=auth_header(alice_tok))
    assert r.status_code == 400


def test_non_owner_cannot_generate_share_code(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    bob_tok = _login(client, "bob")
    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(bob_tok))
    assert r.status_code == 403


def test_pair_by_code_revives_deleted_device(client, conn):
    """pair_by_code must clear deleted_at so a re-paired device appears active again."""
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    # First pairing
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    # Delete the device
    client.delete(f"/api/v1/ui/devices/{device_id}", headers=auth_header(alice_tok))
    row = conn.execute("SELECT deleted_at FROM devices WHERE device_id=?", (device_id,)).fetchone()
    assert row["deleted_at"] is not None

    # Re-register gets a new pairing code
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    assert "pairing_code" in r.json(), "deleted device must be issued a fresh pairing code"
    code = r.json()["pairing_code"]

    # Re-pair via code clears deleted_at
    client.post("/api/v1/ui/devices/pair", json={"code": code}, headers=auth_header(alice_tok))

    row = conn.execute("SELECT deleted_at FROM devices WHERE device_id=?", (device_id,)).fetchone()
    assert row["deleted_at"] is None

    # Device appears active in alice's list
    devices = client.get("/api/v1/ui/devices", headers=auth_header(alice_tok)).json()["devices"]
    entry = next((d for d in devices if d["device_id"] == device_id), None)
    assert entry is not None and entry["is_deleted"] is False


# ── DB helpers direct coverage ────────────────────────────────────────────────

def test_user_has_device_access_owner(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute("INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at, owner_user_id)"
                 " VALUES ('DEV1','','',?,?,'alice')", (now, now))
    assert db.user_has_device_access(conn, "DEV1", "alice") is True
    assert db.user_has_device_access(conn, "DEV1", "bob") is False


def test_user_has_device_access_via_access_row(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute("INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at, owner_user_id)"
                 " VALUES ('DEV1','','',?,?,'alice')", (now, now))
    db.grant_device_access(conn, "DEV1", "bob", "alice")
    assert db.user_has_device_access(conn, "DEV1", "bob") is True


def test_claim_share_code_expired_returns_none(conn):
    conn.execute(
        "INSERT INTO device_share_codes (code, device_id, granted_by, expires_at, used)"
        " VALUES ('STALE1', 'DEV1', 'alice', '2000-01-01T00:00:00Z', 0)"
    )
    assert db.claim_share_code(conn, "STALE1") is None


# ── Error paths in new endpoints ───────────────────────────────────────────────

def _setup_alice_device(client):
    """Helper: alice pairs DEVICE_A and returns (alice_tok, device_id)."""
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))
    return alice_tok, db.normalize_device_id(DEVICE_A)


def test_share_device_not_found_404(client):
    admin_tok = login_admin(client)
    r = client.post("/api/v1/ui/devices/NOSUCHDEVICE/share", headers=auth_header(admin_tok))
    assert r.status_code == 404


def test_list_access_device_not_found_404(client):
    admin_tok = login_admin(client)
    r = client.get("/api/v1/ui/devices/NOSUCHDEVICE/access", headers=auth_header(admin_tok))
    assert r.status_code == 404


def test_list_access_forbidden_for_non_owner(client):
    _create_user(client, "alice")
    _create_user(client, "bob")
    alice_tok, device_id = _setup_alice_device(client)
    bob_tok = _login(client, "bob")
    r = client.get(f"/api/v1/ui/devices/{device_id}/access", headers=auth_header(bob_tok))
    assert r.status_code == 403


def test_revoke_access_device_not_found_404(client):
    admin_tok = login_admin(client)
    r = client.delete("/api/v1/ui/devices/NOSUCHDEVICE/access/bob", headers=auth_header(admin_tok))
    assert r.status_code == 404


def test_revoke_access_forbidden_for_non_owner(client):
    _create_user(client, "alice")
    _create_user(client, "bob")
    alice_tok, device_id = _setup_alice_device(client)
    bob_tok = _login(client, "bob")
    r = client.delete(f"/api/v1/ui/devices/{device_id}/access/bob", headers=auth_header(bob_tok))
    assert r.status_code == 403


def test_delete_device_forbidden_for_non_owner(client):
    _create_user(client, "alice")
    _create_user(client, "bob")
    alice_tok, device_id = _setup_alice_device(client)
    bob_tok = _login(client, "bob")
    r = client.delete(f"/api/v1/ui/devices/{device_id}", headers=auth_header(bob_tok))
    assert r.status_code == 403


def test_accept_share_invalid_code_400(client):
    _create_user(client, "alice")
    alice_tok = _login(client, "alice")
    r = client.post("/api/v1/ui/devices/accept-share", json={"code": "XXXXXX"}, headers=auth_header(alice_tok))
    assert r.status_code == 400


def test_auto_claim_fires_for_single_profile_device(client, conn):
    """Auto-claim fires only when exactly one profile exists — unambiguous mapping."""
    _PROFILE_SOLO = "AAAA000011112222"
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    # Device reports exactly one profile → auto-claim must fire for alice
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": _PROFILE_SOLO, "profile_name": "Alice"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert db.get_profile_owner(conn, device_id, _PROFILE_SOLO) == "alice"


def test_auto_claim_fires_for_multi_profile_device_owner(client, conn):
    """Device owner always gets the first globally-unclaimed profile, even on multi-profile devices."""
    _PROFILE_A = "AAAA000011112222"
    _PROFILE_B = "BBBB000011112222"

    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    # Device reports two profiles — owner (alice) gets first unclaimed (A); B stays unclaimed
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [
            {"profile_id": _PROFILE_A, "profile_name": "Alice"},
            {"profile_id": _PROFILE_B, "profile_name": "Bob"},
        ]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert db.get_profile_owner(conn, device_id, _PROFILE_A) == "alice"
    assert db.get_profile_owner(conn, device_id, _PROFILE_B) is None


def test_accept_share_auto_claims_next_unclaimed_on_multi_profile_device(client, conn):
    """accept-share gives the shared user the next globally-unclaimed profile."""
    _PROFILE_A = "AAAA000011112222"
    _PROFILE_B = "BBBB000011112222"

    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    # Alice (device owner) auto-claims first profile (A)
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [
            {"profile_id": _PROFILE_A, "profile_name": "Alice"},
            {"profile_id": _PROFILE_B, "profile_name": "Bob"},
        ]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert db.get_profile_owner(conn, device_id, _PROFILE_A) == "alice"

    # Bob accepts share → auto-claims next unclaimed profile (B)
    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    bob_tok = _login(client, "bob")
    r = client.post(
        "/api/v1/ui/devices/accept-share",
        json={"code": r.json()["code"]},
        headers=auth_header(bob_tok),
    )
    assert r.status_code == 200
    assert db.get_user_has_claim_on_device(conn, device_id, "bob")
    bob_claim = conn.execute(
        "SELECT profile_id FROM device_profile_map WHERE device_id=? AND user_id='bob'",
        (device_id,),
    ).fetchone()
    assert bob_claim is not None and bob_claim["profile_id"] == _PROFILE_B


def test_accept_share_auto_claims_on_single_profile_device(client, conn):
    """accept-share co-claims the sole profile when all profiles are already claimed.

    Design decision: every user must always land with a default profile (family-trust model).
    Co-claiming grants visibility into that profile's save history.
    """
    _PROFILE_SOLO = "AAAA000011112222"
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    # Register exactly one profile — alice auto-claims it
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [{"profile_id": _PROFILE_SOLO, "profile_name": "Solo"}]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert db.get_profile_owner(conn, device_id, _PROFILE_SOLO) == "alice"

    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    bob_tok = _login(client, "bob")
    r = client.post(
        "/api/v1/ui/devices/accept-share",
        json={"code": r.json()["code"]},
        headers=auth_header(bob_tok),
    )
    assert r.status_code == 200
    # All profiles claimed — bob co-claims the sole profile so user always has a default
    assert db.get_user_has_claim_on_device(conn, device_id, "bob")
    bob_claim = conn.execute(
        "SELECT profile_id FROM device_profile_map WHERE device_id=? AND user_id='bob'",
        (device_id,),
    ).fetchone()
    assert bob_claim is not None and bob_claim["profile_id"] == _PROFILE_SOLO


# ── Device visibility ─────────────────────────────────────────────────────────

def test_device_visible_to_owner(client, conn):
    _create_user(client, "alice")
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    r = client.get("/api/v1/ui/devices", headers=auth_header(alice_tok))
    device_ids = [d["device_id"] for d in r.json()["devices"]]
    assert db.normalize_device_id(DEVICE_A) in device_ids


def test_device_not_visible_to_unrelated_user(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    bob_tok = _login(client, "bob")
    r = client.get("/api/v1/ui/devices", headers=auth_header(bob_tok))
    device_ids = [d["device_id"] for d in r.json()["devices"]]
    assert db.normalize_device_id(DEVICE_A) not in device_ids


def test_shared_device_visible_to_shared_user(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))

    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    bob_tok = _login(client, "bob")
    client.post("/api/v1/ui/devices/accept-share", json={"code": r.json()["code"]}, headers=auth_header(bob_tok))

    r = client.get("/api/v1/ui/devices", headers=auth_header(bob_tok))
    device_ids = [d["device_id"] for d in r.json()["devices"]]
    assert device_id in device_ids


# ── Access management ─────────────────────────────────────────────────────────

def test_revoke_access_removes_visibility(client, conn):
    _create_user(client, "alice")
    _create_user(client, "bob")
    _register_device(client, DEVICE_A)
    device_id = db.normalize_device_id(DEVICE_A)

    r = client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": DEVICE_A})
    alice_tok = _login(client, "alice")
    client.post("/api/v1/ui/devices/pair", json={"code": r.json()["pairing_code"]}, headers=auth_header(alice_tok))
    r = client.post(f"/api/v1/ui/devices/{device_id}/share", headers=auth_header(alice_tok))
    bob_tok = _login(client, "bob")
    client.post("/api/v1/ui/devices/accept-share", json={"code": r.json()["code"]}, headers=auth_header(bob_tok))

    # alice revokes bob
    r = client.delete(f"/api/v1/ui/devices/{device_id}/access/bob", headers=auth_header(alice_tok))
    assert r.status_code == 204

    r = client.get("/api/v1/ui/devices", headers=auth_header(bob_tok))
    device_ids = [d["device_id"] for d in r.json()["devices"]]
    assert device_id not in device_ids


# ── Migration: backfill owner_user_id on devices ──────────────────────────────

def test_migration_adds_owner_user_id_to_devices(tmp_path):
    """Upgrade-path: existing DB with devices + device_auth but no owner_user_id column."""
    import sqlite3
    raw = sqlite3.connect(str(tmp_path / "existing.db"))
    raw.row_factory = sqlite3.Row
    raw.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            hardware_type TEXT NOT NULL DEFAULT '',
            last_seen TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE device_auth (
            device_id TEXT PRIMARY KEY,
            device_token TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen TEXT,
            config_pending INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE sync_transactions (
            transaction_id TEXT PRIMARY KEY,
            title_id TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
            state TEXT NOT NULL,
            snapshot_sequence INTEGER,
            parent_sequence_num INTEGER,
            has_conflict INTEGER NOT NULL DEFAULT 0,
            preservation INTEGER NOT NULL DEFAULT 0,
            target_device_id TEXT,
            sha256 TEXT,
            snapshot_path TEXT,
            total_size_bytes INTEGER,
            checkpoint_ledger TEXT,
            user_key TEXT,
            user_display TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_outbound_per_device_title
            ON sync_transactions(target_device_id, title_id, COALESCE(user_key,''))
            WHERE direction = 'outbound' AND state = 'READY_FOR_RESTORE';
        INSERT INTO devices VALUES ('DEV1', 'My Switch', 'OLED', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        INSERT INTO device_auth VALUES ('DEV1', 'sk_device_xxx', 'alice', '2026-01-01T00:00:00Z', NULL, 0);
    """)
    raw.commit()
    raw.close()

    conn = db.open_db(tmp_path / "existing.db")

    dev_cols = {r[1] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
    assert "owner_user_id" in dev_cols

    device = conn.execute("SELECT owner_user_id FROM devices WHERE device_id='DEV1'").fetchone()
    assert device["owner_user_id"] == "alice", "backfill must set owner from device_auth"

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "device_pairing_codes" in tables
    assert "device_share_codes" in tables
    assert "device_access" in tables

    conn.close()
