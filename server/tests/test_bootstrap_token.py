"""
Bootstrap token delivery tests.
DB layer: set_device_config_pending, consume_pending_config.
HTTP: POST /api/v1/sync/device-config.
"""

from datetime import UTC, datetime, timedelta

import database as db
from helpers import DEVICE_A, TITLE_1, auth_header, do_upload, login_admin

SAVE = b"bootstrap-test" * 100
PROFILE_A = "AAAA111122223333"
PROFILE_B = "BBBB111122223333"


def _hdr(token):
    return auth_header(token)


def _seed(client, device_id=DEVICE_A):
    do_upload(client, device_id, TITLE_1, SAVE)


def _pair(client, device_id=DEVICE_A):
    """Pair device via UI — also sets config_pending=1."""
    admin = login_admin(client)
    r = client.post(f"/api/v1/ui/devices/{device_id}/token", headers=_hdr(admin))
    assert r.status_code == 200
    return r.json()["token"]


def _now_str():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale_str(minutes=20):
    return (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_devices_stale(conn, device_id=DEVICE_A, minutes=20):
    conn.execute("UPDATE devices SET last_seen=? WHERE device_id=?", (_stale_str(minutes), device_id))


# ── DB layer ──────────────────────────────────────────────────────────────────


def test_db_set_config_pending(conn):
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    row = conn.execute(
        "SELECT config_pending FROM device_auth WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row["config_pending"] == 1


def test_db_consume_pending_config_happy(conn):
    token = db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    result = db.consume_pending_config(conn, DEVICE_A, _now_str())
    assert result == token
    row = conn.execute(
        "SELECT config_pending FROM device_auth WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row["config_pending"] == 0


def test_db_consume_pending_config_no_flag_returns_none(conn):
    db.create_device_token(conn, DEVICE_A, "admin")  # config_pending=0 by default
    assert db.consume_pending_config(conn, DEVICE_A, _now_str()) is None


def test_db_consume_pending_config_stale_last_seen_returns_none(conn):
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    assert db.consume_pending_config(conn, DEVICE_A, _stale_str(20)) is None


def test_db_consume_pending_config_null_last_seen_returns_none(conn):
    db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    assert db.consume_pending_config(conn, DEVICE_A, None) is None


def test_db_consume_pending_config_idempotent(conn):
    """Second consume after flag cleared → None."""
    token = db.create_device_token(conn, DEVICE_A, "admin")
    db.set_device_config_pending(conn, DEVICE_A)
    assert db.consume_pending_config(conn, DEVICE_A, _now_str()) == token
    assert db.consume_pending_config(conn, DEVICE_A, _now_str()) is None


# ── HTTP endpoint ─────────────────────────────────────────────────────────────


def test_device_config_happy_path_returns_token(client):
    """Paired + pending + recent last_seen → device_token returned."""
    _seed(client)
    device_token = _pair(client)  # also sets config_pending=1
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert r.json().get("device_token") == device_token


def test_device_config_no_pending_flag_redelivers_when_no_bearer(client, conn):
    """Paired device with config_pending=0 and no Bearer → re-delivers token (lost-token recovery)."""
    _seed(client)
    device_token = _pair(client)
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (DEVICE_A,))
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert r.json().get("device_token") == device_token


def test_device_config_first_contact_returns_pairing_code(client, conn):
    """Brand new device (never seen) — registered on first contact, returns pairing code."""
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    data = r.json()
    assert "pairing_code" in data
    assert len(data["pairing_code"]) == 6
    # Device is now registered
    row = conn.execute("SELECT device_id FROM devices WHERE device_id=?", (DEVICE_A,)).fetchone()
    assert row is not None


def test_device_config_stale_last_seen_still_delivers_token(client, conn):
    """device-config refreshes last_seen, so a previously-stale device gets the token when it contacts us."""
    _seed(client)
    device_token = _pair(client)
    _make_devices_stale(conn)  # simulate device offline for 20 min
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert r.json().get("device_token") == device_token


def test_device_config_repeated_calls_without_bearer_redeliver_token(client):
    """Every no-Bearer device-config call re-delivers the token (lost-token recovery is repeatable)."""
    _seed(client)
    device_token = _pair(client)
    client.post("/api/v1/sync/device-config", json={"known_profiles": []}, headers={"X-Device-ID": DEVICE_A})
    r = client.post("/api/v1/sync/device-config", json={"known_profiles": []}, headers={"X-Device-ID": DEVICE_A})
    assert r.json().get("device_token") == device_token


def test_device_config_upserts_known_profiles_regardless_of_token(client, conn):
    """Profiles reported are cached even when device already has its token (sends Bearer → {} response)."""
    _seed(client)
    device_token = _pair(client)
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (DEVICE_A,))
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [
            {"profile_id": PROFILE_A, "profile_name": "Alice"},
            {"profile_id": PROFILE_B, "profile_name": "Bob"},
        ]},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.json() == {}  # device has token and sends it → nothing to deliver
    rows = conn.execute(
        "SELECT profile_id FROM device_known_profiles WHERE device_id=? ORDER BY profile_id",
        (DEVICE_A,),
    ).fetchall()
    assert {r["profile_id"] for r in rows} == {PROFILE_A, PROFILE_B}


def test_device_config_redelivers_token_after_local_wipe(client, conn):
    """
    Device loses its local token (omnisave folder wiped on-device) after the initial
    delivery (config_pending already consumed). Next device-config with no Authorization
    header must re-deliver the token so the device can recover without SQL intervention.

    Regression: delete-then-re-add from UI sets config_pending=1; token is delivered and
    config_pending cleared; user then wipes the Switch omnisave folder; device is stuck —
    server has device_auth row, config_pending=0, device has no token and gets {} forever.
    """
    _seed(client)
    device_token = _pair(client)  # config_pending=1

    # First delivery: Switch receives token, config_pending→0
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.json().get("device_token") == device_token
    assert conn.execute(
        "SELECT config_pending FROM device_auth WHERE device_id=?", (DEVICE_A,)
    ).fetchone()["config_pending"] == 0

    # Device wipes local state — calls device-config again with no Bearer token.
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 200
    assert r.json().get("device_token") == device_token


def test_device_config_no_redeliver_when_stale_bearer(client, conn):
    """Stale-but-correctly-formatted bearer → no re-delivery (let 401 cycle handle recovery)."""
    _seed(client)
    _pair(client)
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (DEVICE_A,))
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={
            "X-Device-ID": DEVICE_A,
            "Authorization": "Bearer sk_device_thisisastaletokenfrompreviousserver",
        },
    )
    assert r.status_code == 200
    assert "device_token" not in r.json()


def test_device_config_no_redeliver_when_bearer_present(client, conn):
    """Device already has its token and sends it as Bearer — server returns {} (nothing to do)."""
    _seed(client)
    device_token = _pair(client)
    conn.execute("UPDATE device_auth SET config_pending=0 WHERE device_id=?", (DEVICE_A,))
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
    )
    assert r.status_code == 200
    assert r.json() == {}


def test_device_config_missing_device_id_header_400(client):
    r = client.post("/api/v1/sync/device-config", json={"known_profiles": []})
    assert r.status_code == 400


# ── Golden-path: bootstrap → profile claim → ownership ───────────────────────


def test_golden_path_bootstrap_and_ownership(client, conn):
    """
    Full flow: device reports profiles via device-config, admin claims them,
    subsequent syncs get correct owner stamps.
    """
    # 1. Device makes first anonymous sync (registers in devices)
    _seed(client)

    # 2. Device reports profiles at boot
    client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": [
            {"profile_id": PROFILE_A, "profile_name": "Alice"},
            {"profile_id": PROFILE_B, "profile_name": "Bob"},
        ]},
        headers={"X-Device-ID": DEVICE_A},
    )

    # 3. Admin pairs device (sets config_pending=1) and delivers token
    device_token = _pair(client)
    r = client.post(
        "/api/v1/sync/device-config",
        json={"known_profiles": []},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.json().get("device_token") == device_token

    # 4. Admin claims profiles for users
    admin = login_admin(client)
    client.post("/api/v1/ui/users", json={"username": "alice", "password": "pw"}, headers=_hdr(admin))
    client.post("/api/v1/ui/users", json={"username": "bob", "password": "pw"}, headers=_hdr(admin))
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_A}", json={"user_id": "alice"}, headers=_hdr(admin))
    client.put(f"/api/v1/ui/devices/{DEVICE_A}/profiles/{PROFILE_B}", json={"user_id": "bob"}, headers=_hdr(admin))

    # 5. Inbound syncs stamp correct owners
    def _owner(user_key):
        r = client.post(
            "/api/v1/sync/transactions/inbound",
            json={"title_id": TITLE_1, "total_size_bytes": len(SAVE), "user_key": user_key},
            headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {device_token}"},
        )
        assert r.status_code == 200
        return conn.execute(
            "SELECT owner_user_id FROM sync_transactions WHERE transaction_id=?",
            (r.json()["transaction_id"],),
        ).fetchone()["owner_user_id"]

    assert _owner(PROFILE_A) == "alice"
    assert _owner(PROFILE_B) == "bob"
    assert _owner("UNKNOWN000000000") == "admin"  # unknown key → fallback to device owner
