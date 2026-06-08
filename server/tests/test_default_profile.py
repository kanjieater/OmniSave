"""
Default profile per device — server tests.
PUT /api/v1/ui/devices/{device_id}/default-profile

Invariant tested: once a device has profiles, exactly one should be the
default for restore routing. The server exposes a PUT endpoint to set it;
the UI enforces "always one default" by never offering a remove action.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, login_admin, auth_header, pair_device, report_catalog, do_upload, poll_queue

PROFILE_1 = "1000AABBCCDD0001"
PROFILE_2 = "1000AABBCCDD0002"
TITLE_1 = "0100F2C0115B6000"
SAVE_DATA = b"save-data" * 50


def _seed_profiles(conn, device_id: str) -> None:
    db.upsert_known_profile(conn, device_id, PROFILE_1, "Alice")
    db.upsert_known_profile(conn, device_id, PROFILE_2, "Bob")


def _set_default(client, token, device_id, profile_uid):
    return client.put(
        f"/api/v1/ui/devices/{device_id}/default-profile",
        json={"profile_uid": profile_uid},
        headers=auth_header(token),
    )


def _get_device(client, token, device_id):
    r = client.get("/api/v1/ui/devices", headers=auth_header(token))
    assert r.status_code == 200
    devices = r.json()["devices"]
    return next((d for d in devices if d["device_id"] == device_id), None)


# ── Set and read back ──────────────────────────────────────────────────────────


def test_set_default_profile(client, conn):
    """Setting a default profile is reflected in the device listing."""
    pair_device(client, DEVICE_A)
    _seed_profiles(conn, DEVICE_A)
    token = login_admin(client)

    r = _set_default(client, token, DEVICE_A, PROFILE_1)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    device = _get_device(client, token, DEVICE_A)
    assert device is not None
    assert device["default_profile_uid"] == PROFILE_1


def test_change_default_profile(client, conn):
    """Changing the default from one profile to another updates the stored value."""
    pair_device(client, DEVICE_A)
    _seed_profiles(conn, DEVICE_A)
    token = login_admin(client)

    _set_default(client, token, DEVICE_A, PROFILE_1)
    _set_default(client, token, DEVICE_A, PROFILE_2)

    device = _get_device(client, token, DEVICE_A)
    assert device["default_profile_uid"] == PROFILE_2


def test_default_profile_none_initially(client, conn):
    """A freshly registered device with no profiles has no default."""
    pair_device(client, DEVICE_A)
    token = login_admin(client)

    device = _get_device(client, token, DEVICE_A)
    assert device is not None
    assert device["default_profile_uid"] is None


def test_first_profile_auto_becomes_default(client, conn):
    """When the first profile is discovered for a device, it is auto-set as the default."""
    pair_device(client, DEVICE_A)
    token = login_admin(client)

    # No default yet
    device = _get_device(client, token, DEVICE_A)
    assert device["default_profile_uid"] is None

    # Simulate the Switch reporting a profile (as happens in device-config)
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_1, "Alice")

    device = _get_device(client, token, DEVICE_A)
    assert device["default_profile_uid"] == PROFILE_1


def test_second_profile_does_not_override_default(client, conn):
    """Adding a second profile does not replace an existing default."""
    pair_device(client, DEVICE_A)
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_1, "Alice")
    db.upsert_known_profile(conn, DEVICE_A, PROFILE_2, "Bob")

    token = login_admin(client)
    device = _get_device(client, token, DEVICE_A)
    # First profile remains the default; second does not override it
    assert device["default_profile_uid"] == PROFILE_1


def test_set_default_requires_auth(client, conn):
    """Unauthenticated requests are rejected."""
    pair_device(client, DEVICE_A)
    r = client.put(
        f"/api/v1/ui/devices/{DEVICE_A}/default-profile",
        json={"profile_uid": PROFILE_1},
    )
    assert r.status_code in (401, 403)


def test_set_default_unknown_device_returns_404(client, conn):
    """Setting default on a non-existent device returns 404."""
    token = login_admin(client)
    r = _set_default(client, token, "DEADBEEF0000", PROFILE_1)
    assert r.status_code == 404


# ── Delivery routing ───────────────────────────────────────────────────────────


def test_target_profile_uid_reflects_device_default(client, conn):
    """Queue entries carry the target device's default_profile_uid, not the source's user_key."""
    pair_device(client, DEVICE_A)
    pair_device(client, DEVICE_B)
    _seed_profiles(conn, DEVICE_B)
    token = login_admin(client)

    _set_default(client, token, DEVICE_B, PROFILE_1)
    report_catalog(client, DEVICE_B, [TITLE_1])

    # Upload from A with a different source user_key
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA, user_key="FFEEDDCCBBAA9988")

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    # target_profile_uid should be DEVICE_B's default, not the source user_key
    assert pending[0]["target_profile_uid"] == PROFILE_1


def test_target_profile_uid_updates_for_new_outbounds_after_default_change(client, conn):
    """New outbounds after changing device default use the new default; old ones are unaffected."""
    pair_device(client, DEVICE_A)
    pair_device(client, DEVICE_B)
    _seed_profiles(conn, DEVICE_B)
    token = login_admin(client)

    _set_default(client, token, DEVICE_B, PROFILE_1)
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA, user_key="")
    pending_v1 = poll_queue(client, DEVICE_B)
    assert len(pending_v1) == 1
    assert pending_v1[0]["target_profile_uid"] == PROFILE_1

    # Change default THEN upload a new version — new outbound gets PROFILE_2
    _set_default(client, token, DEVICE_B, PROFILE_2)
    do_upload(client, DEVICE_A, TITLE_1, b"save-v2" * 50, user_key="")
    pending_v2 = poll_queue(client, DEVICE_B)
    assert len(pending_v2) == 1
    assert pending_v2[0]["target_profile_uid"] == PROFILE_2
