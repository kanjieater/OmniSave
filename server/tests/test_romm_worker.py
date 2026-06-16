"""Tests for romm_worker — outbound consumer for the RomM virtual device."""

import pathlib

import pytest

import database as db
import processing
import romm_meta
import romm_vsc
import romm_worker

TITLE = "0100F2C0115B6000"
ROM_ID = 42
SAVE_BYTES = b"PK\x03\x04" + b"X" * 200
ROMM_DEVICE_ID = "romm:test"
USER = "admin"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_romm(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "")
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)
    # Prevent background auto-match threads from racing with synchronous worker calls in tests.
    monkeypatch.setattr(romm_meta, "try_auto_match_async", lambda *a, **kw: None)


def _setup_romm(monkeypatch, tmp_path, conn=None, username=USER):
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    if conn is not None:
        db.set_user_config(conn, username, "romm_host", "http://romm.local")
        db.set_user_config(conn, username, "romm_api_key", "key")
        db.set_user_config(conn, username, "romm_enabled", "1")
        db.set_user_config(conn, username, "romm_source_id", ROMM_DEVICE_ID)


def _setup_db_for_worker(conn, tmp_path, username=USER):
    """Populate DB state needed for worker tests."""
    db.upsert_virtual_device(conn, ROMM_DEVICE_ID, "RomM", "romm-vsc",
                             client_type="romm", owner_user_id=username)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.sync_romm_catalog_to_device(conn, USER, ROMM_DEVICE_ID)
    conn.commit()


def _ingest_and_get_romm_outbound(conn, tmp_dirs, source_device="AA:BB:CC:DD:EE:FF", owner_user_id=USER):
    """Run ingest_direct from a physical device; return the RomM outbound txn_id."""
    staging, archive = tmp_dirs
    txn_id = processing.ingest_direct(TITLE, source_device, SAVE_BYTES, staging, archive, conn,
                                      owner_user_id=owner_user_id)
    row = conn.execute(
        "SELECT transaction_id, snapshot_path FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (ROMM_DEVICE_ID, TITLE.upper()),
    ).fetchone()
    return txn_id, (row["transaction_id"] if row else None), (row["snapshot_path"] if row else None)


# ── Disabled ──────────────────────────────────────────────────────────────────


def test_run_once_disabled_skips(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    db.set_user_config(conn, USER, "romm_enabled", "0")
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: called.append(a) or ({"id": 1}, None))
    romm_worker.run_once(conn)
    assert not called


def test_run_once_no_host_skips(conn, tmp_path, monkeypatch, tmp_dirs):
    """No user_config → get_romm_users returns [] → immediate return."""
    _setup_db_for_worker(conn, tmp_path)
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: called.append(a) or ({"id": 1}, None))
    romm_worker.run_once(conn)
    assert not called


# ── Happy path ────────────────────────────────────────────────────────────────


def test_run_once_pushes_and_completes(conn, tmp_path, tmp_dirs, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)
    assert outbound_id, "expected outbound transaction for RomM device"

    monkeypatch.setattr(romm_meta, "upload_save", lambda rom_id, data, device_id, **_kw: ({"id": 99}, None))
    romm_worker.run_once(conn)

    # Outbound marked COMPLETED
    txn = db.get_transaction(conn, outbound_id)
    assert txn["state"] == "COMPLETED"

    # Both sync markers written (loop-prevention invariant)
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "outbound")
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "inbound")


def test_run_once_logs_romm_push_event(conn, tmp_path, tmp_dirs, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: ({"id": 77}, None))
    romm_worker.run_once(conn)
    row = conn.execute(
        "SELECT event_type, owner_user_id, device_id FROM events WHERE event_type='ROMM_PUSH'"
    ).fetchone()
    assert row is not None
    assert row["owner_user_id"] == USER
    assert row["device_id"] is not None


def test_run_once_push_failure_logs_event_with_owner(conn, tmp_path, tmp_dirs, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _ingest_and_get_romm_outbound(conn, tmp_dirs)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: (None, "test error"))
    romm_worker.run_once(conn)
    row = conn.execute(
        "SELECT event_type, owner_user_id, device_id FROM events WHERE event_type='ROMM_PUSH_FAILED'"
    ).fetchone()
    assert row is not None
    assert row["owner_user_id"] == USER
    assert row["device_id"] is not None


# ── Upload failure ─────────────────────────────────────────────────────────────


def test_run_once_push_failure_event_includes_size_and_error(conn, tmp_path, tmp_dirs, monkeypatch):
    """ROMM_PUSH_FAILED event message must include archive size (MB) and error string."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _ingest_and_get_romm_outbound(conn, tmp_dirs)
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **_kw: (None, "TimeoutError: timed out"))
    romm_worker.run_once(conn)
    row = conn.execute(
        "SELECT message FROM events WHERE event_type='ROMM_PUSH_FAILED'"
    ).fetchone()
    assert row is not None
    assert "MB" in row["message"]
    assert "TimeoutError" in row["message"]


def test_run_once_upload_failure_leaves_ready(conn, tmp_path, tmp_dirs, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: (None, "test error"))
    romm_worker.run_once(conn)
    txn = db.get_transaction(conn, outbound_id)
    assert txn["state"] == "READY_FOR_RESTORE"
    # No sync markers written
    assert conn.execute("SELECT COUNT(*) FROM romm_save_sync").fetchone()[0] == 0


# ── Crash recovery ─────────────────────────────────────────────────────────────


def test_run_once_heals_missing_inbound_guard(conn, tmp_path, tmp_dirs, monkeypatch):
    """If outbound marker exists but inbound (loop guard) is absent, worker heals it."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    # Simulate crash: outbound marker written, inbound guard NOT written
    db.record_romm_sync(conn, USER, ROM_ID, 55, "outbound", outbound_id)
    conn.commit()
    assert not db.has_romm_sync(conn, USER, ROM_ID, 55, "inbound")

    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: called.append(a) or ({"id": 55}, None))
    romm_worker.run_once(conn)

    # No re-upload (already has outbound marker)
    assert not called
    # Outbound completed
    txn = db.get_transaction(conn, outbound_id)
    assert txn["state"] == "COMPLETED"
    # Loop guard healed
    assert db.has_romm_sync(conn, USER, ROM_ID, 55, "inbound")


# ── Unmapped title ─────────────────────────────────────────────────────────────


def test_run_once_fails_unmapped_title(conn, tmp_path, tmp_dirs, monkeypatch):
    """Outbound for an unmapped title → fail it so it stops retrying every 60s."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    # Remove the title mapping
    db.delete_romm_title_map(conn, USER, TITLE)
    conn.commit()

    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: called.append(a) or ({"id": 1}, None))
    romm_worker.run_once(conn)

    assert not called
    txn = db.get_transaction(conn, outbound_id)
    # Worker fails the outbound, then cleanup supersedes it (title no longer in catalog).
    # SUPERSEDED is correct — the delivery path is gone, not just transiently broken.
    assert txn["state"] in ("FAILED", "SUPERSEDED")


# ── Idempotency ────────────────────────────────────────────────────────────────


def test_run_once_idempotent_on_already_completed(conn, tmp_path, tmp_dirs, monkeypatch):
    """Calling run_once twice does not re-upload."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    upload_calls = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **_kw: upload_calls.append(a) or ({"id": 11}, None))

    romm_worker.run_once(conn)
    romm_worker.run_once(conn)

    assert len(upload_calls) == 1  # only uploaded once


# ── Heartbeat / last_seen ─────────────────────────────────────────────────────


def test_heartbeat_on_successful_upload(conn, tmp_path, tmp_dirs, monkeypatch):
    """Activity signal: upload succeeds → last_seen updated; ping NOT called."""
    from datetime import UTC, datetime

    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _ingest_and_get_romm_outbound(conn, tmp_dirs)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: ({"id": 99}, None))
    ping_calls = []
    monkeypatch.setattr(romm_meta, "ping", lambda *a: ping_calls.append(1) or True)

    before = datetime.now(UTC)
    romm_worker.run_once(conn)

    row = conn.execute(
        "SELECT last_seen FROM devices WHERE device_id=?", (ROMM_DEVICE_ID,)
    ).fetchone()
    last_seen = datetime.fromisoformat(row["last_seen"].replace("Z", "+00:00"))
    assert (last_seen - before).total_seconds() < 120
    assert not ping_calls


def test_heartbeat_ping_fallback_when_idle(conn, tmp_path, monkeypatch):
    """Health signal: no outbound work → ping fires → last_seen updated on success."""
    from datetime import UTC, datetime

    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    monkeypatch.setattr(romm_meta, "ping", lambda *a: True)

    before = datetime.now(UTC)
    romm_worker.run_once(conn)

    row = conn.execute(
        "SELECT last_seen FROM devices WHERE device_id=?", (ROMM_DEVICE_ID,)
    ).fetchone()
    last_seen = datetime.fromisoformat(row["last_seen"].replace("Z", "+00:00"))
    assert (last_seen - before).total_seconds() < 120


def test_no_heartbeat_when_ping_fails(conn, tmp_path, monkeypatch):
    """Health probe failure → last_seen unchanged; cycle completes normally."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    original = conn.execute(
        "SELECT last_seen FROM devices WHERE device_id=?", (ROMM_DEVICE_ID,)
    ).fetchone()["last_seen"]
    monkeypatch.setattr(romm_meta, "ping", lambda *a: False)

    romm_worker.run_once(conn)

    current = conn.execute(
        "SELECT last_seen FROM devices WHERE device_id=?", (ROMM_DEVICE_ID,)
    ).fetchone()["last_seen"]
    assert current == original


# ── Index refresh signal ───────────────────────────────────────────────────────

import romm_index


def test_request_sets_refresh_flag():
    romm_index._REFRESH_REQUESTED.clear()
    romm_index.request_index_refresh()
    assert romm_index._REFRESH_REQUESTED.is_set()
    romm_index._REFRESH_REQUESTED.clear()  # cleanup


def test_maybe_run_index_noop_when_not_requested(monkeypatch):
    romm_index._REFRESH_REQUESTED.clear()
    calls = []
    monkeypatch.setattr(romm_index, "build_title_id_index", lambda: calls.append(1))
    romm_index.maybe_run_index()
    assert not calls


def test_maybe_run_index_coalesces(monkeypatch):
    """Two concurrent requests produce exactly one scan."""
    import time
    calls = []

    def _slow_build():
        calls.append(1)
        time.sleep(0.05)

    monkeypatch.setattr(romm_index, "build_title_id_index", _slow_build)
    romm_index._INDEX_RUNNING.clear()
    romm_index._REFRESH_REQUESTED.clear()

    romm_index.request_index_refresh()
    romm_index.maybe_run_index()   # launches thread, clears flag
    romm_index.request_index_refresh()
    romm_index.maybe_run_index()   # _INDEX_RUNNING set — suppressed
    time.sleep(0.2)
    assert len(calls) == 1


# ── Streaming contract ────────────────────────────────────────────────────────


def test_worker_passes_path_not_bytes_to_upload_save(conn, tmp_path, tmp_dirs, monkeypatch):
    """run_once must pass pathlib.Path to upload_save (not bytes), proving streaming path."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _ingest_and_get_romm_outbound(conn, tmp_dirs)

    upload_args = []
    monkeypatch.setattr(
        romm_meta, "upload_save",
        lambda *a, **kw: upload_args.append(a) or ({"id": 99}, None),
    )
    romm_worker.run_once(conn)

    assert upload_args, "upload_save was not called"
    snapshot_arg = upload_args[0][1]
    assert isinstance(snapshot_arg, pathlib.Path), (
        f"upload_save must receive pathlib.Path, got {type(snapshot_arg)}"
    )


def test_upload_save_streams_correct_content_length(tmp_path, monkeypatch):
    """Content-Length must equal multipart header + file size + multipart footer."""
    import http.client

    file_content = b"PK\x03\x04" + b"X" * 1024
    save_file = tmp_path / "save.zip"
    save_file.write_bytes(file_content)

    captured_headers: dict = {}

    class _FakeResp:
        status = 201
        def read(self): return b'{"id": 7}'

    class _FakeConn:
        def __init__(self, *a, **kw): pass
        def putrequest(self, method, path): pass
        def putheader(self, name, value): captured_headers[name] = value
        def endheaders(self): pass
        def send(self, data): pass
        def getresponse(self): return _FakeResp()
        def close(self): pass

    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "testkey")
    monkeypatch.setattr(http.client, "HTTPConnection", lambda *a, **kw: _FakeConn())

    result, err = romm_meta.upload_save(rom_id=1, snapshot_path=save_file)
    assert result is not None, f"upload failed: {err}"

    boundary = "omnisave-boundary"
    part_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="saveFile"; filename="omnisave-latest.zip"\r\n'
        f"Content-Type: application/zip\r\n\r\n"
    ).encode()
    part_footer = f"\r\n--{boundary}--\r\n".encode()
    expected = len(part_header) + len(file_content) + len(part_footer)

    assert "Content-Length" in captured_headers
    assert int(captured_headers["Content-Length"]) == expected


def test_auto_match_miss_sets_refresh_flag(conn, monkeypatch):
    romm_index._REFRESH_REQUESTED.clear()
    monkeypatch.setattr("romm_meta._effective_host", lambda: "http://fake-romm")
    monkeypatch.setattr("romm_meta._effective_key", lambda: "key")
    monkeypatch.setattr("romm_meta._db_path", ":memory:", raising=False)
    import database
    monkeypatch.setattr(database, "open_db", lambda _: conn)
    monkeypatch.setattr(database, "get_romm_rom_id", lambda *_: None)
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda _: None)

    import romm_meta
    romm_meta.try_auto_match("0100EC9004736000", USER)
    assert romm_index._REFRESH_REQUESTED.is_set()
    romm_index._REFRESH_REQUESTED.clear()


# ── Head stamping ──────────────────────────────────────────────────────────────


def test_run_once_stamps_device_title_head_on_complete(conn, tmp_path, tmp_dirs, monkeypatch):
    """Successful push → device_title_head stamped for the RomM virtual device."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: ({"id": 99}, None))
    romm_worker.run_once(conn)

    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE device_id=? AND title_id=?",
        (ROMM_DEVICE_ID, TITLE.upper()),
    ).fetchone()
    assert row is not None, "device_title_head must be set after romm_worker completes"
    assert row["last_seq"] == 1


# ── Reconciliation ─────────────────────────────────────────────────────────────


def test_reconcile_creates_outbound_for_undelivered_head(conn, tmp_path, tmp_dirs, monkeypatch):
    """Reconciliation queues a new outbound when HEAD exists but delivery is FAILED with no READY_FOR_RESTORE."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    # Simulate exhausted delivery: mark the outbound FAILED
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED' WHERE transaction_id=?",
        (outbound_id,),
    )
    conn.commit()

    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: ({"id": 5}, None))
    monkeypatch.setattr(romm_meta, "ping", lambda *a: True)
    romm_worker.run_once(conn)

    new_outbound = conn.execute(
        "SELECT transaction_id FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND title_id=?"
        " AND state='READY_FOR_RESTORE'",
        (ROMM_DEVICE_ID, TITLE.upper()),
    ).fetchone()
    assert new_outbound is not None, "reconciliation must create a new READY_FOR_RESTORE outbound"
    assert new_outbound["transaction_id"] != outbound_id


# ── Filename passed to upload_save ────────────────────────────────────────────


def test_run_once_passes_game_name_filename(conn, tmp_path, tmp_dirs, monkeypatch):
    """Worker must pass the game name (not the default) as filename to upload_save."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    db.upsert_romm_game_cache(conn, USER, ROM_ID, "Kirby Star Allies", None)
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    captured = {}
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda rom_id, data, device_id, filename="omnisave-latest.zip", **_:
                        captured.update({"filename": filename}) or ({"id": 55}, None))
    romm_worker.run_once(conn)

    assert captured.get("filename") == "Kirby Star Allies.zip"


def test_run_once_filename_skips_user_label(conn, tmp_path, tmp_dirs, monkeypatch):
    """Worker must not use the user's custom display label as the RomM filename."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)
    # Set a custom UI label that should never reach RomM
    db.set_label(conn, "game", TITLE.upper(), "My Custom Label")
    _, outbound_id, _ = _ingest_and_get_romm_outbound(conn, tmp_dirs)

    captured = {}
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda rom_id, data, device_id, filename="omnisave-latest.zip", **_:
                        captured.update({"filename": filename}) or ({"id": 66}, None))
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    romm_worker.run_once(conn)

    assert captured.get("filename") == "omnisave-latest.zip"
    assert "My Custom Label" not in captured.get("filename", "")


# ── Cross-user security ────────────────────────────────────────────────────────

OTHER_USER = "user_b"
OTHER_ROMM_DEVICE = "romm:user_b"


def test_worker_skips_cross_user_outbound(conn, tmp_path, tmp_dirs, monkeypatch):
    """Worker must not process outbounds whose owner_user_id differs from the running username."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)  # sets up romm:test owned by USER

    # Ingest with USER as owner so fanout correctly creates an outbound for romm:test
    staging, archive = tmp_dirs
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=USER)

    # Capture the specific outbound txn_id before patching its owner
    outbound_row = conn.execute(
        "SELECT transaction_id FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=?",
        (ROMM_DEVICE_ID,),
    ).fetchone()
    assert outbound_row, "setup: expected outbound for romm:test"
    outbound_id = outbound_row["transaction_id"]

    # Simulate the bug: forcibly set owner to OTHER_USER on this specific outbound
    conn.execute(
        "UPDATE sync_transactions SET owner_user_id=? WHERE transaction_id=?",
        (OTHER_USER, outbound_id),
    )
    conn.commit()

    upload_calls = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: upload_calls.append(a) or ({"id": 99}, None))
    romm_worker.run_once(conn)

    assert not upload_calls, "upload_save must NOT be called for cross-user outbound"
    # The specific cross-user outbound must be FAILED
    row = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?",
        (outbound_id,),
    ).fetchone()
    assert row["state"] == "FAILED"


def test_fanout_does_not_cross_user_romm_devices(conn, tmp_dirs, monkeypatch):
    """Uploading as user A must not create an outbound for user B's RomM device."""
    staging, archive = tmp_dirs

    # User A (USER / user_a) has a RomM device
    db.upsert_virtual_device(conn, ROMM_DEVICE_ID, "RomM-A", "romm-vsc",
                              client_type="romm", owner_user_id=USER)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.sync_romm_catalog_to_device(conn, USER, ROMM_DEVICE_ID)

    # User B (OTHER_USER / user_b) has a separate RomM device with the SAME title mapped
    db.upsert_virtual_device(conn, OTHER_ROMM_DEVICE, "RomM-B", "romm-vsc",
                              client_type="romm", owner_user_id=OTHER_USER)
    db.upsert_romm_title_map(conn, OTHER_USER, TITLE, ROM_ID + 1)
    db.sync_romm_catalog_to_device(conn, OTHER_USER, OTHER_ROMM_DEVICE)
    conn.commit()

    # Upload as user A (physical Switch; owner_user_id propagates into fanout)
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=USER)

    # User B's RomM device must have NO outbound
    row = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (OTHER_ROMM_DEVICE,),
    ).fetchone()
    assert row[0] == 0, f"User B's RomM device must not receive user A's save"


def test_reconcile_does_not_create_cross_user_outbound(conn, tmp_path, tmp_dirs, monkeypatch):
    """_reconcile_undelivered must not queue user B's save for user A's RomM device.

    Regression: get_romm_undelivered_head_txns previously ignored owner_user_id,
    so an upload by B for a title A also has in romm_title_map would be re-queued
    each cycle even after the worker guard FAILED it.
    """
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)  # romm:test owned by USER, Kirby in catalog

    staging, archive = tmp_dirs
    # OTHER_USER uploads the same title that USER has mapped in RomM
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=OTHER_USER)
    conn.commit()

    upload_calls = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: upload_calls.append(a) or ({"id": 99}, None))
    romm_worker.run_once(conn)

    # Worker must not upload other user's save to user_a's RomM
    assert not upload_calls, "upload_save must NOT be called for cross-user reconcile outbound"

    # No READY_FOR_RESTORE outbound must remain after the cycle
    pending = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (ROMM_DEVICE_ID,),
    ).fetchone()[0]
    assert pending == 0, "cross-user reconcile outbound must not survive the worker cycle"


def test_fanout_does_not_cross_user_physical_switch(conn, tmp_dirs):
    """Uploading as user A must not create an outbound for user B's physical Switch.

    Regression: the cross-user guard previously only applied to client_type='romm'.
    A physical Switch owned by user_a must not receive user_b's saves.
    """
    staging, archive = tmp_dirs

    SWITCH_A = "AA:BB:CC:DD:EE:01"  # owner = USER (user_a)
    SWITCH_B = "AA:BB:CC:DD:EE:02"  # owner = OTHER_USER (user_b) — different user's Switch
    SWITCH_C = "AA:BB:CC:DD:EE:03"  # owner = USER (user_a) — same user, should receive

    # Register physical devices with distinct owners
    conn.execute(
        "INSERT OR IGNORE INTO devices (device_id, display_name, owner_user_id, created_at, last_seen)"
        " VALUES (?,?,?,datetime('now'),datetime('now'))",
        (SWITCH_A, "Switch-A", USER),
    )
    conn.execute(
        "INSERT OR IGNORE INTO devices (device_id, display_name, owner_user_id, created_at, last_seen)"
        " VALUES (?,?,?,datetime('now'),datetime('now'))",
        (SWITCH_B, "Switch-B", OTHER_USER),
    )
    conn.execute(
        "INSERT OR IGNORE INTO devices (device_id, display_name, owner_user_id, created_at, last_seen)"
        " VALUES (?,?,?,datetime('now'),datetime('now'))",
        (SWITCH_C, "Switch-C", USER),
    )
    # Give all three devices the same title in their catalogs
    for dev in (SWITCH_A, SWITCH_B, SWITCH_C):
        conn.execute(
            "INSERT OR IGNORE INTO device_installed_games (device_id, title_id) VALUES (?,?)",
            (dev, TITLE.upper()),
        )
    conn.commit()

    # User A (user_a) uploads from Switch-A
    processing.ingest_direct(TITLE, SWITCH_A, SAVE_BYTES, staging, archive, conn, owner_user_id=USER)

    # Switch-B (OTHER_USER's device) must NOT receive an outbound
    cross_user = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (SWITCH_B,),
    ).fetchone()[0]
    assert cross_user == 0, "USER's save must not fan out to OTHER_USER's physical Switch"

    # Switch-C (same owner) MUST receive an outbound
    same_user = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (SWITCH_C,),
    ).fetchone()[0]
    assert same_user == 1, "USER's save must fan out to USER's other physical Switch"


# ── Catalog registration must not trigger delivery ────────────────────────────


def test_reconcile_does_not_auto_push_on_first_connect(conn, tmp_path, tmp_dirs, monkeypatch):
    """First RomM connection: HEAD exists for a title but no outbound has ever been attempted.
    _reconcile_undelivered must NOT bootstrap delivery — that would dump all existing saves."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)

    staging, archive = tmp_dirs
    # Existing inbound from a physical Switch — arrived before RomM was connected
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=USER)
    # Drain the outbound fanout created by processing so the RomM outbound from
    # fanout doesn't interfere — complete it manually to simulate it already done
    conn.execute(
        "UPDATE sync_transactions SET state='COMPLETED', updated_at=datetime('now')"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (ROMM_DEVICE_ID,),
    )
    conn.commit()

    upload_calls: list = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: upload_calls.append(a) or ({"id": 99}, None))
    # Now delete the completed outbound to simulate "no outbound ever attempted"
    conn.execute("DELETE FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
                 (ROMM_DEVICE_ID,))
    conn.commit()

    romm_worker.run_once(conn)

    assert not upload_calls, "first-connect must not auto-push existing saves"
    pending = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (ROMM_DEVICE_ID,),
    ).fetchone()[0]
    assert pending == 0, "no outbound transactions must be created on first connect"


def test_reconcile_retries_on_failed_outbound(conn, tmp_path, tmp_dirs, monkeypatch):
    """When a previous outbound delivery attempt FAILED, reconcile must retry.

    This is the legitimate retry path: delivery was attempted, failed, and the
    new inbound re-trigger won't fire because HEAD hasn't changed."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)

    staging, archive = tmp_dirs
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=USER)
    # Mark the fanout outbound as FAILED to simulate a failed delivery
    conn.execute(
        "UPDATE sync_transactions SET state='FAILED', updated_at=datetime('now')"
        " WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (ROMM_DEVICE_ID,),
    )
    conn.commit()

    upload_calls: list = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: upload_calls.append(a) or ({"id": 99}, None))
    monkeypatch.setattr(romm_meta, "ping", lambda host: True)

    # Cycle 1: reconcile detects FAILED outbound, queues a new READY_FOR_RESTORE outbound.
    # Cycle 2: worker picks up that new outbound and calls upload_save.
    romm_worker.run_once(conn)
    romm_worker.run_once(conn)

    assert upload_calls, "reconcile must retry upload after FAILED outbound"


def test_new_save_after_romm_connect_creates_outbound(conn, tmp_path, tmp_dirs, monkeypatch):
    """Desired behavior: new save arrives after RomM is connected → exactly one upload.

    Proves the normal delivery path (processing fanout → worker upload) still works
    after removing the bootstrap behavior."""
    _setup_romm(monkeypatch, tmp_path, conn)
    _setup_db_for_worker(conn, tmp_path)

    staging, archive = tmp_dirs
    # New save arrives — processing creates outbound for RomM via catalog fanout
    processing.ingest_direct(TITLE, "AA:BB:CC:DD:EE:FF", SAVE_BYTES, staging, archive, conn,
                             owner_user_id=USER)

    upload_calls: list = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: upload_calls.append(a) or ({"id": 99}, None))
    monkeypatch.setattr(romm_meta, "ping", lambda host: True)

    romm_worker.run_once(conn)

    assert len(upload_calls) == 1, "exactly one upload must be made for the new save"


# ── catalog backstop drift detection ─────────────────────────────────────────


def test_catalog_backstop_seeds_snapshot_on_first_call(conn, tmp_path, monkeypatch):
    """First backstop call seeds the snapshot without requesting a refresh."""
    _setup_romm(monkeypatch, tmp_path, conn)
    import romm_index

    fetch_calls: list = []
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: fetch_calls.append(1) or [{"id": 1}])
    refresh_calls: list = []
    monkeypatch.setattr(romm_index, "request_index_refresh", lambda: refresh_calls.append(1))

    # Clear throttle state so backstop fires immediately
    romm_worker._catalog_check_ts.clear()
    romm_worker._catalog_last_seen.clear()

    romm_worker._reconcile_romm_catalog_backstop(conn, USER)

    assert fetch_calls, "must fetch current ROM IDs"
    assert not refresh_calls, "first call seeds snapshot — must not request refresh"


def test_catalog_backstop_triggers_refresh_on_drift(conn, tmp_path, monkeypatch):
    """When catalog changes between backstop calls, request_index_refresh is called."""
    _setup_romm(monkeypatch, tmp_path, conn)
    import romm_index

    refresh_calls: list = []
    monkeypatch.setattr(romm_index, "request_index_refresh", lambda: refresh_calls.append(1))

    # Seed initial snapshot with ROM id=1
    romm_worker._catalog_check_ts.clear()
    romm_worker._catalog_last_seen.clear()
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": 1}])
    romm_worker._reconcile_romm_catalog_backstop(conn, USER)  # seeds snapshot

    # Force throttle to expire so next call fires immediately
    romm_worker._catalog_check_ts[USER] = 0.0

    # Catalog now has a new ROM (id=2 added)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": 1}, {"id": 2}])
    romm_worker._reconcile_romm_catalog_backstop(conn, USER)

    assert len(refresh_calls) == 1, "drift detected → must call request_index_refresh"


def test_catalog_backstop_throttled(conn, tmp_path, monkeypatch):
    """Backstop is throttled — second call within interval does not re-fetch."""
    _setup_romm(monkeypatch, tmp_path, conn)
    import romm_index

    fetch_calls: list = []
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: fetch_calls.append(1) or [])
    monkeypatch.setattr(romm_index, "request_index_refresh", lambda: None)

    # Set check timestamp to now so throttle is active
    import time
    romm_worker._catalog_check_ts[USER] = time.time()
    romm_worker._catalog_last_seen.clear()

    romm_worker._reconcile_romm_catalog_backstop(conn, USER)

    assert not fetch_calls, "throttled — must not fetch within interval"
