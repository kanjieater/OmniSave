"""Activity event ingestion tests.

Covers: event storage, idempotent resubmission, invalid field rejection,
unauthenticated access, and batch-size cap.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, pair_device, post_activity_events

APP = "0100F2C0115B6000"
_EVT = {
    "event_type": "APPLICATION_STARTED",
    "application_id": APP,
    "profile_id": "user-1",
    "event_timestamp": 1700000000,
    "monotonic_timestamp": 12345,
}


# ── Storage ───────────────────────────────────────────────────────────────────


def test_events_stored(client, conn):
    r = post_activity_events(client, DEVICE_A, [_EVT])
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["received"] == 1
    rows = conn.execute(
        "SELECT * FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "APPLICATION_STARTED"
    assert rows[0]["application_id"] == APP
    assert rows[0]["profile_id"] == "user-1"
    assert rows[0]["event_timestamp"] == 1700000000
    assert rows[0]["monotonic_timestamp"] == 12345


def test_owner_user_id_stamped(client, conn):
    post_activity_events(client, DEVICE_A, [_EVT])
    row = conn.execute(
        "SELECT owner_user_id FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row["owner_user_id"] == "admin"


def test_multiple_events_in_batch(client, conn):
    events = [
        {**_EVT, "event_type": "APPLICATION_STARTED", "monotonic_timestamp": 1},
        {**_EVT, "event_type": "APPLICATION_EXITED", "monotonic_timestamp": 2},
    ]
    r = post_activity_events(client, DEVICE_A, events)
    assert r.status_code == 200
    assert r.json()["accepted"] == 2
    count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 2


def test_profile_only_event_no_application_id(client, conn):
    evt = {
        "event_type": "PROFILE_ACTIVE",
        "profile_id": "user-1",
        "event_timestamp": 1700000001,
        "monotonic_timestamp": 99,
    }
    r = post_activity_events(client, DEVICE_A, [evt])
    assert r.status_code == 200
    row = conn.execute(
        "SELECT application_id FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()
    assert row["application_id"] == ""


def test_separate_devices_isolated(client, conn):
    post_activity_events(client, DEVICE_A, [_EVT])
    post_activity_events(client, DEVICE_B, [{**_EVT, "event_timestamp": 1700000002}])
    a_count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    b_count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=?", (DEVICE_B,)
    ).fetchone()[0]
    assert a_count == 1
    assert b_count == 1


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_duplicate_push_idempotent(client, conn):
    r1 = post_activity_events(client, DEVICE_A, [_EVT])
    r2 = post_activity_events(client, DEVICE_A, [_EVT])
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["accepted"] == 0
    assert r2.json()["received"] == 1
    count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 1


def test_profile_event_dedup(client, conn):
    """PROFILE_ACTIVE events (no application_id) must dedup on resubmission."""
    evt = {
        "event_type": "PROFILE_ACTIVE",
        "profile_id": "user-1",
        "event_timestamp": 1700000005,
        "monotonic_timestamp": 55,
    }
    r1 = post_activity_events(client, DEVICE_A, [evt])
    r2 = post_activity_events(client, DEVICE_A, [evt])
    assert r1.json()["accepted"] == 1
    assert r2.json()["accepted"] == 0
    count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=? AND event_type='PROFILE_ACTIVE'",
        (DEVICE_A,),
    ).fetchone()[0]
    assert count == 1


def test_partial_duplicate_batch(client, conn):
    evt2 = {**_EVT, "event_type": "APPLICATION_EXITED", "monotonic_timestamp": 9999}
    post_activity_events(client, DEVICE_A, [_EVT])
    r = post_activity_events(client, DEVICE_A, [_EVT, evt2])
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    count = conn.execute(
        "SELECT COUNT(*) FROM device_play_events WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 2


# ── Validation ────────────────────────────────────────────────────────────────


def test_invalid_event_type_rejected(client):
    evt = {**_EVT, "event_type": "NOT_A_REAL_TYPE"}
    r = post_activity_events(client, DEVICE_A, [evt])
    assert r.status_code == 422  # Pydantic Literal rejects at parse time
    assert "event_type" in str(r.json()["detail"])


def test_invalid_application_id_dropped(client):
    """Bad application_id is dropped; batch returns 200 with accepted=0."""
    evt = {**_EVT, "application_id": "../../../etc/passwd"}
    r = post_activity_events(client, DEVICE_A, [evt])
    assert r.status_code == 200
    assert r.json()["accepted"] == 0
    assert r.json()["received"] == 1


def test_invalid_profile_id_dropped(client):
    """Bad profile_id is dropped; valid events in the same batch are still accepted."""
    good = {**_EVT, "monotonic_timestamp": 1}
    bad = {**_EVT, "monotonic_timestamp": 2, "profile_id": "bad id with spaces!"}
    r = post_activity_events(client, DEVICE_A, [good, bad])
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    assert r.json()["received"] == 2


def test_non_retail_application_id_dropped(client):
    """Homebrew/system title IDs (non-0100 prefix) are dropped for Switch devices."""
    evt = {**_EVT, "application_id": "053EEFBFD7D71000", "monotonic_timestamp": 999}
    r = post_activity_events(client, DEVICE_A, [evt])
    assert r.status_code == 200
    assert r.json()["accepted"] == 0
    assert r.json()["received"] == 1


def test_application_id_too_long_dropped(client):
    """application_id > 64 chars is dropped; batch succeeds."""
    evt = {**_EVT, "application_id": "a" * 65}
    r = post_activity_events(client, DEVICE_A, [evt])
    assert r.status_code == 200
    assert r.json()["accepted"] == 0


def test_app_event_without_application_id_dropped(client):
    """APPLICATION_STARTED/EXITED/FOCUSED/UNFOCUSED with null application_id are dropped."""
    app_event_types = [
        "APPLICATION_STARTED", "APPLICATION_EXITED",
        "APPLICATION_FOCUSED", "APPLICATION_UNFOCUSED",
    ]
    for et in app_event_types:
        evt = {**_EVT, "event_type": et, "application_id": None, "monotonic_timestamp": ord(et[0])}
        r = post_activity_events(client, DEVICE_A, [evt])
        assert r.status_code == 200, f"{et} should not reject the batch"
        assert r.json()["accepted"] == 0, f"{et} with null application_id should be dropped"


def test_all_event_types_accepted(client, conn):
    types = [
        "APPLICATION_STARTED", "APPLICATION_EXITED",
        "APPLICATION_FOCUSED", "APPLICATION_UNFOCUSED",
        "PROFILE_ACTIVE", "PROFILE_INACTIVE",
    ]
    events = [
        {**_EVT, "event_type": t, "monotonic_timestamp": i}
        for i, t in enumerate(types)
    ]
    r = post_activity_events(client, DEVICE_A, events)
    assert r.status_code == 200
    assert r.json()["accepted"] == len(types)


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_unauthenticated_rejected(client):
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 401


def test_wrong_token_rejected(client):
    pair_device(client, DEVICE_A)
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT]},
        headers={
            "X-Device-ID": DEVICE_A,
            "Authorization": "Bearer sk_device_notavalidtoken",
        },
    )
    assert r.status_code == 401


def test_missing_device_id_rejected(client):
    token = pair_device(client, DEVICE_A)
    r = client.post(
        "/api/v1/activity/events",
        json={"events": [_EVT]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


# ── Batch cap ─────────────────────────────────────────────────────────────────


def test_batch_cap_enforced(client):
    events = [
        {**_EVT, "monotonic_timestamp": i}
        for i in range(501)
    ]
    r = post_activity_events(client, DEVICE_A, events)
    assert r.status_code == 422  # Pydantic Field(max_length=500) rejects at parse time
    assert "500" in str(r.json()["detail"])


def test_batch_at_cap_accepted(client, conn):
    events = [
        {**_EVT, "monotonic_timestamp": i}
        for i in range(500)
    ]
    r = post_activity_events(client, DEVICE_A, events)
    assert r.status_code == 200
    assert r.json()["accepted"] == 500


# ── get_play_events helper ────────────────────────────────────────────────────


def test_get_play_events_by_device(client, conn):
    import database as db
    post_activity_events(client, DEVICE_A, [_EVT])
    rows = db.get_play_events(conn, device_id=DEVICE_A)
    assert len(rows) == 1
    assert rows[0]["device_id"] == DEVICE_A


def test_get_play_events_by_application_id(client, conn):
    import database as db
    post_activity_events(client, DEVICE_A, [_EVT])
    rows = db.get_play_events(conn, application_id=APP)
    assert len(rows) == 1
    rows_none = db.get_play_events(conn, application_id="no-such-app")
    assert rows_none == []


def test_get_play_events_by_owner_user_id(client, conn):
    import database as db
    post_activity_events(client, DEVICE_A, [_EVT])
    rows = db.get_play_events(conn, owner_user_id="admin")
    assert len(rows) == 1
    rows_none = db.get_play_events(conn, owner_user_id="nobody")
    assert rows_none == []


def test_get_play_events_since_filter(client, conn):
    import database as db
    early = {**_EVT, "event_timestamp": 1000, "monotonic_timestamp": 1}
    late = {**_EVT, "event_timestamp": 2000, "monotonic_timestamp": 2}
    post_activity_events(client, DEVICE_A, [early, late])
    rows = db.get_play_events(conn, since=1500)
    assert len(rows) == 1
    assert rows[0]["event_timestamp"] == 2000


def test_get_play_events_no_filters(client, conn):
    import database as db
    post_activity_events(client, DEVICE_A, [_EVT])
    post_activity_events(client, DEVICE_B, [{**_EVT, "event_timestamp": 1700000002}])
    rows = db.get_play_events(conn)
    assert len(rows) == 2


def test_insert_play_events_rolls_back_on_error(conn):
    """ROLLBACK path: a bad event mid-batch leaves no rows committed."""
    import database as db
    from unittest.mock import patch

    good = {**_EVT, "event_timestamp": 9000000001, "monotonic_timestamp": 9001}
    events = [good]

    original_execute = conn.execute

    call_count = [0]

    def patched_execute(sql, params=()):
        if "INSERT OR IGNORE" in sql:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated mid-batch failure")
        return original_execute(sql, params)

    with patch.object(conn, "execute", side_effect=patched_execute):
        try:
            db.insert_play_events(conn, "AABBCC112233", "admin", events)
        except RuntimeError:
            pass

    rows = db.get_play_events(conn, device_id="AABBCC112233")
    assert rows == [], "rolled-back rows must not persist"


def test_set_activity_offset_rolls_back_on_error(conn):
    """Exception during INSERT triggers ROLLBACK — offset must not persist (lines 2547-2549)."""
    from unittest.mock import patch

    original_execute = conn.execute
    call_count = [0]

    def patched(sql, params=()):
        if "INSERT INTO device_activity_offset" in sql:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated insert failure")
        return original_execute(sql, params)

    with patch.object(conn, "execute", side_effect=patched):
        try:
            db.set_activity_offset(conn, "ZZDEVICE01", 99)
        except RuntimeError:
            pass

    assert db.get_activity_offset(conn, "ZZDEVICE01") == 0, "rolled-back offset must not persist"
