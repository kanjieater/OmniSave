"""Tests for device activity offset tracking (server-driven backfill)."""

import database as db
from helpers import DEVICE_A, DEVICE_B, pair_device, post_activity_events

_EVT = {
    "event_type": "APPLICATION_STARTED",
    "application_id": "demo-app",
    "profile_id": "user-1",
    "event_timestamp": 1700000000,
    "monotonic_timestamp": 12345,
}


def _get_offset(client, device_id: str, token: str) -> dict:
    return client.get(
        "/api/v1/activity/offset",
        headers={"X-Device-ID": device_id, "Authorization": f"Bearer {token}"},
    )


# ── GET /activity/offset ──────────────────────────────────────────────────────


def test_offset_starts_at_zero(client):
    token = pair_device(client, DEVICE_A)
    r = _get_offset(client, DEVICE_A, token)
    assert r.status_code == 200
    assert r.json() == {"last_offset": 0}


def test_offset_requires_device_auth(client):
    r = client.get(
        "/api/v1/activity/offset",
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 401


def test_offset_unknown_device_returns_zero(client):
    token = pair_device(client, DEVICE_A)
    # DEVICE_B is not paired; pair it so we can auth, then check its offset
    token_b = pair_device(client, DEVICE_B)
    r = _get_offset(client, DEVICE_B, token_b)
    assert r.status_code == 200
    assert r.json()["last_offset"] == 0


# ── POST /activity/events with next_offset ────────────────────────────────────


def test_offset_updated_after_event_post(client):
    token = pair_device(client, DEVICE_A)
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT], "next_offset": 42},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1

    r2 = _get_offset(client, DEVICE_A, token)
    assert r2.json()["last_offset"] == 42


def test_offset_not_updated_when_omitted(client):
    token = pair_device(client, DEVICE_A)
    # Post without next_offset
    post_activity_events(client, DEVICE_A, [_EVT], token=token)
    r = _get_offset(client, DEVICE_A, token)
    assert r.json()["last_offset"] == 0


def test_offset_is_monotonic(client):
    token = pair_device(client, DEVICE_A)

    # First batch: advance to 100
    client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT], "next_offset": 100},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert _get_offset(client, DEVICE_A, token).json()["last_offset"] == 100

    # Retry with lower next_offset (e.g. old client retransmit) — must not regress
    evt2 = {**_EVT, "monotonic_timestamp": 99999}
    client.post(
        "/api/v1/activity/events",
        json={"events": [evt2], "next_offset": 50},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert _get_offset(client, DEVICE_A, token).json()["last_offset"] == 100


def test_offset_advances_across_batches(client):
    token = pair_device(client, DEVICE_A)

    for i, offset in enumerate([10, 20, 30]):
        evt = {**_EVT, "monotonic_timestamp": i}
        client.post(
            "/api/v1/activity/events",
            json={"events": [evt], "next_offset": offset},
            headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
        )

    assert _get_offset(client, DEVICE_A, token).json()["last_offset"] == 30


def test_offset_isolated_per_device(client):
    token_a = pair_device(client, DEVICE_A)
    token_b = pair_device(client, DEVICE_B)

    client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT], "next_offset": 77},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token_a}"},
    )

    assert _get_offset(client, DEVICE_A, token_a).json()["last_offset"] == 77
    assert _get_offset(client, DEVICE_B, token_b).json()["last_offset"] == 0


# ── DB helper ─────────────────────────────────────────────────────────────────


def test_set_activity_offset_monotonic_via_db(conn):
    db.set_activity_offset(conn, "DEVICE_X", 100)
    db.set_activity_offset(conn, "DEVICE_X", 50)   # should not regress
    assert db.get_activity_offset(conn, "DEVICE_X") == 100

    db.set_activity_offset(conn, "DEVICE_X", 200)  # should advance
    assert db.get_activity_offset(conn, "DEVICE_X") == 200


def test_insert_play_events_atomic_with_offset(conn):
    """Events and watermark advance in one transaction via insert_play_events(next_offset=...)."""
    evt = {
        "event_type": "APPLICATION_STARTED",
        "application_id": "ABCDEF1234567890",
        "profile_id": None,
        "event_timestamp": 1700000000,
        "monotonic_timestamp": 1,
    }
    inserted = db.insert_play_events(conn, "DEVICE_X", "admin", [evt], next_offset=99)
    assert inserted == 1
    assert db.get_activity_offset(conn, "DEVICE_X") == 99

    # Idempotent re-insert must not double-count; offset must not regress
    inserted2 = db.insert_play_events(conn, "DEVICE_X", "admin", [evt], next_offset=99)
    assert inserted2 == 0
    assert db.get_activity_offset(conn, "DEVICE_X") == 99


# ── Invalid-event filtering ───────────────────────────────────────────────────


def test_invalid_event_in_batch_drops_bad_accepts_good(client):
    """Bad application_id is dropped; valid events in the same batch are still accepted."""
    token = pair_device(client, DEVICE_A)
    good = {**_EVT, "monotonic_timestamp": 9001}
    bad = {**_EVT, "monotonic_timestamp": 9002, "application_id": "not-valid!!"}
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [good, bad], "next_offset": 55},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    assert r.json()["received"] == 2
    assert _get_offset(client, DEVICE_A, token).json()["last_offset"] == 55


def test_app_event_without_application_id_dropped(client):
    """APPLICATION_STARTED missing application_id is dropped; offset still advances."""
    token = pair_device(client, DEVICE_A)
    bad = {**_EVT, "application_id": None, "monotonic_timestamp": 7777}
    good = {**_EVT, "monotonic_timestamp": 7778}
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [bad, good], "next_offset": 60},
        headers={"X-Device-ID": DEVICE_A, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    assert _get_offset(client, DEVICE_A, token).json()["last_offset"] == 60
