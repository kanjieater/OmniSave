"""
Pending consistency: every endpoint must agree on the same count for the same device.

Canonical definition: pending = outbound transaction with state READY_FOR_RESTORE.
No HEAD-derived or client-specific logic may influence pending counts.
"""

import uuid
from datetime import UTC, datetime

import database as db
from helpers import auth_header, get_uid, login_admin

TITLE_1 = "0100F2C0115B6000"
TITLE_2 = "0100EC001DE7E000"
DEVICE_A = "AABBCCDDEEFF"
DEVICE_B = "112233445566"
ROMM_ID = "ROMM000000000001"
ADMIN_USER = "admin"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(conn, user_id: str) -> str:
    """Resolve 'admin' username to its stored UUID; other values pass through."""
    if user_id == ADMIN_USER:
        return get_uid(conn, "admin") or user_id
    return user_id


def _seed_device(conn, device_id: str, user_id: str = ADMIN_USER) -> None:
    uid = _resolve(conn, user_id)
    now = _now()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at, owner_user_id)"
        " VALUES (?, '', '', ?, ?, ?)",
        (device_id, now, now, uid),
    )
    # device_profile_map is NOT consulted by the pending UNION SQL (which uses device_access
    # UNION devices.owner_user_id). This insert only matters for total_devices and legacy queries.
    conn.execute(
        "INSERT OR IGNORE INTO device_profile_map"
        " (device_id, profile_id, user_id, profile_name, created_at)"
        " VALUES (?, ?, ?, '', ?)",
        (device_id, f"seed-{device_id}", uid, now),
    )


# NOTE: duplicates test_ui_api._seed_txn — consider moving to helpers.py if schema diverges
def _seed_outbound(
    conn,
    *,
    title_id: str = TITLE_1,
    target_device_id: str = DEVICE_B,
    state: str = "READY_FOR_RESTORE",
    snapshot_sequence: int = 1,
    owner_user_id: str = ADMIN_USER,
) -> str:
    txn_id = str(uuid.uuid4())
    now = _now()
    uid = _resolve(conn, owner_user_id)
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id, title_id, source_device_id, direction, state,"
        "  snapshot_sequence, target_device_id, owner_user_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (txn_id, title_id, DEVICE_A, "outbound", state,
         snapshot_sequence, target_device_id, uid, now, now),
    )
    return txn_id


def _seed_inbound(
    conn,
    *,
    title_id: str = TITLE_1,
    source_device_id: str = DEVICE_A,
    state: str = "READY_FOR_RESTORE",
    snapshot_sequence: int = 1,
    owner_user_id: str = ADMIN_USER,
) -> str:
    txn_id = str(uuid.uuid4())
    now = _now()
    uid = _resolve(conn, owner_user_id)
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id, title_id, source_device_id, direction, state,"
        "  snapshot_sequence, owner_user_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (txn_id, title_id, source_device_id, "inbound", state,
         snapshot_sequence, uid, now, now),
    )
    return txn_id


# ── RomM: inbound HEAD with no outbound → pending_count must be 0 ──────────────


def test_romm_no_outbound_gives_zero_pending_dashboard(client, conn):
    """RomM device with inbound HEAD but no outbound forked → pending_count=0 on dashboard."""
    token = login_admin(client)
    admin_uid = _resolve(conn, ADMIN_USER)
    _seed_device(conn, DEVICE_A)
    db.upsert_virtual_device(conn, ROMM_ID, "RomM", "romm-vsc",
                              client_type="romm", owner_user_id=admin_uid)
    _seed_inbound(conn, title_id=TITLE_1, snapshot_sequence=1)

    r = client.get("/api/v1/ui/dashboard", headers=auth_header(token))
    assert r.status_code == 200
    romm_entry = next((d for d in r.json()["devices"] if d["device_id"] == ROMM_ID), None)
    assert romm_entry is not None
    assert romm_entry["pending_count"] == 0


def test_romm_no_outbound_gives_zero_pending_devices_list(client, conn):
    """RomM device with inbound HEAD but no outbound forked → pending_count=0 on devices list."""
    token = login_admin(client)
    admin_uid = _resolve(conn, ADMIN_USER)
    _seed_device(conn, DEVICE_A)
    db.upsert_virtual_device(conn, ROMM_ID, "RomM", "romm-vsc",
                              client_type="romm", owner_user_id=admin_uid)
    _seed_inbound(conn, title_id=TITLE_1, snapshot_sequence=1)

    r = client.get("/api/v1/ui/devices", headers=auth_header(token))
    assert r.status_code == 200
    romm_entry = next((d for d in r.json()["devices"] if d["device_id"] == ROMM_ID), None)
    assert romm_entry is not None
    assert romm_entry["pending_count"] == 0


def test_romm_with_outbound_shows_pending(client, conn):
    """RomM device with a READY_FOR_RESTORE outbound forked → pending_count=1."""
    token = login_admin(client)
    admin_uid = _resolve(conn, ADMIN_USER)
    _seed_device(conn, DEVICE_A)
    db.upsert_virtual_device(conn, ROMM_ID, "RomM", "romm-vsc",
                              client_type="romm", owner_user_id=admin_uid)
    _seed_inbound(conn, title_id=TITLE_1, snapshot_sequence=1)
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=ROMM_ID, snapshot_sequence=1)

    r = client.get("/api/v1/ui/devices", headers=auth_header(token))
    assert r.status_code == 200
    romm_entry = next((d for d in r.json()["devices"] if d["device_id"] == ROMM_ID), None)
    assert romm_entry is not None
    assert romm_entry["pending_count"] == 1


# ── Dashboard and devices list must agree per device ───────────────────────────


def test_dashboard_and_devices_list_agree(client, conn):
    """dashboard.devices[D].pending_count == list_devices()[D].pending_count for every device."""
    token = login_admin(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=DEVICE_B, snapshot_sequence=1)
    _seed_outbound(conn, title_id=TITLE_2, target_device_id=DEVICE_B, snapshot_sequence=1)

    dash = {d["device_id"]: d["pending_count"]
            for d in client.get("/api/v1/ui/dashboard", headers=auth_header(token)).json()["devices"]}
    devs = {d["device_id"]: d["pending_count"]
            for d in client.get("/api/v1/ui/devices", headers=auth_header(token)).json()["devices"]}

    for device_id, count in devs.items():
        assert dash.get(device_id, 0) == count, (
            f"pending_count mismatch for {device_id}: dashboard={dash.get(device_id, 0)}, devices={count}"
        )


# ── Device card count matches per-game pending_delivery booleans ───────────────


def test_pending_count_matches_game_detail_boolean(client, conn):
    """devices[D].pending_count == count of games where pending_delivery=True for device D."""
    token = login_admin(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=DEVICE_B, snapshot_sequence=1)
    _seed_outbound(conn, title_id=TITLE_2, target_device_id=DEVICE_B, snapshot_sequence=1)

    devices = {d["device_id"]: d
               for d in client.get("/api/v1/ui/devices", headers=auth_header(token)).json()["devices"]}
    card_count = devices[DEVICE_B]["pending_count"]

    pending_from_game_detail = 0
    for title in (TITLE_1, TITLE_2):
        matrix = {e["device_id"]: e for e in
                  client.get(f"/api/v1/ui/games/{title}", headers=auth_header(token)).json()["device_sync_matrix"]}
        if matrix.get(DEVICE_B, {}).get("pending_delivery"):
            pending_from_game_detail += 1

    assert card_count == pending_from_game_detail


# ── stats.pending_titles uses canonical device scope ──────────────────────


def test_pending_titles_counts_owner_device_outbound(client, conn):
    """stats.pending_titles counts READY_FOR_RESTORE outbounds on user-owned devices."""
    token = login_admin(client)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=DEVICE_B, snapshot_sequence=1)

    r = client.get("/api/v1/ui/dashboard", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["stats"]["pending_titles"] == 1


def test_pending_titles_same_title_two_devices_deduplicates(client, conn):
    """One title pending on two devices → pending_titles deduplicates by title, not device (expected: 1)."""
    token = login_admin(client)
    admin_uid = _resolve(conn, ADMIN_USER)
    _seed_device(conn, DEVICE_A)
    _seed_device(conn, DEVICE_B)
    db.upsert_virtual_device(conn, ROMM_ID, "RomM", "romm-vsc",
                              client_type="romm", owner_user_id=admin_uid)
    # Same title queued for both DEVICE_B and ROMM
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=DEVICE_B, snapshot_sequence=1)
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=ROMM_ID, snapshot_sequence=1)

    r = client.get("/api/v1/ui/dashboard", headers=auth_header(token))
    # pending_titles = COUNT(DISTINCT title_id) — same title on two devices still = 1
    assert r.json()["stats"]["pending_titles"] == 1
    # But per-device pending_count should each be 1
    counts = {d["device_id"]: d["pending_count"] for d in r.json()["devices"]}
    assert counts.get(DEVICE_B, 0) == 1
    assert counts.get(ROMM_ID, 0) == 1


# ── Cross-user isolation ──────────────────────────────────────────────────────


def test_other_user_outbound_not_in_pending(client, conn):
    """Outbound for a device owned by another user is not counted in admin's pending."""
    token = login_admin(client)
    _seed_device(conn, DEVICE_A)
    # DEVICE_B owned by a different user — not in admin's device_access or devices.owner_user_id
    now = _now()
    conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, last_seen, created_at, owner_user_id)"
        " VALUES (?, '', '', ?, ?, ?)",
        (DEVICE_B, now, now, "other_user"),
    )
    _seed_outbound(conn, title_id=TITLE_1, target_device_id=DEVICE_B,
                   owner_user_id="other_user", snapshot_sequence=1)

    r = client.get("/api/v1/ui/dashboard", headers=auth_header(token))
    assert r.status_code == 200
    data = r.json()
    assert data["stats"]["pending_titles"] == 0
    assert all(d["device_id"] != DEVICE_B for d in data["devices"])
