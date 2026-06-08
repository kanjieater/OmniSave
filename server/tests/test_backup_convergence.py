"""
Generation-based heartbeat state convergence tests.

Covers: device_backup_updates DB helpers, generation bump in processing,
and sync_generation + backup_updates fields on GET /queue.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, queue_get


SAVE_DATA   = b"save-a-" * 200
SAVE_DATA_B = b"save-b-" * 200
SAVE_DATA_2 = b"save-c-" * 200


# ── DB helper unit tests ──────────────────────────────────────────────────────


def test_push_backup_update_increments_generation(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 1)
    assert db.db_get_sync_generation(conn, DEVICE_A) == 1

    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 2)
    assert db.db_get_sync_generation(conn, DEVICE_A) == 2


def test_generation_is_per_device(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 1)
    assert db.db_get_sync_generation(conn, DEVICE_B) == 0


def test_get_sync_generation_returns_zero_for_unknown_device(conn):
    assert db.db_get_sync_generation(conn, DEVICE_A) == 0


def test_backup_updates_since_returns_latest_per_title(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 5)   # gen=1
    db.db_push_backup_update(conn, DEVICE_A, TITLE_2, 10)  # gen=2
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 7)   # gen=3 — supersedes gen=1

    rows = db.db_get_backup_updates_since(conn, DEVICE_A, 0)
    by_title = {r["title_id"]: r for r in rows}

    assert by_title[TITLE_1.upper()]["snapshot_sequence"] == 7
    assert by_title[TITLE_2.upper()]["snapshot_sequence"] == 10


def test_backup_updates_since_excludes_already_seen(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 5)   # gen=1
    db.db_push_backup_update(conn, DEVICE_A, TITLE_2, 10)  # gen=2

    # Client already at gen=1; should only see TITLE_2
    rows = db.db_get_backup_updates_since(conn, DEVICE_A, 1)
    assert len(rows) == 1
    assert rows[0]["title_id"] == TITLE_2.upper()


def test_backup_updates_since_empty_when_up_to_date(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 5)
    gen = db.db_get_sync_generation(conn, DEVICE_A)
    assert db.db_get_backup_updates_since(conn, DEVICE_A, gen) == []


def test_backup_updates_title_not_returned_if_max_gen_already_seen(conn):
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 3)   # gen=1
    db.db_push_backup_update(conn, DEVICE_A, TITLE_2, 9)   # gen=2
    db.db_push_backup_update(conn, DEVICE_A, TITLE_1, 4)   # gen=3

    # Client at gen=3 — all caught up
    assert db.db_get_backup_updates_since(conn, DEVICE_A, 3) == []

    # Client at gen=2 — only TITLE_1 gen=3 is newer
    rows = db.db_get_backup_updates_since(conn, DEVICE_A, 2)
    assert len(rows) == 1
    assert rows[0]["title_id"] == TITLE_1.upper()
    assert rows[0]["snapshot_sequence"] == 4


# ── Processing integration ────────────────────────────────────────────────────


def test_processing_bumps_generation_after_unique_commit(client, conn):
    assert db.db_get_sync_generation(conn, DEVICE_A) == 0

    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    assert db.db_get_sync_generation(conn, DEVICE_A) == 1
    rows = db.db_get_backup_updates_since(conn, DEVICE_A, 0)
    assert len(rows) == 1
    assert rows[0]["title_id"] == TITLE_1.upper()
    assert rows[0]["snapshot_sequence"] == 1


def test_processing_does_not_bump_generation_for_dedup(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    assert db.db_get_sync_generation(conn, DEVICE_A) == 1

    # Same bytes → dedup; generation must stay at 1
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    assert db.db_get_sync_generation(conn, DEVICE_A) == 1


def test_processing_increments_per_unique_upload(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)
    do_upload(client, DEVICE_A, TITLE_2, SAVE_DATA_2)

    assert db.db_get_sync_generation(conn, DEVICE_A) == 2
    rows = db.db_get_backup_updates_since(conn, DEVICE_A, 0)
    titles = {r["title_id"] for r in rows}
    assert TITLE_1.upper() in titles
    assert TITLE_2.upper() in titles


def test_generation_is_device_scoped_in_processing(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    assert db.db_get_sync_generation(conn, DEVICE_A) == 1
    assert db.db_get_sync_generation(conn, DEVICE_B) == 0


# ── Queue endpoint ────────────────────────────────────────────────────────────


def test_queue_includes_sync_generation_field(client):
    r = queue_get(client, DEVICE_A)
    assert r.status_code == 200
    body = r.json()
    assert "sync_generation" in body
    assert isinstance(body["sync_generation"], int)
    assert "backup_updates" in body
    assert isinstance(body["backup_updates"], list)


def test_queue_backup_updates_empty_when_up_to_date(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    # First poll: client at gen=0, server at gen=1 → gets update
    r1 = queue_get(client, DEVICE_A, params="sync_generation=0")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["sync_generation"] == 1
    assert len(body1["backup_updates"]) == 1
    assert body1["backup_updates"][0]["title_id"] == TITLE_1.upper()
    assert body1["backup_updates"][0]["snapshot_sequence"] == 1

    # Second poll: client now at gen=1 → no updates
    r2 = queue_get(client, DEVICE_A, params="sync_generation=1")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sync_generation"] == 1
    assert body2["backup_updates"] == []


def test_queue_legacy_client_gets_updates_with_default_generation(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    r = queue_get(client, DEVICE_A)
    assert r.status_code == 200
    body = r.json()
    assert body["sync_generation"] == 1
    assert len(body["backup_updates"]) == 1


def test_queue_backup_updates_only_for_requesting_device(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    r = queue_get(client, DEVICE_B, params="sync_generation=0")
    assert r.status_code == 200
    body = r.json()
    # DEVICE_B never uploaded → no backup_updates for DEVICE_B
    assert body["sync_generation"] == 0
    assert body["backup_updates"] == []


def test_queue_backup_updates_entry_has_required_fields(client):
    do_upload(client, DEVICE_A, TITLE_1, SAVE_DATA)

    r = queue_get(client, DEVICE_A, params="sync_generation=0")
    assert r.status_code == 200
    entry = r.json()["backup_updates"][0]
    assert "title_id" in entry
    assert "snapshot_sequence" in entry
    assert "committed_at" in entry
    assert isinstance(entry["snapshot_sequence"], int)
    assert entry["snapshot_sequence"] > 0
