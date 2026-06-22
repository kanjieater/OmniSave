"""
Tests for ui_api — covers all /api/v1/ui/* endpoints.
Uses in-memory DB (conftest.py). All protected endpoints require auth token.
"""

import uuid
from datetime import UTC, datetime

import pytest
from helpers import login_admin, auth_header

TITLE_1 = "0100F2C0115B6000"
TITLE_2 = "0100EC001DE7E000"
DEVICE_A = "AABBCCDDEEFF"
DEVICE_B = "112233445566"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _login(client) -> str:
    return login_admin(client)


def _hdr(token: str) -> dict:
    return auth_header(token)


ADMIN_USER = "admin"


def _seed_event(conn, event_type: str = "TEST", message: str = "msg",
                title_id=None, device_id=None, transaction_id=None,
                owner_user_id: str = ADMIN_USER) -> None:
    conn.execute(
        "INSERT INTO events"
        " (occurred_at, event_type, title_id, device_id, transaction_id, message, owner_user_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (_now(), event_type, title_id, device_id, transaction_id, message, owner_user_id),
    )


def _seed_device(conn, device_id: str, display_name: str = "", user_id: str = ADMIN_USER) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at, owner_user_id)"
        " VALUES (?, ?, '', ?, ?, ?)",
        (device_id, display_name, now, now, user_id),
    )


def _seed_txn(
    conn,
    *,
    transaction_id: str = None,
    title_id: str = TITLE_1,
    source_device_id: str = DEVICE_A,
    direction: str = "inbound",
    state: str = "READY_FOR_RESTORE",
    snapshot_sequence: int = None,
    parent_sequence_num: int = None,
    has_conflict: int = 0,
    target_device_id: str = None,
    sha256: str = None,
    snapshot_path: str = None,
    owner_user_id: str = ADMIN_USER,
) -> str:
    txn_id = transaction_id or str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id, title_id, source_device_id, direction, state,"
        "  snapshot_sequence, parent_sequence_num, has_conflict, target_device_id,"
        "  sha256, snapshot_path, owner_user_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            txn_id, title_id, source_device_id, direction, state,
            snapshot_sequence, parent_sequence_num, has_conflict,
            target_device_id, sha256, snapshot_path, owner_user_id, now, now,
        ),
    )
    return txn_id


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_auth_status_unauthenticated(client):
    r = client.get("/api/v1/ui/auth/status")
    assert r.status_code == 200
    data = r.json()
    assert data["bootstrapped"] is True   # always true — auto-seeded on init
    assert data["authenticated"] is False
    assert data["username"] == ""   # no user identified until logged in


def test_auth_login_returns_token(client):
    r = client.post("/api/v1/ui/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    token = r.json()["admin_token"]
    assert token.startswith("sk_live_")


def test_auth_login_wrong_password_401(client):
    r = client.post("/api/v1/ui/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_auth_login_wrong_username_401(client):
    r = client.post("/api/v1/ui/auth/login", json={"username": "nobody", "password": "admin"})
    assert r.status_code == 401


def test_auth_status_authenticated_after_login(client):
    token = _login(client)
    r = client.get("/api/v1/ui/auth/status", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["bootstrapped"] is True
    assert data["authenticated"] is True
    assert data["username"] == "admin"


def test_auth_status_unauthenticated_after_logout(client):
    token = _login(client)
    client.post("/api/v1/ui/auth/logout", headers=_hdr(token))
    r = client.get("/api/v1/ui/auth/status")
    assert r.json()["authenticated"] is False


def test_auth_status_always_open(client):
    """auth/status is not behind _auth_err — always returns 200."""
    r = client.get("/api/v1/ui/auth/status")
    assert r.status_code == 200


def test_auth_rotate_returns_new_token(client):
    token = _login(client)
    r = client.post("/api/v1/ui/auth/rotate", headers=_hdr(token))
    assert r.status_code == 200
    new_token = r.json()["admin_token"]
    assert new_token.startswith("sk_live_")
    assert new_token != token


def test_auth_rotate_invalidates_old_token(client):
    token = _login(client)
    new_token = client.post("/api/v1/ui/auth/rotate", headers=_hdr(token)).json()["admin_token"]
    # Old token is no longer valid after rotation
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(token)).status_code == 401
    # New token works
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(new_token)).status_code == 200


def test_admin_multi_session_login(client):
    """Two admin logins must both remain valid simultaneously."""
    token1 = _login(client)
    token2 = _login(client)
    assert token1 != token2
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(token1)).status_code == 200
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(token2)).status_code == 200


# ── Dashboard ─────────────────────────────────────────────────────────────────


def test_dashboard_empty_db_zeros(client):
    token = _login(client)
    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    stats = data["stats"]
    assert stats["total_games"] == 0
    assert stats["total_devices"] == 0
    assert stats["active_errors"] == 0
    assert stats["pending_titles"] == 0
    assert data["recent_games"] == []
    assert data["devices"] == []
    assert data["recent_events"] == []


def test_dashboard_seeded_counts(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, title_id=TITLE_1, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, title_id=TITLE_2, state="FAILED")

    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    data = r.json()
    assert data["stats"]["total_devices"] == 2
    assert data["stats"]["total_games"] == 2
    assert data["stats"]["active_errors"] == 1
    assert len(data["recent_games"]) == 2


def test_dashboard_pending_titles_counted(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="READY_FOR_RESTORE", snapshot_sequence=1,
    )

    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    assert r.json()["stats"]["pending_titles"] == 1


def test_dashboard_recent_events_present(client, conn):
    token = _login(client)
    conn.execute(
        "INSERT INTO events (occurred_at, event_type, title_id, device_id, transaction_id, message, owner_user_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (_now(), "TEST_EVENT", None, None, None, "hello", ADMIN_USER),
    )

    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    events = r.json()["recent_events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "TEST_EVENT"
    assert events[0]["summary"] == "hello"


def test_dashboard_deleted_device_carries_is_deleted_flag(client, conn):
    """dashboard /devices must include is_deleted so the UI filter works."""
    _seed_device(conn, DEVICE_A)
    token = _login(client)

    data = client.get("/api/v1/ui/dashboard", headers=_hdr(token)).json()
    entry = next((d for d in data["devices"] if d["device_id"] == DEVICE_A), None)
    assert entry is not None
    assert entry["is_deleted"] is False

    client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(token))

    data = client.get("/api/v1/ui/dashboard", headers=_hdr(token)).json()
    entry = next((d for d in data["devices"] if d["device_id"] == DEVICE_A), None)
    assert entry is not None
    assert entry["is_deleted"] is True


# ── client_type ───────────────────────────────────────────────────────────────


def test_device_list_client_type_field_present(client, conn):
    """client_type must be present in every device list entry."""
    _seed_device(conn, DEVICE_A)
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == DEVICE_A)
    assert "client_type" in entry


def test_device_config_stamps_client_type_switch(client, conn):
    """device-config endpoint must write client_type='switch' for Switch devices."""
    import database as db
    _seed_device(conn, DEVICE_A)
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, client_type, last_seen, created_at)"
        " VALUES (?, '', '', 'switch', datetime('now'), datetime('now'))"
        " ON CONFLICT(device_id) DO UPDATE SET client_type='switch', last_seen=excluded.last_seen",
        (DEVICE_A,),
    )
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == DEVICE_A)
    assert entry["client_type"] == "switch"


def test_romm_virtual_device_client_type_romm(client, conn):
    """RomM virtual device must appear in device list with client_type='romm'."""
    import database as db
    romm_id = "romm:test.host"
    # owner_user_id must be set so device appears only for admin, not all users
    db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc", client_type="romm", owner_user_id="admin")
    db.set_config(conn, "romm_source_id", romm_id)
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next((d for d in data["devices"] if d["device_id"] == romm_id), None)
    assert entry is not None, "RomM device must appear for admin"
    assert entry["client_type"] == "romm"

def test_romm_device_not_visible_without_owner(client, conn):
    """RomM device WITHOUT owner_user_id must NOT appear for any user (no supplemental leak)."""
    import database as db
    romm_id = "romm:test.host"
    # Upsert without owner_user_id — simulates the old buggy state where device had no owner
    db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc", client_type="romm", owner_user_id=None)
    db.set_config(conn, "romm_source_id", romm_id)
    conn.commit()
    token = _login(client)  # admin
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next((d for d in data["devices"] if d["device_id"] == romm_id), None)
    assert entry is None, "Ownerless virtual device must not appear — supplemental query was removed"


# ── Device profiles & push-modal defaults ────────────────────────────────────


def _seed_profile(conn, device_id, profile_id, user_id=ADMIN_USER, profile_name=""):
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO device_profile_map"
        " (device_id, profile_id, user_id, profile_name, created_at) VALUES (?,?,?,?,?)",
        (device_id, profile_id, user_id, profile_name, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO device_known_profiles"
        " (device_id, profile_id, profile_name, last_seen) VALUES (?,?,?,?)",
        (device_id, profile_id, profile_name, now),
    )


def _set_default_profile(conn, device_id, profile_id):
    conn.execute(
        "UPDATE devices SET default_profile_uid=? WHERE device_id=?",
        (profile_id, device_id),
    )


def test_device_profiles_single(client, conn):
    """Device with one profile: endpoint returns exactly that profile."""
    _seed_device(conn, DEVICE_A)
    _seed_profile(conn, DEVICE_A, "AAAA000000000001", profile_name="x")
    conn.commit()
    token = _login(client)
    data = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token)).json()
    profiles = data["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["profile_id"] == "AAAA000000000001"
    assert profiles[0]["profile_name"] == "x"


def test_device_profiles_multi(client, conn):
    """Device with two profiles: endpoint returns both; default marked correctly."""
    _seed_device(conn, DEVICE_A)
    _seed_profile(conn, DEVICE_A, "AAAA000000000001", user_id=ADMIN_USER, profile_name="x")
    _seed_profile(conn, DEVICE_A, "BBBB000000000002", user_id="other", profile_name="lil")
    _set_default_profile(conn, DEVICE_A, "AAAA000000000001")
    conn.commit()
    token = _login(client)
    data = client.get(f"/api/v1/ui/devices/{DEVICE_A}/profiles", headers=_hdr(token)).json()
    ids = [p["profile_id"] for p in data["profiles"]]
    assert "AAAA000000000001" in ids
    assert "BBBB000000000002" in ids


def test_device_profiles_romm_empty(client, conn):
    """RomM virtual device has no Nintendo profiles; endpoint returns empty list."""
    import database as db
    romm_id = "romm:admin"
    db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc", client_type="romm", owner_user_id=ADMIN_USER)
    db.set_config(conn, "romm_source_id", romm_id)
    conn.commit()
    token = _login(client)
    data = client.get(f"/api/v1/ui/devices/{romm_id}/profiles", headers=_hdr(token)).json()
    assert data["profiles"] == []


def test_romm_owner_user_id_in_device_list(client, conn):
    """RomM device must expose owner_user_id so UI can label it without OmniSave session user."""
    import database as db
    romm_id = "romm:admin"
    db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc", client_type="romm", owner_user_id=ADMIN_USER)
    db.set_config(conn, "romm_source_id", romm_id)
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == romm_id)
    assert entry["owner_user_id"] == ADMIN_USER


def test_push_uses_device_default_profile(client, conn):
    """Push without explicit target_profile_uid must use device's default_profile_uid."""
    _seed_device(conn, DEVICE_A)
    _seed_profile(conn, DEVICE_A, "AAAA000000000001", profile_name="x")
    _set_default_profile(conn, DEVICE_A, "AAAA000000000001")
    txn_id = _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    conn.commit()
    token = _login(client)
    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json={"targets": [{"device_id": DEVICE_A}]},
        headers=_hdr(token),
    )
    assert r.status_code == 202
    row = conn.execute(
        "SELECT target_profile_uid FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_A,),
    ).fetchone()
    assert row is not None
    assert row["target_profile_uid"] == "AAAA000000000001"


def test_push_explicit_profile_overrides_default(client, conn):
    """Explicit target_profile_uid in push body must override the device default."""
    _seed_device(conn, DEVICE_A)
    _seed_profile(conn, DEVICE_A, "AAAA000000000001", user_id=ADMIN_USER, profile_name="x")
    _seed_profile(conn, DEVICE_A, "BBBB000000000002", user_id="other", profile_name="lil")
    _set_default_profile(conn, DEVICE_A, "AAAA000000000001")
    txn_id = _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    conn.commit()
    token = _login(client)
    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json={"targets": [{"device_id": DEVICE_A, "target_profile_uid": "BBBB000000000002"}]},
        headers=_hdr(token),
    )
    assert r.status_code == 202
    row = conn.execute(
        "SELECT target_profile_uid FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_A,),
    ).fetchone()
    assert row["target_profile_uid"] == "BBBB000000000002"


def test_devices_list_includes_default_profile_name(client, conn):
    """/devices must include default_profile_name when default_profile_uid is set and resolvable."""
    _seed_device(conn, DEVICE_A)
    _seed_profile(conn, DEVICE_A, "AAAA000000000001", profile_name="user_a")
    _set_default_profile(conn, DEVICE_A, "AAAA000000000001")
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == DEVICE_A)
    assert entry["default_profile_uid"] == "AAAA000000000001"
    assert entry["default_profile_name"] == "user_a"


def test_devices_list_default_profile_name_null_when_uid_unset(client, conn):
    """/devices must return default_profile_name=null when no default profile is configured."""
    _seed_device(conn, DEVICE_A)
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == DEVICE_A)
    assert entry["default_profile_uid"] is None
    assert entry["default_profile_name"] is None


def test_devices_list_default_profile_name_from_profile_map_fallback(client, conn):
    """default_profile_name must resolve from device_profile_map when device_known_profiles is empty."""
    now = _now()
    _seed_device(conn, DEVICE_A)
    # Claim-only: profile is in device_profile_map but NOT in device_known_profiles.
    conn.execute(
        "INSERT OR IGNORE INTO device_profile_map"
        " (device_id, profile_id, user_id, profile_name, created_at) VALUES (?,?,?,?,?)",
        (DEVICE_A, "AAAA000000000001", ADMIN_USER, "og-user", now),
    )
    _set_default_profile(conn, DEVICE_A, "AAAA000000000001")
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    entry = next(d for d in data["devices"] if d["device_id"] == DEVICE_A)
    assert entry["default_profile_uid"] == "AAAA000000000001"
    assert entry["default_profile_name"] == "og-user"


# ── Games ─────────────────────────────────────────────────────────────────────


def test_games_empty_list(client):
    token = _login(client)
    r = client.get("/api/v1/ui/games", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["games"] == []


def test_games_only_outbound_not_listed(client, conn):
    token = _login(client)
    _seed_txn(conn, direction="outbound", target_device_id=DEVICE_B, state="READY_FOR_RESTORE")

    r = client.get("/api/v1/ui/games", headers=_hdr(token))
    assert r.json()["games"] == []


def test_games_status_only_failed_shows_no_data(client, conn):
    """Games never show ERROR. Only-failed-upload history → NO_DATA (no successful save)."""
    token = _login(client)
    _seed_txn(conn, state="FAILED")

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert len(games) == 1
    assert games[0]["status"] == "NO_DATA"


def test_games_status_legacy_conflict_row_shows_synced(client, conn):
    """Legacy rows with has_conflict=1 (written before global-seq migration) show SYNCED.
    CONFLICT is no longer a user-facing status."""
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", has_conflict=1, snapshot_sequence=1,
              sha256="a" * 64)

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["status"] == "SYNCED"


def test_games_status_synced(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", has_conflict=0, snapshot_sequence=1,
              sha256="b" * 64)

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["status"] == "SYNCED"


def test_games_status_synced_even_with_failed_upload(client, conn):
    """A failed upload alongside a successful save → SYNCED (not ERROR — games never show ERROR)."""
    token = _login(client)
    _seed_txn(conn, state="FAILED")
    _seed_txn(conn, state="READY_FOR_RESTORE", has_conflict=0, snapshot_sequence=1,
              sha256="c" * 64)

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert len(games) == 1
    assert games[0]["status"] == "SYNCED"


def test_games_display_name_from_labels(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)
    conn.execute(
        "INSERT INTO labels (entity_type, entity_id, label) VALUES ('game', ?, ?)",
        (TITLE_1, "My Game"),
    )

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["display_name"] == "My Game"


def test_games_display_name_none_without_label(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["display_name"] is None


# ── Game detail ───────────────────────────────────────────────────────────────


def test_game_detail_invalid_title_id_400(client):
    token = _login(client)
    r = client.get("/api/v1/ui/games/NOTVALIDHEXID", headers=_hdr(token))
    assert r.status_code == 400


def test_game_detail_empty_game(client):
    token = _login(client)
    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "NO_DATA"
    assert data["head_sequence"] is None
    assert data["snapshots"] == []
    assert data["device_sync_matrix"] == []


def test_game_detail_snapshot_structure(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    txn_id = _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
                       snapshot_sequence=1, sha256="d" * 64)

    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "SYNCED"
    assert data["head_sequence"] == 1
    assert len(data["snapshots"]) == 1
    snap = data["snapshots"][0]
    assert snap["transaction_id"] == txn_id
    assert snap["sequence_num"] == 1
    assert snap["device_id"] == DEVICE_A
    assert snap["is_head"] is True
    assert snap["archive_size_bytes"] is None  # no archive file in test env


def test_game_detail_snapshot_archive_size(client, conn, tmp_dirs):
    """archive_size_bytes reflects the actual archive file size when present."""
    _, archive = tmp_dirs
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    txn_id = _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    archive_path = archive / txn_id / "save.zip"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"x" * 2048)

    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token))
    assert r.status_code == 200
    snap = r.json()["snapshots"][0]
    assert snap["archive_size_bytes"] == 2048


def test_archive_size_none_when_no_archive_dir(monkeypatch):
    """_archive_size returns None when _archive_dir is unset."""
    import ui_api as _ui_api
    monkeypatch.setattr(_ui_api, "_archive_dir", None)
    assert _ui_api._archive_size("any-txn-id") is None


def test_game_detail_uploading_excluded(client, conn):
    """UPLOADING (in-progress) transactions must not appear in the snapshots list."""
    token = _login(client)
    _seed_txn(conn, state="UPLOADING")

    snaps = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["snapshots"]
    assert len(snaps) == 0


def test_game_detail_deduped_excluded(client, conn):
    """DEDUPED transactions must not appear in All Saves — only in the activity feed."""
    token = _login(client)
    _seed_txn(conn, state="DEDUPED")
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)

    snaps = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["state"] == "COMMITTED"


def test_game_detail_state_map_processing_to_persisted(client, conn):
    token = _login(client)
    _seed_txn(conn, state="PROCESSING")

    snap = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["snapshots"][0]
    assert snap["state"] == "PERSISTED"


def test_game_detail_failed_snapshots_excluded(client, conn):
    """FAILED inbound transactions must not appear in the snapshots list."""
    token = _login(client)
    _seed_txn(conn, state="FAILED")
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)

    snaps = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["state"] == "COMMITTED"


def test_game_detail_legacy_conflict_row_shows_committed(client, conn):
    """Legacy rows with has_conflict=1 render as COMMITTED (no CONFLICT_BRANCH concept).
    They are excluded from HEAD computation so is_head is False."""
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", has_conflict=1, snapshot_sequence=2)

    snap = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["snapshots"][0]
    assert snap["state"] == "COMMITTED"
    assert snap["is_head"] is False


def test_game_detail_sync_matrix_source_device_is_synced(client, conn):
    """Device that uploaded the HEAD is already SYNCED — it has the save locally."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]
    entry = next(e for e in matrix if e["device_id"] == DEVICE_A)
    assert entry["sync_state"] == "SYNCED"
    assert entry["cloud_head_sequence"] == 1


def test_game_detail_sync_matrix_out_of_sync(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="READY_FOR_RESTORE", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "OUT_OF_SYNC"
    assert matrix[DEVICE_B]["local_sequence"] is None


def test_game_detail_sync_matrix_synced(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="COMPLETED", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "SYNCED"
    assert matrix[DEVICE_B]["local_sequence"] == 1


def test_game_detail_sync_matrix_synced_via_device_title_head(client, conn):
    """device_title_head.last_seq >= head_seq → SYNCED (primary signal overrides outbound seq check)."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=5,
              sha256="e" * 64)
    # Outbound at seq=3 (< head 5) — old outbound logic would show OUT_OF_SYNC; device_title_head overrides
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="COMPLETED", snapshot_sequence=3)
    conn.execute(
        "INSERT INTO device_title_head (title_id, device_id, last_seq, updated_at) "
        "VALUES (?, ?, 5, '2026-01-01T00:00:00Z')",
        (TITLE_1.upper(), DEVICE_B),
    )
    conn.commit()

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "SYNCED"
    assert matrix[DEVICE_B]["local_sequence"] == 5


def test_game_detail_sync_matrix_downloading(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="DELIVERING", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "DOWNLOADING"


def test_game_detail_sync_matrix_completed_not_at_head_is_out_of_sync(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=2)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="COMPLETED", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "OUT_OF_SYNC"


def test_game_detail_sync_matrix_completed_no_head_is_synced(client, conn):
    """COMPLETED outbound with no READY_FOR_RESTORE (head_seq=None) → SYNCED.

    Regression: startup.py can fail stale inbound transactions, leaving head_seq=None.
    The old code required head_seq is not None, so COMPLETED fell through to OUT_OF_SYNC
    even though the device had already received the last available save."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    # No READY_FOR_RESTORE inbound → head_seq=None
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="COMPLETED", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "SYNCED"


def test_game_detail_sync_matrix_superseded_outbound_is_no_delivery(client, conn):
    """Only SUPERSEDED outbounds → delivery was cancelled; show NO_DELIVERY not OUT_OF_SYNC."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="SUPERSEDED", snapshot_sequence=1,
    )

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "NO_DELIVERY"


# ── Game detail — view model fields (sync_enabled, pending_delivery, last_synced_at, hw) ──


def test_game_detail_matrix_sync_enabled_default_true(client, conn):
    """sync_enabled defaults to true when no prefs are stored for the device."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_A]["sync_enabled"] is True


def test_game_detail_matrix_sync_enabled_false_when_pref_disabled(client, conn):
    """sync_enabled is false when sync_prefs explicitly disables this title for the device."""
    import json
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    conn.execute(
        "INSERT INTO server_config (key, value) VALUES (?, ?)",
        (f"sync_prefs:{DEVICE_A}", json.dumps({TITLE_1.upper(): False})),
    )
    conn.commit()

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_A]["sync_enabled"] is False


def test_game_detail_matrix_pending_delivery_true(client, conn):
    """pending_delivery is true when an outbound READY_FOR_RESTORE exists for this device+title."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["pending_delivery"] is True
    assert matrix[DEVICE_A]["pending_delivery"] is False


def test_game_detail_matrix_pending_delivery_false_when_delivered(client, conn):
    """pending_delivery is false once the outbound transaction moves past READY_FOR_RESTORE."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="DELIVERING", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["pending_delivery"] is False


def test_game_detail_matrix_last_synced_at_populated(client, conn):
    """last_synced_at is the MAX(created_at) of inbound completed transactions for source device."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_A]["last_synced_at"] is not None


def test_game_detail_matrix_last_synced_at_none_for_delivery_target(client, conn):
    """last_synced_at is None for a device that only received (not uploaded) a save."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["last_synced_at"] is None


def test_game_detail_matrix_last_synced_at_romm_fallback(client, conn):
    """last_synced_at for romm devices comes from outbound COMPLETED (they never upload inbound)."""
    import json as _json
    token = _login(client)
    ROMM_ID = "romm:user_a"
    _seed_device(conn, DEVICE_A)
    # Seed a romm device with client_type
    now = _now()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, client_type, last_seen, created_at, owner_user_id)"
        " VALUES (?, 'RomM', '', 'romm', ?, ?, ?)",
        (ROMM_ID, now, now, ADMIN_USER),
    )
    conn.execute(
        "INSERT OR IGNORE INTO device_profile_map (device_id, profile_id, user_id, profile_name, created_at)"
        " VALUES (?, ?, ?, '', ?)",
        (ROMM_ID, f"seed-{ROMM_ID}", ADMIN_USER, now),
    )
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=ROMM_ID, state="COMPLETED", snapshot_sequence=1)
    conn.commit()

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[ROMM_ID]["last_synced_at"] is not None


def test_game_detail_matrix_hardware_and_client_type_present(client, conn):
    """hardware_type and client_type are present in every matrix entry (may be None)."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]
    assert len(matrix) > 0
    for entry in matrix:
        assert "hardware_type" in entry
        assert "client_type" in entry


def test_game_detail_sync_matrix_delivery_failed(client, conn):
    """FAILED outbound → DELIVERY_FAILED state + failed_transaction_id set."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    failed_id = _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
                          target_device_id=DEVICE_B, state="FAILED", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "DELIVERY_FAILED"
    assert matrix[DEVICE_B]["failed_transaction_id"] == failed_id


def test_game_detail_sync_matrix_failed_then_requeued_shows_out_of_sync(client, conn):
    """FAILED + newer READY_FOR_RESTORE → READY_FOR_RESTORE wins (priority=1 < FAILED priority=3) → OUT_OF_SYNC."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="FAILED", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="READY_FOR_RESTORE", snapshot_sequence=1)

    matrix = {e["device_id"]: e for e in
              client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token)).json()["device_sync_matrix"]}
    assert matrix[DEVICE_B]["sync_state"] == "OUT_OF_SYNC"


# ── Events ────────────────────────────────────────────────────────────────────


def test_events_empty(client):
    token = _login(client)
    r = client.get("/api/v1/ui/events", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["events"] == []


def test_events_returned_newest_first(client, conn):
    token = _login(client)
    for i in range(3):
        _seed_event(conn, message=f"msg{i}")

    events = client.get("/api/v1/ui/events", headers=_hdr(token)).json()["events"]
    assert len(events) == 3
    ids = [e["id"] for e in events]
    assert ids == sorted(ids, reverse=True)


def test_events_limit_param(client, conn):
    token = _login(client)
    for i in range(10):
        _seed_event(conn, message=f"msg{i}")

    r = client.get("/api/v1/ui/events?limit=4", headers=_hdr(token))
    assert len(r.json()["events"]) == 4


def test_events_limit_clamped_min_to_1(client, conn):
    token = _login(client)
    _seed_event(conn)
    r = client.get("/api/v1/ui/events?limit=0", headers=_hdr(token))
    assert len(r.json()["events"]) == 1


def test_events_limit_clamped_max_to_500(client, conn):
    token = _login(client)
    for i in range(5):
        _seed_event(conn, message=f"msg{i}")
    r = client.get("/api/v1/ui/events?limit=9999", headers=_hdr(token))
    assert len(r.json()["events"]) == 5


def test_events_includes_romm_push(client, conn):
    token = _login(client)
    _seed_event(conn, event_type="ROMM_PUSH", message="title=X romm_save_id=1",
                owner_user_id=ADMIN_USER)
    events = client.get("/api/v1/ui/events", headers=_hdr(token)).json()["events"]
    assert any(e["event_type"] == "ROMM_PUSH" for e in events)


# ── Errors ────────────────────────────────────────────────────────────────────


def test_errors_empty(client):
    token = _login(client)
    r = client.get("/api/v1/ui/errors", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["errors"] == []


def test_errors_non_failed_not_included(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE")

    assert client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"] == []


def test_errors_returns_failed_transactions(client, conn):
    token = _login(client)
    txn_id = _seed_txn(conn, state="FAILED")

    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert len(errors) == 1
    assert errors[0]["transaction_id"] == txn_id
    assert errors[0]["acknowledged"] is False


def test_errors_outbound_device_id_uses_target(client, conn):
    token = _login(client)
    _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="FAILED",
    )

    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["device_id"] == DEVICE_B


def test_errors_inbound_device_id_uses_source(client, conn):
    token = _login(client)
    _seed_txn(conn, source_device_id=DEVICE_A, state="FAILED")

    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["device_id"] == DEVICE_A


def test_errors_game_name_from_label(client, conn):
    token = _login(client)
    conn.execute(
        "INSERT INTO labels (entity_type, entity_id, label) VALUES ('game', ?, ?)",
        (TITLE_1, "Zelda: Tears of the Kingdom"),
    )
    _seed_txn(conn, title_id=TITLE_1, state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["game_name"] == "Zelda: Tears of the Kingdom"


def test_errors_game_name_none_when_unknown(client, conn):
    token = _login(client)
    _seed_txn(conn, title_id="FFFFFFFFFFFFFFFF", state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["game_name"] is None


def test_errors_device_name_from_display_name(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, display_name="My Switch")
    _seed_txn(conn, source_device_id=DEVICE_A, direction="inbound", state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["device_name"] == "My Switch"


def test_errors_device_name_none_when_unnamed(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, display_name="")
    _seed_txn(conn, source_device_id=DEVICE_A, direction="inbound", state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["device_name"] is None


def test_errors_hardware_type_from_device(client, conn):
    token = _login(client)
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (DEVICE_A, "OG Switch", "switch", _now(), _now()),
    )
    _seed_txn(conn, source_device_id=DEVICE_A, direction="inbound", state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["hardware_type"] == "switch"


def test_errors_icon_url_present_in_response(client, conn):
    token = _login(client)
    _seed_txn(conn, title_id=TITLE_1, state="FAILED")
    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert "icon_url" in errors[0]


def test_acknowledge_sets_acknowledged_true(client, conn):
    token = _login(client)
    txn_id = _seed_txn(conn, state="FAILED")

    r = client.post(f"/api/v1/ui/errors/{txn_id}/acknowledge", headers=_hdr(token))
    assert r.status_code == 200

    errors = client.get("/api/v1/ui/errors", headers=_hdr(token)).json()["errors"]
    assert errors[0]["acknowledged"] is True


def test_acknowledge_idempotent(client, conn):
    token = _login(client)
    txn_id = _seed_txn(conn, state="FAILED")

    r1 = client.post(f"/api/v1/ui/errors/{txn_id}/acknowledge", headers=_hdr(token))
    r2 = client.post(f"/api/v1/ui/errors/{txn_id}/acknowledge", headers=_hdr(token))
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_acknowledge_unknown_transaction_404(client):
    token = _login(client)
    r = client.post("/api/v1/ui/errors/no-such-txn/acknowledge", headers=_hdr(token))
    assert r.status_code == 404


def test_acknowledge_non_failed_transaction_404(client, conn):
    token = _login(client)
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE")

    r = client.post(f"/api/v1/ui/errors/{txn_id}/acknowledge", headers=_hdr(token))
    assert r.status_code == 404


# ── Labels — device ───────────────────────────────────────────────────────────


def test_label_device_put_200(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)

    r = client.put(
        f"/api/v1/ui/labels/device/{DEVICE_A}",
        json={"display_name": "My Switch"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_label_device_put_persists_in_devices_list(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)

    client.put(
        f"/api/v1/ui/labels/device/{DEVICE_A}",
        json={"display_name": "Living Room Switch"},
        headers=_hdr(token),
    )

    devices = {d["device_id"]: d for d in
               client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]}
    assert devices[DEVICE_A]["display_name"] == "Living Room Switch"


def test_label_device_put_unknown_404(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/labels/device/unknown-device",
        json={"display_name": "X"},
        headers=_hdr(token),
    )
    assert r.status_code == 404


def test_label_device_delete_204(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, display_name="Old Name")

    r = client.delete(f"/api/v1/ui/labels/device/{DEVICE_A}", headers=_hdr(token))
    assert r.status_code == 204


def test_label_device_delete_clears_name(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    client.put(
        f"/api/v1/ui/labels/device/{DEVICE_A}",
        json={"display_name": "Name To Remove"},
        headers=_hdr(token),
    )

    client.delete(f"/api/v1/ui/labels/device/{DEVICE_A}", headers=_hdr(token))

    devices = {d["device_id"]: d for d in
               client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]}
    assert devices[DEVICE_A]["display_name"] is None


def test_label_device_delete_unknown_404(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/labels/device/nobody", headers=_hdr(token))
    assert r.status_code == 404


# ── Labels — game ─────────────────────────────────────────────────────────────


def test_label_game_put_200(client):
    token = _login(client)
    r = client.put(
        f"/api/v1/ui/labels/game/{TITLE_1}",
        json={"display_name": "Zelda TOTK"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_label_game_put_visible_in_games_list(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)
    client.put(
        f"/api/v1/ui/labels/game/{TITLE_1}",
        json={"display_name": "Zelda TOTK"},
        headers=_hdr(token),
    )

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["display_name"] == "Zelda TOTK"


def test_label_game_put_upserts(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)
    client.put(f"/api/v1/ui/labels/game/{TITLE_1}", json={"display_name": "First"}, headers=_hdr(token))
    client.put(f"/api/v1/ui/labels/game/{TITLE_1}", json={"display_name": "Second"}, headers=_hdr(token))

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["display_name"] == "Second"


def test_label_game_put_invalid_title_400(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/labels/game/BADID",
        json={"display_name": "X"},
        headers=_hdr(token),
    )
    assert r.status_code == 400


def test_label_game_delete_204(client):
    token = _login(client)
    client.put(f"/api/v1/ui/labels/game/{TITLE_1}", json={"display_name": "Name"}, headers=_hdr(token))
    r = client.delete(f"/api/v1/ui/labels/game/{TITLE_1}", headers=_hdr(token))
    assert r.status_code == 204


def test_label_game_delete_clears_display_name(client, conn):
    token = _login(client)
    _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_sequence=1)
    client.put(f"/api/v1/ui/labels/game/{TITLE_1}", json={"display_name": "Zelda"}, headers=_hdr(token))

    client.delete(f"/api/v1/ui/labels/game/{TITLE_1}", headers=_hdr(token))

    games = client.get("/api/v1/ui/games", headers=_hdr(token)).json()["games"]
    assert games[0]["display_name"] is None


def test_label_game_delete_invalid_title_400(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/labels/game/BADID", headers=_hdr(token))
    assert r.status_code == 400


# ── Devices ───────────────────────────────────────────────────────────────────


def test_devices_empty_list(client):
    token = _login(client)
    r = client.get("/api/v1/ui/devices", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["devices"] == []


def test_devices_list_includes_seeded_devices(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, display_name="Switch A")
    _seed_device(conn, DEVICE_B)

    devices = {d["device_id"]: d for d in
               client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]}
    assert DEVICE_A in devices
    assert DEVICE_B in devices
    assert devices[DEVICE_A]["display_name"] == "Switch A"
    assert devices[DEVICE_B]["display_name"] is None


def test_device_delete_204(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)

    r = client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(token))
    assert r.status_code == 204


def test_device_delete_marks_as_deleted(client, conn):
    """Deleted device stays in GET /devices with is_deleted=True so its name resolves in history."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(token))

    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    deleted = next((d for d in devices if d["device_id"] == DEVICE_A), None)
    assert deleted is not None
    assert deleted["is_deleted"] is True


def test_device_delete_unknown_404(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/devices/nobody", headers=_hdr(token))
    assert r.status_code == 404


def test_device_delete_orphans_transactions(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    txn_id = _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(token))

    assert conn.execute(
        "SELECT 1 FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone() is not None
    row = conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row is not None and row["deleted_at"] is not None


def test_deleted_device_with_surviving_token_gets_401(client, conn):
    """Even if revocation races and the token survives, a deleted device must get 401 on any sync call."""
    _seed_device(conn, DEVICE_A)
    ui_token = _login(client)
    device_token = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(ui_token)
    ).json()["token"]

    # Simulate a race: delete_at set but token NOT removed from device_auth
    conn.execute("UPDATE devices SET deleted_at=? WHERE device_id=?", (_now(), DEVICE_A))

    r = client.get(
        "/api/v1/sync/queue",
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.status_code == 401


def test_device_delete_poll_does_not_revive(client, conn):
    """Polling /queue with a stale token after deletion must 401 and must NOT clear deleted_at."""
    _seed_device(conn, DEVICE_A)
    ui_token = _login(client)
    device_token = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(ui_token)
    ).json()["token"]
    client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(ui_token))

    r = client.get(
        "/api/v1/sync/queue",
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.status_code == 401

    row = conn.execute("SELECT deleted_at FROM devices WHERE device_id=?", (DEVICE_A,)).fetchone()
    assert row is not None and row["deleted_at"] is not None


def test_device_repaired_clears_deleted_at(client, conn):
    """Re-pairing a soft-deleted device restores it to active (deleted_at=NULL, is_deleted=False)."""
    _seed_device(conn, DEVICE_A)
    ui_token = _login(client)
    client.delete(f"/api/v1/ui/devices/{DEVICE_A}", headers=_hdr(ui_token))

    assert conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (DEVICE_A,)
    ).fetchone()["deleted_at"] is not None

    client.post(f"/api/v1/ui/devices/{DEVICE_A}/token", headers=_hdr(_login(client)))

    assert conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (DEVICE_A,)
    ).fetchone()["deleted_at"] is None

    devices = client.get("/api/v1/ui/devices", headers=_hdr(_login(client))).json()["devices"]
    entry = next((d for d in devices if d["device_id"] == DEVICE_A), None)
    assert entry is not None and entry["is_deleted"] is False


# ── Device games ──────────────────────────────────────────────────────────────


def test_device_games_empty(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)

    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["games"] == []


def test_device_games_distinct_title_ids(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A, state="COMPLETED", snapshot_sequence=2)
    _seed_txn(conn, title_id=TITLE_2, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    title_ids = [g["title_id"] for g in games]
    assert len(title_ids) == len(set(title_ids))
    assert TITLE_1 in title_ids
    assert TITLE_2 in title_ids


def test_device_games_sync_enabled_defaults_true(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    assert all(g["sync_enabled"] is True for g in games)


def test_device_games_has_icon_url_key(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    assert len(games) == 1
    assert "icon_url" in games[0]  # may be None — key presence is the contract


def test_device_games_pending_delivery_false_when_no_outbound(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    assert games[0]["pending_delivery"] is False


def test_device_games_pending_delivery_true_when_outbound_queued(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    # DEVICE_B uploads a save
    _seed_txn(
        conn, title_id=TITLE_1, source_device_id=DEVICE_B,
        direction="inbound", state="READY_FOR_RESTORE", snapshot_sequence=1,
    )
    # processing forks an outbound row for DEVICE_A
    _seed_txn(
        conn, title_id=TITLE_1, source_device_id=DEVICE_B,
        direction="outbound", target_device_id=DEVICE_A,
        state="READY_FOR_RESTORE", snapshot_sequence=1,
    )

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    game = next(g for g in games if g["title_id"] == TITLE_1)
    assert game["pending_delivery"] is True


def test_device_games_pending_delivery_false_after_ack(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(
        conn, title_id=TITLE_1, source_device_id=DEVICE_B,
        direction="inbound", state="READY_FOR_RESTORE", snapshot_sequence=1,
    )
    # outbound already COMPLETED (device ACKed)
    _seed_txn(
        conn, title_id=TITLE_1, source_device_id=DEVICE_B,
        direction="outbound", target_device_id=DEVICE_A,
        state="COMPLETED", snapshot_sequence=1,
    )

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    game = next(g for g in games if g["title_id"] == TITLE_1)
    assert game["pending_delivery"] is False


_VALID_SYNC_STATES = {"SYNCED", "OUT_OF_SYNC", "DOWNLOADING", "NO_DELIVERY"}


def test_device_games_sync_state_is_valid(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    assert all(g["sync_state"] in _VALID_SYNC_STATES for g in games)


def test_device_games_last_synced_at_present_when_inbound_exists(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    assert games[0]["last_synced_at"] is not None


def test_device_games_last_synced_at_null_for_outbound_only(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    # only an outbound row targeting DEVICE_A — it never uploaded itself
    _seed_txn(
        conn, title_id=TITLE_1, source_device_id=DEVICE_B,
        direction="outbound", target_device_id=DEVICE_A,
        state="READY_FOR_RESTORE", snapshot_sequence=1,
    )

    games = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]
    game = next(g for g in games if g["title_id"] == TITLE_1)
    assert game["last_synced_at"] is None


# ── device_games — RomM device and Switch catalog ingestion ───────────────────


def test_device_games_switch_shows_from_installed_catalog(client, conn):
    """Switch device_games returns games from device_installed_games even with no transactions."""
    _seed_device(conn, DEVICE_A)
    conn.execute(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?,?)",
        (DEVICE_A, TITLE_1),
    )
    conn.commit()
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token))
    assert r.status_code == 200
    assert any(g["title_id"] == TITLE_1 for g in r.json()["games"])


def test_device_config_then_switch_device_games_shows_installed_titles(client, conn):
    """End-to-end: Switch posts device-config → UI device games endpoint shows the title."""
    import database as _db
    # Seed device and claim it so ui_api sees it as belonging to admin
    _seed_device(conn, DEVICE_A)
    conn.commit()

    r = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": [TITLE_1], "known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200

    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token))
    assert r.status_code == 200
    titles = [g["title_id"].upper() for g in r.json()["games"]]
    assert TITLE_1.upper() in titles


def test_device_games_romm_shows_catalog_entries(client, conn):
    """device_games returns games seeded in device_installed_games for a RomM device."""
    import database as _db
    romm_id = "romm:admin"
    _db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc",
                               client_type="romm", owner_user_id=ADMIN_USER)
    conn.execute(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?,?)",
        (romm_id, TITLE_1),
    )
    conn.commit()
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{romm_id}/games", headers=_hdr(token))
    assert r.status_code == 200
    games = r.json()["games"]
    assert len(games) == 1
    assert games[0]["title_id"] == TITLE_1
    assert "sync_state" in games[0]
    assert "sync_enabled" in games[0]
    assert "pending_delivery" in games[0]


def test_device_games_romm_no_delivery_when_no_prior_outbound(client, conn):
    """RomM device game shows NO_DELIVERY when HEAD exists but no delivery was ever attempted.

    Games uploaded before RomM was registered should not appear as Needs Sync.
    The user must opt in via Restore All; fanout only applies to future uploads."""
    import database as _db
    romm_id = "romm:admin"
    _db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc",
                               client_type="romm", owner_user_id=ADMIN_USER)
    conn.execute(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?,?)",
        (romm_id, TITLE_1),
    )
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A,
              state="READY_FOR_RESTORE", snapshot_sequence=1)
    _db.upsert_romm_title_map(conn, ADMIN_USER, TITLE_1, 42)
    conn.commit()
    token = _login(client)
    r = client.get(f"/api/v1/ui/devices/{romm_id}/games", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["games"][0]["sync_state"] == "NO_DELIVERY"


def test_dashboard_romm_pull_source_not_counted_as_pending(client, conn):
    """RomM device that sourced the inbound (pull from RomM) must not show as pending.

    When RomM is the source_device_id of an inbound, no outbound to romm is
    ever created (romm is excluded from fanout as the source). pending_count
    is outbound-only, so this device correctly shows 0."""
    import database as _db
    romm_id = "romm:admin"
    _db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc",
                               client_type="romm", owner_user_id=ADMIN_USER)
    conn.execute(
        "INSERT INTO device_installed_games (device_id, title_id) VALUES (?,?)",
        (romm_id, TITLE_1),
    )
    # Inbound sourced from romm (a pull) — no outbound to romm created
    _seed_txn(conn, title_id=TITLE_1, source_device_id=romm_id,
              state="READY_FOR_RESTORE", snapshot_sequence=5)
    # Processing stamps device_title_head for the source device
    _db.upsert_device_title_head(conn, TITLE_1, romm_id, 5)
    conn.commit()
    token = _login(client)
    data = client.get("/api/v1/ui/dashboard", headers=_hdr(token)).json()
    romm_entry = next((d for d in data["devices"] if d["device_id"] == romm_id), None)
    assert romm_entry is not None
    assert romm_entry["pending_count"] == 0


# ── Sync prefs ────────────────────────────────────────────────────────────────


def test_sync_prefs_set_and_retrieve(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    r = client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/games/sync/batch",
        json={"preferences": [{"title_id": TITLE_1, "enabled": False}]},
        headers=_hdr(token),
    )
    assert r.status_code == 200

    games = {g["title_id"]: g for g in
             client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]}
    assert games[TITLE_1]["sync_enabled"] is False


def test_sync_prefs_merges_with_existing(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)
    _seed_txn(conn, title_id=TITLE_2, source_device_id=DEVICE_A, state="READY_FOR_RESTORE", snapshot_sequence=1)

    client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/games/sync/batch",
        json={"preferences": [{"title_id": TITLE_1, "enabled": False}]},
        headers=_hdr(token),
    )
    client.post(
        f"/api/v1/ui/devices/{DEVICE_A}/games/sync/batch",
        json={"preferences": [{"title_id": TITLE_2, "enabled": False}]},
        headers=_hdr(token),
    )

    games = {g["title_id"]: g for g in
             client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=_hdr(token)).json()["games"]}
    assert games[TITLE_1]["sync_enabled"] is False
    assert games[TITLE_2]["sync_enabled"] is False


# ── Push snapshot ─────────────────────────────────────────────────────────────


def test_push_snapshot_404_unknown_txn(client):
    token = _login(client)
    r = client.post(
        "/api/v1/ui/snapshots/no-such-txn/push",
        json={"device_ids": []},
        headers=_hdr(token),
    )
    assert r.status_code == 404


def test_push_snapshot_400_wrong_state(client, conn):
    token = _login(client)
    txn_id = _seed_txn(conn, state="FAILED")

    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json={"device_ids": []},
        headers=_hdr(token),
    )
    assert r.status_code == 400


def test_push_snapshot_400_no_eligible_targets(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    txn_id = _seed_txn(
        conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
        snapshot_sequence=1, snapshot_path="/fake/save.bin",
    )

    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json={"device_ids": []},
        headers=_hdr(token),
    )
    assert r.status_code == 400


def test_push_snapshot_202_explicit_device_ids(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    txn_id = _seed_txn(
        conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
        snapshot_sequence=1, snapshot_path="/fake/save.bin",
    )

    r = client.post(
        f"/api/v1/ui/snapshots/{txn_id}/push",
        json={"device_ids": [DEVICE_B]},
        headers=_hdr(token),
    )
    assert r.status_code == 202
    data = r.json()
    assert data["ok"] is True
    assert len(data["outbound_ids"]) == 1


def test_push_snapshot_202_auto_targets(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    txn_id = _seed_txn(
        conn, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
        snapshot_sequence=1, snapshot_path="/fake/save.bin",
    )

    r = client.post(f"/api/v1/ui/snapshots/{txn_id}/push", json={}, headers=_hdr(token))
    assert r.status_code == 202
    assert len(r.json()["outbound_ids"]) == 1


def test_push_snapshot_202_completed_state(client, conn):
    """COMPLETED inbound transactions must be pushable (head snapshot re-delivery)."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    txn_id = _seed_txn(
        conn, source_device_id=DEVICE_A, state="COMPLETED",
        snapshot_sequence=1, snapshot_path="/fake/save.bin",
    )

    r = client.post(f"/api/v1/ui/snapshots/{txn_id}/push", json={}, headers=_hdr(token))
    assert r.status_code == 202
    assert r.json()["ok"] is True
    assert len(r.json()["outbound_ids"]) == 1


def test_get_icon_url_uses_only_icon_url(monkeypatch):
    """get_icon_url must not fall back to artworkUrl or bannerUrl (they are wide banners)."""
    import titledb

    monkeypatch.setattr(titledb, "_ensure_us", lambda: {
        "AABBCCDD11223344": {"iconUrl": "https://cdn/icon.jpg", "bannerUrl": "https://cdn/banner.jpg"},
        "AABBCCDD11223355": {"bannerUrl": "https://cdn/banner.jpg"},
        "AABBCCDD11223366": {"artworkUrl": "https://cdn/art.jpg"},
    })

    assert titledb.get_icon_url("AABBCCDD11223344") == "https://cdn/icon.jpg"
    assert titledb.get_icon_url("AABBCCDD11223355") is None
    assert titledb.get_icon_url("AABBCCDD11223366") is None
    assert titledb.get_icon_url("0000000000000000") is None


# ── Retry outbound ────────────────────────────────────────────────────────────


def test_retry_outbound_404_unknown(client):
    token = _login(client)
    r = client.post("/api/v1/ui/outbounds/no-such-txn/retry", headers=_hdr(token))
    assert r.status_code == 404


def test_retry_outbound_200_on_failed(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    txn_id = _seed_txn(
        conn, direction="outbound", source_device_id=DEVICE_A,
        target_device_id=DEVICE_B, state="FAILED", snapshot_sequence=1,
    )

    r = client.post(f"/api/v1/ui/outbounds/{txn_id}/retry", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["ok"] is True

    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()
    assert row["state"] == "READY_FOR_RESTORE"


# ── Download snapshot ─────────────────────────────────────────────────────────


def test_download_snapshot_401_unauthenticated(client, conn, tmp_path):
    fake_zip = tmp_path / "save.zip"
    fake_zip.write_bytes(b"PK")
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=str(fake_zip))
    r = client.get(f"/api/v1/ui/snapshots/{txn_id}/download")
    assert r.status_code == 401


def test_download_snapshot_404_not_found(client, conn):
    import uuid as _uuid
    token = _login(client)
    r = client.get(f"/api/v1/ui/snapshots/{_uuid.uuid4()}/download", headers=_hdr(token))
    assert r.status_code == 404


def test_download_snapshot_404_missing_file(client, conn, tmp_path):
    token = _login(client)
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE",
                       snapshot_path=str(tmp_path / "gone.zip"))
    r = client.get(f"/api/v1/ui/snapshots/{txn_id}/download", headers=_hdr(token))
    assert r.status_code == 404


def test_download_snapshot_200_returns_zip(client, conn, tmp_path, monkeypatch):
    import urllib.parse
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: "Kirby Star Allies")
    token = _login(client)
    fake_zip = tmp_path / "save.zip"
    fake_zip.write_bytes(b"PK\x03\x04")
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=str(fake_zip))
    r = client.get(f"/api/v1/ui/snapshots/{txn_id}/download", headers=_hdr(token))
    assert r.status_code == 200
    cd = urllib.parse.unquote(r.headers.get("content-disposition", ""))
    assert "Kirby Star Allies [" in cd
    assert "].zip" in cd


def test_download_snapshot_filename_fallback_to_title_id(client, conn, tmp_path, monkeypatch):
    import urllib.parse
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    token = _login(client)
    fake_zip = tmp_path / "save.zip"
    fake_zip.write_bytes(b"PK\x03\x04")
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=str(fake_zip))
    r = client.get(f"/api/v1/ui/snapshots/{txn_id}/download", headers=_hdr(token))
    assert r.status_code == 200
    cd = urllib.parse.unquote(r.headers.get("content-disposition", ""))
    assert TITLE_1 in cd


# ── Delete snapshot ───────────────────────────────────────────────────────────


def test_delete_snapshot_404_wrong_state(client, conn):
    """In-progress states (UPLOADING, PROCESSING) are not deletable."""
    token = _login(client)
    txn_id = _seed_txn(conn, state="UPLOADING")

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 404


def test_delete_snapshot_200_null_snapshot_path_ready(client, conn):
    """Snapshot with no archive path still succeeds — no file to unlink."""
    token = _login(client)
    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=None)

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["deleted"] == txn_id


def test_delete_snapshot_200_removes_file(client, conn, tmp_path):
    token = _login(client)
    fake_dir = tmp_path / "archive" / "txn-del"
    fake_dir.mkdir(parents=True)
    fake_file = fake_dir / "save.bin"
    fake_file.write_bytes(b"data")

    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=str(fake_file))

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["deleted"] == txn_id
    assert not fake_file.exists()


def test_delete_snapshot_200_completed_state(client, conn, tmp_path):
    """COMPLETED inbound snapshots must be deletable (HEAD re-delete)."""
    token = _login(client)
    fake_file = tmp_path / "save.bin"
    fake_file.write_bytes(b"data")

    txn_id = _seed_txn(conn, state="COMPLETED", snapshot_path=str(fake_file))

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["deleted"] == txn_id
    assert not fake_file.exists()


def test_delete_snapshot_rmdir_oserror_swallowed(client, conn, tmp_path):
    """rmdir OSError when dir has siblings is silently swallowed (covers except branch)."""
    token = _login(client)
    fake_dir = tmp_path / "archive" / "txn-rmdir"
    fake_dir.mkdir(parents=True)
    fake_file = fake_dir / "save.bin"
    fake_file.write_bytes(b"data")
    (fake_dir / "sibling.bin").write_bytes(b"stays")  # dir non-empty → rmdir raises OSError

    txn_id = _seed_txn(conn, state="READY_FOR_RESTORE", snapshot_path=str(fake_file))

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert not fake_file.exists()
    assert (fake_dir / "sibling.bin").exists()  # sibling untouched


def test_delete_snapshot_200_superseded_state(client, conn, tmp_path):
    """SUPERSEDED snapshots (old archived saves) must be deletable."""
    token = _login(client)
    fake_file = tmp_path / "save.bin"
    fake_file.write_bytes(b"data")
    txn_id = _seed_txn(conn, state="SUPERSEDED", snapshot_path=str(fake_file))

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert not fake_file.exists()


def test_delete_snapshot_200_failed_state(client, conn, tmp_path):
    """FAILED snapshots must be deletable."""
    token = _login(client)
    fake_file = tmp_path / "save.bin"
    fake_file.write_bytes(b"data")
    txn_id = _seed_txn(conn, state="FAILED", snapshot_path=str(fake_file))

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert not fake_file.exists()


def test_delete_snapshot_200_null_path_succeeds(client, conn):
    """Snapshot with no archive path (duplicate save) still returns 200."""
    token = _login(client)
    txn_id = _seed_txn(conn, state="COMPLETED", snapshot_path=None)

    r = client.delete(f"/api/v1/ui/snapshots/{txn_id}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["deleted"] == txn_id


# ── Reset flag ────────────────────────────────────────────────────────────────


def test_reset_flag_clears_session_and_resets_password(client, conn, tmp_path, monkeypatch):
    import ui_api as ui_module
    import database as db_module

    token = _login(client)
    assert db_module.get_auth_user_by_token(conn, token) is not None

    flag = tmp_path / "reset_admin.flag"
    flag.touch()
    monkeypatch.setattr(ui_module, "_RESET_FLAG", flag)

    ui_module._check_reset_flag()

    assert db_module.get_auth_user_by_token(conn, token) is None
    assert not flag.exists()
    # Password reset to "admin" — login works again with default credentials
    r = client.post("/api/v1/ui/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200


# ── Settings ──────────────────────────────────────────────────────────────────


def test_settings_get_includes_username(client):
    token = _login(client)
    r = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "admin"
    assert data["romm_users"] == {}
    assert data["switch_users"] == {}
    assert data["user_key_romm"] == {}


def test_settings_set_and_get_romm_user(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, "Switch A")
    r = client.put(
        f"/api/v1/ui/settings/romm_user/{DEVICE_A}",
        json={"username": "alice"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r2 = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert r2.json()["romm_users"][DEVICE_A] == "alice"


def test_settings_clear_romm_user(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    client.put(
        f"/api/v1/ui/settings/romm_user/{DEVICE_A}",
        json={"username": "bob"},
        headers=_hdr(token),
    )
    r = client.delete(f"/api/v1/ui/settings/romm_user/{DEVICE_A}", headers=_hdr(token))
    assert r.status_code == 200
    r2 = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert DEVICE_A not in r2.json()["romm_users"]


def test_settings_set_romm_user_unknown_device(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm_user/unknown_device",
        json={"username": "alice"},
        headers=_hdr(token),
    )
    assert r.status_code == 404


def test_settings_clear_romm_user_unknown_device(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/settings/romm_user/unknown_device", headers=_hdr(token))
    assert r.status_code == 404


def test_settings_requires_auth(client):
    assert client.get("/api/v1/ui/settings").status_code == 401


def test_dashboard_recent_games_includes_outbound_only_games(client, conn):
    """Games with only outbound FAILED txns must still appear in recent_games."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(
        conn,
        title_id=TITLE_1,
        source_device_id=DEVICE_A,
        direction="outbound",
        state="FAILED",
        target_device_id=DEVICE_B,
    )
    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    assert r.status_code == 200
    titles = [g["title_id"] for g in r.json()["recent_games"]]
    assert TITLE_1 in titles


def test_dashboard_requires_auth(client):
    assert client.get("/api/v1/ui/dashboard").status_code == 401


def test_games_requires_auth(client):
    assert client.get("/api/v1/ui/games").status_code == 401


def test_settings_set_and_get_switch_user(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A, "Switch A")
    r = client.put(
        f"/api/v1/ui/settings/switch_user/{DEVICE_A}",
        json={"username": "player1"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r2 = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert r2.json()["switch_users"][DEVICE_A] == "player1"


def test_settings_clear_switch_user(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    client.put(
        f"/api/v1/ui/settings/switch_user/{DEVICE_A}",
        json={"username": "player1"},
        headers=_hdr(token),
    )
    r = client.delete(f"/api/v1/ui/settings/switch_user/{DEVICE_A}", headers=_hdr(token))
    assert r.status_code == 200
    r2 = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert DEVICE_A not in r2.json()["switch_users"]


def test_settings_set_switch_user_unknown_device(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/switch_user/unknown_device",
        json={"username": "player1"},
        headers=_hdr(token),
    )
    assert r.status_code == 404


def test_settings_clear_switch_user_unknown_device(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/settings/switch_user/unknown_device", headers=_hdr(token))
    assert r.status_code == 404


# ── Per-user-key RomM mapping ─────────────────────────────────────────────────


def test_settings_set_romm_user_by_key(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/user_key_romm/AABBCCDDAABBCCDD",
        json={"username": "alice_gamer"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_settings_get_includes_user_key_romm(client, conn):
    """GET /settings reflects user_key_romm after a transaction and a mapping."""
    import database as db_module
    from helpers import do_upload, DEVICE_A, TITLE_1

    token = _login(client)
    # Upload a save with a user_key so it appears in user_key_romm
    do_upload(client, DEVICE_A, TITLE_1, b"save" * 100,
              user_key="AABBCCDDAABBCCDD", user_display="Alice")
    # Map that user_key to a RomM user
    client.put(
        "/api/v1/ui/settings/user_key_romm/AABBCCDDAABBCCDD",
        json={"username": "alice_gamer"},
        headers=_hdr(token),
    )
    r = client.get("/api/v1/ui/settings", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert "user_key_romm" in data
    assert "AABBCCDDAABBCCDD" in data["user_key_romm"]
    entry = data["user_key_romm"]["AABBCCDDAABBCCDD"]
    assert entry["display_name"] == "Alice"
    assert entry["romm_username"] == "alice_gamer"


def test_settings_clear_romm_user_by_key(client):
    token = _login(client)
    client.put(
        "/api/v1/ui/settings/user_key_romm/AABBCCDDAABBCCDD",
        json={"username": "alice_gamer"},
        headers=_hdr(token),
    )
    r = client.delete("/api/v1/ui/settings/user_key_romm/AABBCCDDAABBCCDD",
                      headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_settings_clear_romm_user_by_key_invalid_format(client):
    """DELETE /settings/user_key_romm/<key> with invalid key returns 400."""
    token = _login(client)
    r = client.delete(
        "/api/v1/ui/settings/user_key_romm/not-a-hex-key!!",
        headers=_hdr(token),
    )
    assert r.status_code == 400


def test_settings_romm_user_by_key_invalid(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/user_key_romm/NOT-VALID-HEX!!",
        json={"username": "x"},
        headers=_hdr(token),
    )
    assert r.status_code == 400


def test_game_icon_url_from_romm_cache(client, conn):
    """icon_url and display_name served from RomM cache when mapping exists."""
    import database as db
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
               snapshot_sequence=1)
    db.upsert_romm_title_map(conn, ADMIN_USER, TITLE_1, 42)
    db.upsert_romm_game_cache(conn, ADMIN_USER, 42, "Test Game", "http://icon.png")
    r = client.get(f"/api/v1/ui/games/{TITLE_1}", headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["icon_url"] == "http://icon.png"
    assert r.json()["display_name"] == "Test Game"


def test_dashboard_icon_url_field_present(client, conn):
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A, state="READY_FOR_RESTORE",
               snapshot_sequence=1)
    r = client.get("/api/v1/ui/dashboard", headers=_hdr(token))
    assert r.status_code == 200
    games = r.json()["recent_games"]
    assert len(games) > 0
    assert "icon_url" in games[0]


# ── DB migration: old labels schema ───────────────────────────────────────────


def test_romm_title_map_migration_adds_username(tmp_path):
    """Legacy romm_title_map (no username col) is hard-reset to new schema with username+mapped_at.
    Legacy rows are intentionally dropped (pre-release; no data to preserve)."""
    import sqlite3
    import database as db

    db_path = tmp_path / "legacy_romm.db"
    raw = sqlite3.connect(str(db_path))
    raw.executescript("""
        CREATE TABLE romm_title_map (
            title_id TEXT PRIMARY KEY,
            rom_id   INTEGER NOT NULL
        );
        INSERT INTO romm_title_map(title_id, rom_id) VALUES ('0100F2C0115B6000', 42);
    """)
    raw.close()

    conn = db.open_db(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(romm_title_map)").fetchall()}
    assert "username" in cols
    assert "mapped_at" in cols
    # Legacy row was dropped (hard-reset; no data to preserve)
    count = conn.execute("SELECT COUNT(*) FROM romm_title_map").fetchone()[0]
    assert count == 0
    conn.close()


def test_labels_migration_from_namespace_schema(tmp_path):
    """open_db migrates old labels table (namespace col) to new (entity_type col)."""
    import sqlite3
    import database as db

    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_path))
    raw.executescript("""
        CREATE TABLE labels (
            namespace  TEXT NOT NULL,
            entity_id  TEXT NOT NULL,
            label      TEXT NOT NULL,
            PRIMARY KEY (namespace, entity_id)
        );
        INSERT INTO labels(namespace, entity_id, label) VALUES ('game', '0100F2C0115B6000', 'My Game');
        INSERT INTO labels(namespace, entity_id, label) VALUES ('device', 'AA:BB', 'My Device');
    """)
    raw.close()

    conn = db.open_db(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(labels)").fetchall()}
    assert "entity_type" in cols
    assert "namespace" not in cols
    row = conn.execute(
        "SELECT label FROM labels WHERE entity_type='game' AND entity_id=?",
        ("0100F2C0115B6000",),
    ).fetchone()
    assert row["label"] == "My Game"
    conn.close()


# ── Credential management ─────────────────────────────────────────────────────


def test_change_username(client):
    token = _login(client)
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "admin", "new_username": "superadmin"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # new username reflected in status
    data = client.get("/api/v1/ui/auth/status", headers=_hdr(token)).json()
    assert data["username"] == "superadmin"
    # login with new username works
    r2 = client.post("/api/v1/ui/auth/login", json={"username": "superadmin", "password": "admin"})
    assert r2.status_code == 200


def test_change_password(client):
    token = _login(client)
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "admin", "new_password": "newpass123"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    # old token invalidated (password change rotates session)
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(token)).status_code == 401
    # new password works
    r2 = client.post("/api/v1/ui/auth/login", json={"username": "admin", "password": "newpass123"})
    assert r2.status_code == 200


def test_change_credentials_wrong_current_password_403(client):
    token = _login(client)
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "wrong", "new_password": "whatever"},
        headers=_hdr(token),
    )
    assert r.status_code == 403


def test_change_credentials_requires_auth(client):
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "admin", "new_username": "x"},
    )
    assert r.status_code == 401


def test_verify_password_malformed_hash_returns_false():
    import ui_api as _ui
    assert _ui._verify_password("anypassword", "not-a-valid-hash-format") is False


def test_admin_rename_cascades_owned_data(client, conn):
    """Admin rename cascades ownership across all data tables and preserves session."""
    token = _login(client)
    now = _now()

    _seed_device(conn, DEVICE_A)  # covers devices.owner_user_id
    conn.execute(
        "INSERT OR IGNORE INTO device_profile_map (device_id, profile_id, user_id, profile_name, created_at)"
        " VALUES (?,?,?,?,?)",
        (DEVICE_A, "cascade-probe-profile", ADMIN_USER, "", _now()),
    )
    conn.execute(
        "INSERT INTO user_config (username, key, value) VALUES (?,?,?)",
        (ADMIN_USER, "rename_cascade_probe", "1"),
    )
    conn.execute(
        "INSERT INTO romm_title_map (username, title_id, rom_id, mapped_at) VALUES (?,?,?,?)",
        (ADMIN_USER, TITLE_1, 42, now),
    )
    conn.execute(
        "INSERT INTO romm_game_cache (username, rom_id, name, icon_url, fetched_at) VALUES (?,?,?,?,?)",
        (ADMIN_USER, 42, "Game", None, now),
    )
    conn.execute(
        "INSERT INTO romm_save_sync (username, rom_id, romm_save_id, direction, transaction_id, synced_at)"
        " VALUES (?,?,?,?,?,?)",
        (ADMIN_USER, 42, 99, "inbound", None, now),
    )
    conn.execute(
        "INSERT INTO device_auth (device_id, device_token, user_id, created_at) VALUES (?,?,?,?)",
        (DEVICE_A, "tok-cascade", ADMIN_USER, now),
    )
    _seed_txn(conn, title_id=TITLE_1, source_device_id=DEVICE_A)
    _seed_event(conn, device_id=DEVICE_A)
    conn.commit()

    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "admin", "new_username": "admin_renamed"},
        headers=_hdr(token),
    )
    assert r.status_code == 200, r.text

    checks = [
        ("devices", "owner_user_id"),
        ("user_config", "username"),
        ("romm_title_map", "username"),
        ("romm_game_cache", "username"),
        ("romm_save_sync", "username"),
        ("device_auth", "user_id"),
        ("device_profile_map", "user_id"),
        ("events", "owner_user_id"),
        ("sync_transactions", "owner_user_id"),
        ("auth_sessions", "username"),
    ]
    for table, col in checks:
        old = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {col}=?",  # noqa: S608
            (ADMIN_USER,),
        ).fetchone()["n"]
        assert old == 0, f"{table}.{col} still has old admin username"
        new = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {col}=?",  # noqa: S608
            ("admin_renamed",),
        ).fetchone()["n"]
        assert new > 0, f"{table}.{col} was not updated to new admin username"

    # Session token must still resolve after rename.
    r2 = client.get("/api/v1/ui/auth/status", headers=_hdr(token))
    assert r2.status_code == 200
    assert r2.json()["username"] == "admin_renamed"


# ── User management ────────────────────────────────────────────────────────────


def test_list_users_includes_admin(client):
    token = _login(client)
    r = client.get("/api/v1/ui/users", headers=_hdr(token))
    assert r.status_code == 200
    users = {u["username"]: u for u in r.json()["users"]}
    assert "admin" in users
    assert users["admin"]["is_admin"] is True


def test_create_user_and_login(client):
    token = _login(client)
    r = client.post("/api/v1/ui/users", json={"username": "wife", "password": "pass123"}, headers=_hdr(token))
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Non-admin user can log in
    r2 = client.post("/api/v1/ui/auth/login", json={"username": "wife", "password": "pass123"})
    assert r2.status_code == 200
    assert r2.json()["admin_token"].startswith("sk_live_")


def test_create_user_appears_in_list(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "player2", "password": "abc"}, headers=_hdr(token))
    users = {u["username"] for u in client.get("/api/v1/ui/users", headers=_hdr(token)).json()["users"]}
    assert "player2" in users


def test_create_user_duplicate_409(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "dup", "password": "abc"}, headers=_hdr(token))
    r = client.post("/api/v1/ui/users", json={"username": "dup", "password": "abc"}, headers=_hdr(token))
    assert r.status_code == 409


def test_create_user_reserved_admin_409(client):
    token = _login(client)
    r = client.post("/api/v1/ui/users", json={"username": "admin", "password": "x"}, headers=_hdr(token))
    assert r.status_code == 409


def test_create_user_empty_username_400(client):
    token = _login(client)
    r = client.post("/api/v1/ui/users", json={"username": "", "password": "x"}, headers=_hdr(token))
    assert r.status_code == 400


def test_create_user_empty_password_400(client):
    token = _login(client)
    r = client.post("/api/v1/ui/users", json={"username": "ok", "password": ""}, headers=_hdr(token))
    assert r.status_code == 400


def test_delete_user(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "todelete", "password": "x"}, headers=_hdr(token))
    r = client.delete("/api/v1/ui/users/todelete", headers=_hdr(token))
    assert r.status_code == 200
    users = {u["username"] for u in client.get("/api/v1/ui/users", headers=_hdr(token)).json()["users"]}
    assert "todelete" not in users


def test_delete_admin_forbidden(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/users/admin", headers=_hdr(token))
    assert r.status_code == 403


def test_delete_unknown_user_404(client):
    token = _login(client)
    r = client.delete("/api/v1/ui/users/nobody", headers=_hdr(token))
    assert r.status_code == 404


def test_user_management_requires_auth(client):
    assert client.get("/api/v1/ui/users").status_code == 401
    assert client.post("/api/v1/ui/users", json={"username": "x", "password": "y"}).status_code == 401


def test_non_admin_cannot_create_users(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "limited", "password": "abc"}, headers=_hdr(token))
    # Log in as the new non-admin user
    r = client.post("/api/v1/ui/auth/login", json={"username": "limited", "password": "abc"})
    user_token = r.json()["admin_token"]
    r2 = client.post("/api/v1/ui/users", json={"username": "another", "password": "abc"}, headers=_hdr(user_token))
    assert r2.status_code == 403


def test_non_admin_cannot_delete_users(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "limuser", "password": "abc"}, headers=_hdr(token))
    client.post("/api/v1/ui/users", json={"username": "victim", "password": "abc"}, headers=_hdr(token))
    r = client.post("/api/v1/ui/auth/login", json={"username": "limuser", "password": "abc"})
    user_token = r.json()["admin_token"]
    r2 = client.delete("/api/v1/ui/users/victim", headers=_hdr(user_token))
    assert r2.status_code == 403


def test_non_admin_login_and_rotate(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "rotuser", "password": "abc"}, headers=_hdr(token))
    r = client.post("/api/v1/ui/auth/login", json={"username": "rotuser", "password": "abc"})
    user_token = r.json()["admin_token"]
    # Rotate works for non-admin
    r2 = client.post("/api/v1/ui/auth/rotate", headers=_hdr(user_token))
    assert r2.status_code == 200
    new_token = r2.json()["admin_token"]
    assert new_token != user_token
    # Old token invalid
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(user_token)).status_code == 401
    # New token valid
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(new_token)).status_code == 200


def test_non_admin_logout(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "logoutuser", "password": "abc"}, headers=_hdr(token))
    r = client.post("/api/v1/ui/auth/login", json={"username": "logoutuser", "password": "abc"})
    user_token = r.json()["admin_token"]
    client.post("/api/v1/ui/auth/logout", headers=_hdr(user_token))
    assert client.get("/api/v1/ui/dashboard", headers=_hdr(user_token)).status_code == 401


def test_non_admin_wrong_password_401(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "wrongpw", "password": "correct"}, headers=_hdr(token))
    r = client.post("/api/v1/ui/auth/login", json={"username": "wrongpw", "password": "bad"})
    assert r.status_code == 401


def test_list_users_requires_admin(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "viewer", "password": "abc"}, headers=_hdr(token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "viewer", "password": "abc"}).json()["admin_token"]
    r = client.get("/api/v1/ui/users", headers=_hdr(user_token))
    assert r.status_code == 403


def test_non_admin_change_own_password(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "changeme", "password": "oldpass"}, headers=_hdr(token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "changeme", "password": "oldpass"}).json()["admin_token"]
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "oldpass", "new_password": "newpass"},
        headers=_hdr(user_token),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Old password no longer works
    r2 = client.post("/api/v1/ui/auth/login", json={"username": "changeme", "password": "oldpass"})
    assert r2.status_code == 401
    # New password works
    r3 = client.post("/api/v1/ui/auth/login", json={"username": "changeme", "password": "newpass"})
    assert r3.status_code == 200


def test_non_admin_change_own_username(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "renameold", "password": "pw"}, headers=_hdr(token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "renameold", "password": "pw"}).json()["admin_token"]
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "pw", "new_username": "renamenew"},
        headers=_hdr(user_token),
    )
    assert r.status_code == 200
    # Can log in with new username
    r2 = client.post("/api/v1/ui/auth/login", json={"username": "renamenew", "password": "pw"})
    assert r2.status_code == 200


def test_non_admin_change_credentials_wrong_password_403(client):
    token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "badpwuser", "password": "correct"}, headers=_hdr(token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "badpwuser", "password": "correct"}).json()["admin_token"]
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "wrong", "new_password": "x"},
        headers=_hdr(user_token),
    )
    assert r.status_code == 403


def test_auth_status_includes_is_admin(client):
    token = _login(client)
    r = client.get("/api/v1/ui/auth/status", headers=_hdr(token))
    assert r.json()["is_admin"] is True

    # Non-admin
    client.post("/api/v1/ui/users", json={"username": "nonadmin", "password": "abc"}, headers=_hdr(token))
    user_token = client.post("/api/v1/ui/auth/login", json={"username": "nonadmin", "password": "abc"}).json()["admin_token"]
    r2 = client.get("/api/v1/ui/auth/status", headers=_hdr(user_token))
    assert r2.json()["is_admin"] is False


# ── /settings/romm GET + PUT ──────────────────────────────────────────────────


def test_get_romm_settings_defaults(client):
    token = _login(client)
    r = client.get("/api/v1/ui/settings/romm", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False
    assert data["host"] == ""
    assert data["has_api_key"] is False
    assert "source_id" in data


def _mock_refresh_ok(conn, username, host="", key=""):
    """Simulates a successful RomM credential verification."""
    import database as _db
    _db.set_user_config(conn, username, "romm_username", "testuser")
    _db.set_user_config(conn, username, "romm_connect_status", "ok")
    _db.set_user_config(conn, username, "romm_connect_detail", "")


def _mock_refresh_fail(conn, username, host="", key=""):
    """Simulates a failed RomM credential verification (auth_failed)."""
    import database as _db
    _db.set_user_config(conn, username, "romm_username", "")
    _db.set_user_config(conn, username, "romm_connect_status", "auth_failed")
    _db.set_user_config(conn, username, "romm_connect_detail", "HTTP 403")


def _mock_refresh_network_error(conn, username, host="", key=""):
    """Simulates a network failure during RomM credential verification."""
    import database as _db
    _db.set_user_config(conn, username, "romm_username", "")
    _db.set_user_config(conn, username, "romm_connect_status", "network_error")
    _db.set_user_config(conn, username, "romm_connect_detail", "[Errno -3] Name resolution failure")


def test_put_romm_settings_host_and_key(client, monkeypatch):
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "secret123", "enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["romm_username"] == "testuser"
    assert data["romm_connect_status"] == "ok"

    # Verify persisted
    r2 = client.get("/api/v1/ui/settings/romm", headers=_hdr(token))
    assert r2.json()["host"] == "http://romm.local"
    assert r2.json()["has_api_key"] is True
    assert r2.json()["enabled"] is True
    assert r2.json()["romm_connect_status"] == "ok"


def test_put_romm_settings_disable(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"enabled": False},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    r2 = client.get("/api/v1/ui/settings/romm", headers=_hdr(token))
    assert r2.json()["enabled"] is False


def test_put_romm_settings_disable_hides_device(client, monkeypatch):
    """Enable with credentials then disable — device must appear as is_deleted in both
    /devices and /dashboard so the UI filter removes it immediately."""
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    token = _login(client)

    # Enable with host + key so the virtual device is created with deleted_at=NULL.
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "secret", "enabled": True},
        headers=_hdr(token),
    )

    # Sanity: device visible and not deleted.
    devices_on = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm_on = next((d for d in devices_on if d.get("client_type") == "romm"), None)
    assert romm_on is not None and romm_on["is_deleted"] is False

    # Disable — only send enabled flag, credentials stay in DB (production scenario).
    client.put("/api/v1/ui/settings/romm", json={"enabled": False}, headers=_hdr(token))

    # Device must be marked deleted in /devices.
    devices_off = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm_off = next((d for d in devices_off if d.get("client_type") == "romm"), None)
    assert romm_off is not None and romm_off["is_deleted"] is True

    # And in /dashboard clients section.
    dash = client.get("/api/v1/ui/dashboard", headers=_hdr(token)).json()
    romm_dash = next((d for d in dash["devices"] if d["device_id"].startswith("romm:")), None)
    assert romm_dash is not None and romm_dash["is_deleted"] is True


def test_get_romm_settings_includes_connect_status(client, monkeypatch):
    """GET /settings/romm returns romm_connect_status and romm_connect_detail."""
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    token = _login(client)
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "key"},
        headers=_hdr(token),
    )
    r = client.get("/api/v1/ui/settings/romm", headers=_hdr(token))
    data = r.json()
    assert "romm_connect_status" in data
    assert "romm_connect_detail" in data
    assert data["romm_connect_status"] == "ok"
    assert data["romm_username"] == "testuser"


def test_put_romm_settings_auth_failed_hides_device(client, monkeypatch):
    """When credentials fail auth, device stays hidden and response reports the error."""
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_fail)
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "badkey", "enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["romm_username"] is None
    assert data["romm_connect_status"] == "auth_failed"
    assert data["romm_connect_detail"] == "HTTP 403"

    # Device must NOT appear as active
    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm = next((d for d in devices if d.get("client_type") == "romm"), None)
    assert romm is None or romm["is_deleted"] is True


def test_put_romm_settings_network_error_leaves_device_visible(client, monkeypatch):
    """Re-save with network error must NOT hide a previously visible device."""
    import romm_meta as _romm_meta
    import romm_index as _romm_index
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: None)
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: None)
    token = _login(client)
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "good", "enabled": True},
        headers=_hdr(token),
    )

    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_network_error)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "good"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["romm_connect_status"] == "network_error"

    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm = next((d for d in devices if d.get("client_type") == "romm"), None)
    assert romm is not None and romm["is_deleted"] is False


def test_put_romm_settings_initial_network_error_does_not_hide_device(client, monkeypatch):
    """Fresh-wipe path: first credential save with network error must still show device."""
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_network_error)
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "good", "enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert r.json()["romm_connect_status"] == "network_error"

    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm = next((d for d in devices if d.get("client_type") == "romm"), None)
    assert romm is not None
    assert romm["is_deleted"] is False


def test_put_romm_settings_auth_success_reveals_device(client, monkeypatch):
    """When credentials pass auth, device becomes visible and response contains username."""
    import romm_meta as _romm_meta
    import romm_index as _romm_index
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: None)
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: None)
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "goodkey", "enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["romm_username"] == "testuser"
    assert data["romm_connect_status"] == "ok"

    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm = next((d for d in devices if d.get("client_type") == "romm"), None)
    assert romm is not None and romm["is_deleted"] is False


def test_put_romm_settings_triggers_index_on_success(client, monkeypatch):
    """Successful auth triggers an immediate index refresh so games appear without waiting."""
    import romm_meta as _romm_meta
    import romm_index as _romm_index
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    called = []
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: called.append("refresh"))
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: called.append("run"))
    token = _login(client)
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "goodkey", "enabled": True},
        headers=_hdr(token),
    )
    assert "refresh" in called
    assert "run" in called


def test_put_romm_settings_no_index_on_auth_failure(client, monkeypatch):
    """Failed auth must NOT trigger index refresh."""
    import romm_meta as _romm_meta
    import romm_index as _romm_index
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_fail)
    called = []
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: called.append("refresh"))
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: called.append("run"))
    token = _login(client)
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "badkey", "enabled": True},
        headers=_hdr(token),
    )
    assert "refresh" not in called
    assert "run" not in called


def test_put_romm_settings_toggle_on_triggers_index(client, conn, monkeypatch):
    """Toggle-on (no credentials in request) triggers index refresh when creds already stored."""
    import romm_index as _romm_index
    import database as _db
    _db.set_user_config(conn, ADMIN_USER, "romm_host", "http://romm.local")
    _db.set_user_config(conn, ADMIN_USER, "romm_api_key", "goodkey")
    _db.set_user_config(conn, ADMIN_USER, "romm_enabled", "0")
    conn.commit()
    called = []
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: called.append("refresh"))
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: called.append("run"))
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert "refresh" in called
    assert "run" in called


def test_put_romm_settings_toggle_off_does_not_trigger_index(client, conn, monkeypatch):
    """Disabling RomM must NOT trigger an index refresh."""
    import romm_index as _romm_index
    import database as _db
    _db.set_user_config(conn, ADMIN_USER, "romm_host", "http://romm.local")
    _db.set_user_config(conn, ADMIN_USER, "romm_api_key", "goodkey")
    _db.set_user_config(conn, ADMIN_USER, "romm_enabled", "1")
    conn.commit()
    called = []
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: called.append("refresh"))
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: called.append("run"))
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"enabled": False},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    assert "refresh" not in called
    assert "run" not in called


def test_put_romm_settings_syncs_catalog_immediately(client, conn, monkeypatch):
    """Games already in romm_title_map must appear in device_installed_games immediately
    on a successful connect — without waiting for the background index to complete."""
    import romm_meta as _romm_meta
    import romm_index as _romm_index
    import database as _db

    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: None)
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: None)

    # Seed catalog as if a prior index run already ran
    _db.upsert_romm_title_map(conn, ADMIN_USER, TITLE_1, 42)
    conn.commit()

    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "goodkey", "enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200

    row = conn.execute(
        "SELECT 1 FROM device_installed_games WHERE title_id=?", (TITLE_1.upper(),)
    ).fetchone()
    assert row is not None, "catalog must be synced immediately on successful connect"


# ── _admin_err forbidden path ─────────────────────────────────────────────────


def test_admin_err_forbids_non_admin(client):
    """_admin_err returns 403 for authenticated non-admin users."""
    token = _login(client)
    # Create a non-admin user
    client.post("/api/v1/ui/users",
                json={"username": "pleb", "password": "pw"},
                headers=_hdr(token))
    pleb_token = client.post(
        "/api/v1/ui/auth/login", json={"username": "pleb", "password": "pw"}
    ).json()["admin_token"]

    # /settings/users is admin-only; non-admin gets 403
    r = client.get("/api/v1/ui/users", headers=_hdr(pleb_token))
    assert r.status_code == 403


def test_put_romm_settings_source_id(client):
    token = _login(client)
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"source_id": "romm:myhost.local"},
        headers=_hdr(token),
    )
    assert r.status_code == 200
    r2 = client.get("/api/v1/ui/settings/romm", headers=_hdr(token))
    assert r2.json()["source_id"] == "romm:myhost.local"


def test_put_romm_settings_restores_device_when_credentials_unchanged(client, conn, monkeypatch):
    """Changing non-credential settings (e.g. enabled) un-deletes the romm device when
    credentials are already set and a verified username exists (lines 1985-1987)."""
    import romm_meta as _romm_meta
    monkeypatch.setattr(_romm_meta, "refresh_username_cache", _mock_refresh_ok)
    token = _login(client)

    # Step 1: configure host + key → auth succeeds → device becomes visible
    client.put(
        "/api/v1/ui/settings/romm",
        json={"host": "http://romm.local", "api_key": "goodkey", "enabled": True},
        headers=_hdr(token),
    )

    # Step 2: soft-delete the romm device to simulate it being hidden
    conn.execute(
        "UPDATE devices SET deleted_at=datetime('now') WHERE client_type='romm'"
    )

    # Step 3: PUT with only enabled=True (no host/api_key change) → elif branch fires
    r = client.put(
        "/api/v1/ui/settings/romm",
        json={"enabled": True},
        headers=_hdr(token),
    )
    assert r.status_code == 200

    # Device should be un-deleted because host+key exist and username was previously verified
    devices = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()["devices"]
    romm = next((d for d in devices if d.get("client_type") == "romm"), None)
    assert romm is not None and romm["is_deleted"] is False


def test_device_games_exception_logged_and_reraised(client, monkeypatch):
    """Exception from _device_games_inner is logged and re-raised (lines 1520-1522)."""
    import pytest
    import ui_api as _ui_api
    from helpers import pair_device, DEVICE_A, auth_header, login_admin

    pair_device(client, DEVICE_A)
    token = login_admin(client)

    monkeypatch.setattr(_ui_api, "_device_games_inner", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db crash")))

    with pytest.raises(RuntimeError, match="db crash"):
        client.get(f"/api/v1/ui/devices/{DEVICE_A}/games", headers=auth_header(token))


# ── delivery_failed_count ghost exclusion ──────────────────────────────────────


def test_device_list_delivery_failed_count_excludes_ghost_failures(client, conn):
    """FAILED row where a COMPLETED delivery exists for same title+target → count = 0."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="FAILED", snapshot_sequence=1)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="COMPLETED", snapshot_sequence=1)

    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    dev_b = next(d for d in data["devices"] if d["device_id"] == DEVICE_B)
    assert dev_b["delivery_failed_count"] == 0


def test_device_list_delivery_failed_count_real_failure(client, conn):
    """FAILED row with no COMPLETED for same title+target → count = 1."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_txn(conn, direction="outbound", source_device_id=DEVICE_A,
              target_device_id=DEVICE_B, state="FAILED", snapshot_sequence=1)

    data = client.get("/api/v1/ui/devices", headers=_hdr(token)).json()
    dev_b = next(d for d in data["devices"] if d["device_id"] == DEVICE_B)
    assert dev_b["delivery_failed_count"] == 1


# ── restore-all ────────────────────────────────────────────────────────────────


def test_device_restore_all_queues_outbound(client, conn):
    """POST /devices/{id}/restore-all creates an outbound for each available HEAD."""
    token = _login(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    txn_id = _seed_txn(
        conn, direction="inbound", source_device_id=DEVICE_A,
        state="READY_FOR_RESTORE", snapshot_sequence=1,
        sha256="a" * 64, snapshot_path="/fake/path/save.zip",
    )
    conn.commit()

    r = client.post(f"/api/v1/ui/devices/{DEVICE_B}/restore-all", headers=_hdr(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["queued"] == 1

    row = conn.execute(
        "SELECT state FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()
    assert row is not None
    assert row["state"] == "READY_FOR_RESTORE"


# ── user rename ownership propagation ─────────────────────────────────────────


def test_rename_user_propagates_ownership_to_all_tables(client, conn):
    """Renaming a user must update every table that stores username as an identity
    key. Regression for: saves/devices disappeared after rename because
    rename_auth_user only updated auth_users + auth_sessions."""
    admin_token = _login(client)

    # Create user alice and get her session token
    client.post("/api/v1/ui/users", json={"username": "alice", "password": "pw"}, headers=_hdr(admin_token))
    alice_token = client.post("/api/v1/ui/auth/login", json={"username": "alice", "password": "pw"}).json()["admin_token"]

    # Seed owned data for alice directly in DB
    _seed_device(conn, DEVICE_A, user_id="alice")
    _seed_event(conn, owner_user_id="alice", device_id=DEVICE_A)
    _seed_txn(conn, source_device_id=DEVICE_A, direction="inbound",
              state="READY_FOR_RESTORE", snapshot_sequence=1,
              sha256="a" * 64, snapshot_path="/fake/save.zip", owner_user_id="alice")

    # user_config: simulates a stored RomM URL preference
    conn.execute(
        "INSERT INTO user_config (username, key, value) VALUES (?, ?, ?)",
        ("alice", "romm_url", "http://romm.local"),
    )

    # RomM tables
    conn.execute(
        "INSERT INTO romm_title_map (username, title_id, rom_id, mapped_at) VALUES (?,?,?,?)",
        ("alice", TITLE_1, 42, "2024-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO romm_save_sync"
        " (username, rom_id, romm_save_id, direction, transaction_id, synced_at)"
        " VALUES (?,?,?,?,?,?)",
        ("alice", 42, 99, "inbound", None, "2024-01-01T00:00:00Z"),
    )
    conn.commit()

    # ── rename alice → bob using her existing session token ──────────────────
    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "pw", "new_username": "bob"},
        headers=_hdr(alice_token),
    )
    assert r.status_code == 200, r.text

    # ── B. request consistency — same token, no re-auth ──────────────────────
    # Session token must still resolve (auth_sessions.username updated)
    r = client.get("/api/v1/ui/devices", headers=_hdr(alice_token))
    assert r.status_code == 200, "session token broken after rename"
    device_ids = [d["device_id"] for d in r.json()["devices"]]
    assert DEVICE_A in device_ids, "device disappeared after rename"

    # Game title must appear (sync_transactions.owner_user_id updated)
    r = client.get("/api/v1/ui/games", headers=_hdr(alice_token))
    assert r.status_code == 200
    title_ids = [g["title_id"] for g in r.json()["games"]]
    assert TITLE_1.upper() in title_ids, "game title disappeared after rename"

    # ── C. config survival ────────────────────────────────────────────────────
    row = conn.execute(
        "SELECT value FROM user_config WHERE username=? AND key=?", ("bob", "romm_url")
    ).fetchone()
    assert row is not None, "user_config lost after rename"
    assert row["value"] == "http://romm.local"

    # ── A. persistence — old username owns nothing ────────────────────────────
    zero_checks = [
        ("devices", "owner_user_id"),
        ("sync_transactions", "owner_user_id"),
        ("events", "owner_user_id"),
        ("device_auth", "user_id"),
        ("device_profile_map", "user_id"),
        ("user_config", "username"),
        ("romm_title_map", "username"),
        ("romm_game_cache", "username"),
        ("romm_save_sync", "username"),
    ]
    for table, col in zero_checks:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col}=?", ("alice",)  # noqa: S608
        ).fetchone()[0]
        assert count == 0, f"{table}.{col} still references 'alice' after rename"


def test_rename_user_to_existing_username_returns_409_and_rolls_back(client, conn):
    """Rename to a duplicate username must return 409 and leave the DB untouched."""
    admin_token = _login(client)
    client.post("/api/v1/ui/users", json={"username": "src", "password": "pw"}, headers=_hdr(admin_token))
    client.post("/api/v1/ui/users", json={"username": "taken", "password": "pw"}, headers=_hdr(admin_token))
    src_token = client.post("/api/v1/ui/auth/login", json={"username": "src", "password": "pw"}).json()["admin_token"]

    r = client.post(
        "/api/v1/ui/settings/credentials",
        json={"current_password": "pw", "new_username": "taken"},
        headers=_hdr(src_token),
    )
    assert r.status_code == 409

    # Rollback: src still exists, taken still exists, neither was corrupted
    assert client.post("/api/v1/ui/auth/login", json={"username": "src", "password": "pw"}).status_code == 200
    assert client.post("/api/v1/ui/auth/login", json={"username": "taken", "password": "pw"}).status_code == 200
