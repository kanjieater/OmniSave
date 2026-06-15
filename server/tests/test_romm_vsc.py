"""
RomM Virtual Sync Client tests — push, pull, push_head, ingest_direct, DB helpers.
"""

import uuid

import pytest

import database as db
import processing
import romm_meta
import romm_vsc

TITLE = "0100F2C0115B6000"
ROM_ID = 42
SAVE_BYTES = b"PK\x03\x04" + b"X" * 200  # fake save.zip payload
USER = "admin"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_romm(monkeypatch):
    """Default: RomM not configured — all tests start clean."""
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "")
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)


def _setup_romm(monkeypatch, tmp_path, conn=None, username=USER):
    """Configure RomM per-user in user_config so _load_user_creds succeeds."""
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    if conn is not None:
        db.set_user_config(conn, username, "romm_host", "http://romm.local")
        db.set_user_config(conn, username, "romm_api_key", "key")
        db.set_user_config(conn, username, "romm_enabled", "1")


# ── DB helpers ─────────────────────────────────────────────────────────────────


def test_has_romm_sync_false_when_empty(conn):
    assert db.has_romm_sync(conn, USER, ROM_ID, 1, "inbound") is False


def test_has_romm_sync_true_after_record(conn):
    db.record_romm_sync(conn, USER, ROM_ID, 1, "inbound", "txn-1")
    assert db.has_romm_sync(conn, USER, ROM_ID, 1, "inbound") is True
    assert db.has_romm_sync(conn, USER, ROM_ID, 1, "outbound") is False


def test_record_romm_sync_idempotent(conn):
    db.record_romm_sync(conn, USER, ROM_ID, 1, "outbound", "txn-a")
    db.record_romm_sync(conn, USER, ROM_ID, 1, "outbound", "txn-b")  # INSERT OR IGNORE → no-op
    rows = conn.execute("SELECT * FROM romm_save_sync WHERE rom_id=? AND romm_save_id=1", (ROM_ID,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["transaction_id"] == "txn-a"


def test_create_processing_transaction(conn):
    txn_id, session_id = db.create_processing_transaction(conn, "romm-vsc", TITLE, 500, None)
    txn = db.get_transaction(conn, txn_id)
    sess = db.get_session(conn, session_id)
    assert txn["state"] == "PROCESSING"
    assert txn["source_device_id"] == "romm-vsc"
    assert sess["session_state"] == "COMPLETED"
    assert sess["server_verified_bytes"] == 500


# ── ingest_direct ──────────────────────────────────────────────────────────────


def test_ingest_direct_creates_processing_transaction(conn, tmp_dirs, monkeypatch):
    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_vsc, "push_async", lambda *a: None)
    txn_id = processing.ingest_direct(TITLE, "romm-vsc", SAVE_BYTES, staging, archive, conn)
    # After sync processing, transaction is READY_FOR_RESTORE
    txn = db.get_transaction(conn, txn_id)
    assert txn is not None
    assert txn["state"] == "READY_FOR_RESTORE"


def test_ingest_direct_staging_file_written(conn, tmp_dirs, monkeypatch):
    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_vsc, "push_async", lambda *a: None)

    created = []
    orig = db.create_processing_transaction

    def _capture(*args, **kwargs):
        result = orig(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(db, "create_processing_transaction", _capture)
    processing.ingest_direct(TITLE, "romm-vsc", SAVE_BYTES, staging, archive, conn)
    # After processing, archive file exists at the snapshot_path
    txn_id, _ = created[0]
    archive_txn = db.get_transaction(conn, txn_id)
    assert archive_txn["snapshot_path"] is not None
    import pathlib
    assert pathlib.Path(archive_txn["snapshot_path"]).exists()


def test_ingest_direct_runs_processing(conn, tmp_dirs, monkeypatch):
    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_vsc, "push_async", lambda *a: None)
    txn_id = processing.ingest_direct(TITLE, "romm-vsc", SAVE_BYTES, staging, archive, conn)
    txn = db.get_transaction(conn, txn_id)
    assert txn["sha256"] is not None
    assert txn["snapshot_sequence"] is not None


# ── push ───────────────────────────────────────────────────────────────────────


def test_push_skips_no_romm_host(conn, tmp_path, monkeypatch):
    # No user_config → _load_user_creds returns False → immediate return
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    romm_vsc.push(TITLE, "txn-1", "/nonexistent/archive.zip", USER)
    assert conn.execute("SELECT COUNT(*) FROM romm_save_sync").fetchone()[0] == 0


def test_push_skips_unmapped(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: called.append(a) or ({"id": 1}, None))
    romm_vsc.push(TITLE, "txn-1", "/nonexistent.zip", USER)
    assert not called  # no rom_id mapping → skip


def test_push_uploads_to_romm(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,has_conflict,created_at,updated_at)"
        " VALUES (?,?,'dev-a','inbound','READY_FOR_RESTORE',1,0,datetime('now'),datetime('now'))",
        (txn_id, TITLE),
    )
    conn.commit()
    archive = tmp_path / "archive" / "save.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(SAVE_BYTES)
    monkeypatch.setattr(romm_meta, "upload_save", lambda rom_id, snap, device_id, **_: ({"id": 99}, None))
    romm_vsc.push(TITLE, txn_id, str(archive), USER)
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "outbound")
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "inbound")  # guard against pull-back


def test_push_idempotent(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.record_romm_sync(conn, USER, ROM_ID, 99, "outbound", "txn-push-1")
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: called.append(a) or ({"id": 99}, None))
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    romm_vsc.push(TITLE, "txn-push-1", str(archive), USER)
    assert not called  # already recorded → skip


def test_push_upload_failure_swallowed(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: (None, "upload failed"))
    romm_vsc.push(TITLE, "txn-push-2", str(archive), USER)  # must not raise


def test_push_stamps_device_title_head(conn, tmp_path, monkeypatch):
    """Successful push writes device_title_head so sync-state sees romm device as SYNCED.
    The vsc_device_id written here must match what _romm_head_was_synced/_romm_unsynced_count
    use to query device_title_head — both derive from get_user_romm_device_id."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,has_conflict,created_at,updated_at)"
        " VALUES (?,?,'dev-a','inbound','READY_FOR_RESTORE',7,0,datetime('now'),datetime('now'))",
        (txn_id, TITLE),
    )
    conn.commit()
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: ({"id": 55}, None))
    romm_vsc.push(TITLE, txn_id, str(archive), USER)
    vsc_device_id = romm_vsc.get_user_romm_device_id(conn, USER)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (TITLE.upper(), vsc_device_id),
    ).fetchone()
    assert row is not None, "device_title_head must be written on successful push"
    assert row["last_seq"] == 7


# ── stamp_device_head + record_romm_delivery contract ─────────────────────────


def test_stamp_and_record_stamps_both_tables(conn):
    """Both contract functions together write romm_save_sync + device_title_head."""
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    txn_id = str(uuid.uuid4())

    romm_vsc.stamp_device_head(conn, title_id=TITLE, username=USER, snapshot_sequence=3)
    romm_vsc.record_romm_delivery(conn, username=USER, rom_id=ROM_ID,
                                   romm_save_id=77, transaction_id=txn_id)

    assert db.has_romm_sync(conn, USER, ROM_ID, 77, "outbound")
    assert db.has_romm_sync(conn, USER, ROM_ID, 77, "inbound")
    vsc_id = romm_vsc.get_user_romm_device_id(conn, USER)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (TITLE.upper(), vsc_id),
    ).fetchone()
    assert row is not None
    assert row["last_seq"] == 3


def test_record_romm_delivery_idempotent(conn):
    """Calling record_romm_delivery twice with the same args is a safe no-op."""
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    txn_id = str(uuid.uuid4())

    romm_vsc.record_romm_delivery(conn, username=USER, rom_id=ROM_ID,
                                   romm_save_id=88, transaction_id=txn_id)
    romm_vsc.record_romm_delivery(conn, username=USER, rom_id=ROM_ID,
                                   romm_save_id=88, transaction_id=txn_id)

    n = conn.execute(
        "SELECT COUNT(*) FROM romm_save_sync WHERE username=? AND direction='outbound'", (USER,)
    ).fetchone()[0]
    assert n == 1


def test_stamp_device_head_is_monotonic(conn):
    """device_title_head only advances — a lower seq does not overwrite a higher one."""
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)

    romm_vsc.stamp_device_head(conn, title_id=TITLE, username=USER, snapshot_sequence=5)
    romm_vsc.stamp_device_head(conn, title_id=TITLE, username=USER, snapshot_sequence=3)

    vsc_id = romm_vsc.get_user_romm_device_id(conn, USER)
    row = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (TITLE.upper(), vsc_id),
    ).fetchone()
    assert row["last_seq"] == 5


def test_worker_complete_outbound_after_delivery(conn):
    """Worker path: stamp + record + complete_outbound sets outbound txn to COMPLETED."""
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    vsc_device_id = romm_vsc.get_user_romm_device_id(conn, USER)
    outbound_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,target_device_id,sha256,total_size_bytes,created_at,updated_at)"
        " VALUES (?,?,?,'outbound','READY_FOR_RESTORE',2,?,NULL,10,datetime('now'),datetime('now'))",
        (outbound_id, TITLE, "dev-a", vsc_device_id),
    )

    romm_vsc.stamp_device_head(conn, title_id=TITLE, username=USER, snapshot_sequence=2)
    romm_vsc.record_romm_delivery(conn, username=USER, rom_id=ROM_ID,
                                   romm_save_id=99, transaction_id=outbound_id)
    db.complete_outbound(conn, vsc_device_id, outbound_id)

    outbound = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (outbound_id,)
    ).fetchone()
    assert outbound["state"] == "COMPLETED"


# ── push_head ─────────────────────────────────────────────────────────────────


def _seed_ready_txn(conn, title_id, archive_path):
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,has_conflict,snapshot_path,created_at,updated_at)"
        " VALUES (?,?,'dev-a','inbound','READY_FOR_RESTORE',1,0,?,datetime('now'),datetime('now'))",
        (txn_id, title_id, archive_path),
    )
    conn.commit()
    return txn_id


def test_push_head_skips_no_romm_host(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    romm_vsc.push_head(TITLE, USER)  # no user_config → immediate return


def test_push_head_skips_unmapped(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: called.append(a) or ({"id": 1}, None))
    romm_vsc.push_head(TITLE, USER)  # no mapping → no upload
    assert not called


def test_push_head_pushes_ready_snapshot(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    _seed_ready_txn(conn, TITLE, str(archive))
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    monkeypatch.setattr(romm_meta, "upload_save", lambda rom_id, snap, device_id, **_: ({"id": 55}, None))
    romm_vsc.push_head(TITLE, USER)
    assert db.has_romm_sync(conn, USER, ROM_ID, 55, "outbound")


def test_push_head_noop_when_no_snapshot(conn, tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: called.append(a) or ({"id": 1}, None))
    romm_vsc.push_head(TITLE, USER)  # no READY_FOR_RESTORE snapshot → no upload
    assert not called


def test_push_head_exception_swallowed(tmp_path, monkeypatch):
    _setup_romm(monkeypatch, tmp_path)
    monkeypatch.setattr(db, "open_db", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    romm_vsc.push_head(TITLE, USER)  # must not raise


# ── pull ───────────────────────────────────────────────────────────────────────


def test_pull_skips_no_romm_host(conn, tmp_dirs):
    staging, archive = tmp_dirs
    # ROMM_HOST="" → immediate return
    romm_vsc.pull(staging, archive)
    assert conn.execute("SELECT COUNT(*) FROM romm_save_sync").fetchone()[0] == 0


def test_pull_ingests_new_save(conn, tmp_path, tmp_dirs, monkeypatch):
    """pull() uses list_all_saves_for_rom (no device_id filter) to see all RomM clients."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rid: [{"id": 7, "file_extension": "zip", "file_name": "save.zip"}])
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: SAVE_BYTES)
    romm_vsc.pull(staging, archive)
    assert db.has_romm_sync(conn, USER, ROM_ID, 7, "inbound")


def test_pull_uses_all_saves_not_device_filtered(conn, tmp_path, tmp_dirs, monkeypatch):
    """Verify list_all_saves_for_rom is called (not the device-filtered variant)."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()
    all_saves_called = []
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rid: all_saves_called.append(rid) or [])
    monkeypatch.setattr(romm_meta, "list_saves_for_rom", lambda rid, did: (_ for _ in ()).throw(AssertionError("should not call filtered variant")))
    romm_vsc.pull(staging, archive)
    assert all_saves_called  # called with rom_id, no device_id arg


def test_pull_skips_already_synced(conn, tmp_path, tmp_dirs, monkeypatch):
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    db.record_romm_sync(conn, USER, ROM_ID, 7, "inbound", "existing-txn")
    downloaded = []
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rid: [{"id": 7, "file_extension": "zip", "file_name": "save.zip"}])
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: downloaded.append(sid) or b"")
    romm_vsc.pull(staging, archive)
    assert not downloaded  # already synced → no download


def test_pull_download_failure_skips(conn, tmp_path, tmp_dirs, monkeypatch):
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rid: [{"id": 8, "file_extension": "zip", "file_name": "save.zip"}])
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: None)
    romm_vsc.pull(staging, archive)
    assert not db.has_romm_sync(conn, USER, ROM_ID, 8, "inbound")


def test_pull_skips_when_disabled(conn, tmp_path, tmp_dirs, monkeypatch):
    """romm_enabled='0' in user_config causes pull to skip that user."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.set_user_config(conn, USER, "romm_enabled", "0")
    called = []
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rid: called.append(rid) or [])
    romm_vsc.pull(staging, archive)
    assert not called  # disabled → no API calls


# ── upload_save URL contract ───────────────────────────────────────────────────


def test_upload_save_url_contains_autosave_params(tmp_path, monkeypatch):
    """upload_save must include slot=autosave, autocleanup=true, autocleanup_limit."""
    import http.client

    captured_paths = []

    class _FakeResp:
        status = 201
        def read(self): return b'{"id": 1}'

    class _FakeConn:
        def __init__(self, *a, **kw): pass
        def putrequest(self, method, path): captured_paths.append(path)
        def putheader(self, *a): pass
        def endheaders(self): pass
        def send(self, data): pass
        def getresponse(self): return _FakeResp()
        def close(self): pass

    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "testkey")
    monkeypatch.setattr(http.client, "HTTPConnection", lambda *a, **kw: _FakeConn())

    save_file = tmp_path / "save.zip"
    save_file.write_bytes(SAVE_BYTES)
    result, err = romm_meta.upload_save(rom_id=42, snapshot_path=save_file)

    assert result is not None, f"upload failed: {err}"
    assert captured_paths, "putrequest was not called"
    path = captured_paths[0]
    assert "slot=autosave" in path
    assert "autocleanup=true" in path
    assert "autocleanup_limit=10" in path
    assert "rom_id=42" in path


# ── _load_user_creds disabled path ────────────────────────────────────────────


def test_push_skips_when_user_disabled(conn, tmp_path, monkeypatch):
    """_load_user_creds returns False when romm_enabled='0' → push skips upload."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.set_user_config(conn, USER, "romm_enabled", "0")
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    called = []
    monkeypatch.setattr(romm_meta, "upload_save", lambda *a, **kw: called.append(a) or ({"id": 1}, None))
    romm_vsc.push(TITLE, "txn-disabled", str(archive), USER)
    assert not called  # disabled user → no upload


# ── _romm_filename fallback ───────────────────────────────────────────────────


def test_romm_filename_no_titledb_match(conn, tmp_path, monkeypatch):
    """_romm_filename falls back to omnisave-latest.zip when cache, live fetch, and titledb all fail."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    captured = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda rom_id, snap, device_id, filename="omnisave-latest.zip", **kw:
                        captured.append(filename) or ({"id": 5}, None))
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    romm_vsc.push(TITLE, "txn-fallback", str(archive), USER)
    assert captured == ["omnisave-latest.zip"]


# ── pull: non-zip skip ────────────────────────────────────────────────────────


def test_pull_skips_non_zip_extension(conn, tmp_path, tmp_dirs, monkeypatch):
    """Saves with non-zip file_extension are skipped by the pull loop."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()
    downloaded = []
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom",
                        lambda rid: [{"id": 9, "file_extension": "srm", "file_name": "save.srm"}])
    monkeypatch.setattr(romm_meta, "download_save_content",
                        lambda sid: downloaded.append(sid) or b"")
    romm_vsc.pull(staging, archive)
    assert not downloaded  # non-zip → skipped before download


# ── push_head_async early return + all-users path ─────────────────────────────


def test_push_head_async_no_db_path(monkeypatch):
    """push_head_async returns immediately when _db_path is not set."""
    monkeypatch.setattr(romm_meta, "_db_path", None)
    romm_vsc.push_head_async(TITLE)  # must not raise or spawn thread


def test_push_head_async_calls_all_users(conn, tmp_path, tmp_dirs, monkeypatch):
    """push_head_async runs push_head for every enabled user synchronously via thread."""
    _setup_romm(monkeypatch, tmp_path, conn)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    _seed_ready_txn(conn, TITLE, str(archive))
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)

    pushed = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda *a, **kw: pushed.append(kw.get("filename", "")) or ({"id": 77}, None))
    romm_vsc.push_head_async(TITLE)

    import time as _time
    # Give the daemon thread time to run
    for _ in range(20):
        if pushed:
            break
        _time.sleep(0.05)
    assert pushed  # thread called push_head → upload_save fired


# ── Direct _romm_filename unit tests ─────────────────────────────────────────


def test_romm_filename_fallback_no_name(conn, monkeypatch):
    """_romm_filename returns omnisave-latest.zip when titledb has no entry."""
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    result = romm_vsc._romm_filename(TITLE, conn)
    assert result == "omnisave-latest.zip"


def test_romm_filename_safe_name(conn, monkeypatch):
    """_romm_filename returns safe name with .zip extension."""
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: "Kirby's Dream Buffet")
    result = romm_vsc._romm_filename(TITLE, conn)
    assert result == "Kirby's Dream Buffet.zip"


def test_romm_filename_romm_cache_priority(conn, monkeypatch):
    """RomM game cache name takes priority over titledb."""
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: "Titledb Name")
    db.upsert_romm_game_cache(conn, USER, ROM_ID, "Trip World DX (World) (Limited Run Games)", None)
    result = romm_vsc._romm_filename(TITLE, conn, username=USER, rom_id=ROM_ID)
    assert result == "Trip World DX (World) (Limited Run Games).zip"


def test_romm_filename_romm_cache_empty_falls_back_to_titledb(conn, monkeypatch):
    """Falls back to titledb when RomM cache and live fetch both return nothing."""
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: "Titledb Name")
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)
    result = romm_vsc._romm_filename(TITLE, conn, username=USER, rom_id=ROM_ID)
    assert result == "Titledb Name.zip"


def test_romm_filename_live_fetch_on_cache_miss(conn, monkeypatch):
    """On cache miss, _romm_filename fetches from RomM and uses the returned name."""
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: "Titledb Name")
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata",
                        lambda rid: {"name": "Live RomM Name", "icon_url": None})
    result = romm_vsc._romm_filename(TITLE, conn, username=USER, rom_id=ROM_ID)
    assert result == "Live RomM Name.zip"
    # Result should now be cached
    cached = db.get_romm_game_cache(conn, USER, ROM_ID)
    assert cached and cached["name"] == "Live RomM Name"


def test_romm_filename_skips_user_label(conn, monkeypatch):
    """User's custom display label must never be used as the RomM filename."""
    db.set_label(conn, "game", TITLE.upper(), "My Short Label")
    monkeypatch.setattr(romm_meta, "fetch_rom_metadata", lambda rom_id: None)
    import titledb as _titledb
    # Titledb returns None so we fall back to omnisave-latest, NOT the user label
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    result = romm_vsc._romm_filename(TITLE, conn, username=USER, rom_id=ROM_ID)
    assert result == "omnisave-latest.zip"
    assert "My Short Label" not in result


def test_romm_push_uses_romm_cache_name(conn, tmp_path, monkeypatch):
    """push() uses the RomM cached name, not omnisave-latest, when cache is populated."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.upsert_romm_game_cache(conn, USER, ROM_ID, "Black-Matrix 00 (Japan) (Disc 1)", None)
    archive = tmp_path / "save.zip"
    archive.write_bytes(SAVE_BYTES)
    captured = []
    monkeypatch.setattr(romm_meta, "upload_save",
                        lambda rom_id, snap, device_id, filename="omnisave-latest.zip", **kw:
                        captured.append(filename) or ({"id": 42}, None))
    import titledb as _titledb
    monkeypatch.setattr(_titledb, "resolve_game_name", lambda tid, conn=None: None)
    romm_vsc.push(TITLE, "txn-cache-name", str(archive), USER)
    assert captured == ["Black-Matrix 00 (Japan) (Disc 1).zip"]


# ── Exception paths in _pull_for_user and _push_head_all_users ───────────────


def test_pull_for_user_exception_swallowed(conn, tmp_path, tmp_dirs, monkeypatch):
    """Exceptions inside _pull_for_user are caught and logged, never raised."""
    _setup_romm(monkeypatch, tmp_path, conn)
    staging, archive = tmp_dirs

    # Force an exception mid-execution
    monkeypatch.setattr(db, "get_romm_title_map",
                        lambda c: (_ for _ in ()).throw(RuntimeError("db exploded")))
    romm_vsc._pull_for_user(staging, archive, USER)  # must not raise


def test_push_head_all_users_exception_swallowed(conn, tmp_path, monkeypatch):
    """Exceptions inside _push_head_all_users are caught and logged, never raised."""
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    monkeypatch.setattr(db, "open_db",
                        lambda path: (_ for _ in ()).throw(RuntimeError("open failed")))
    romm_vsc._push_head_all_users(TITLE)  # must not raise


# ── start_pull_loop thread start ──────────────────────────────────────────────


def test_start_pull_loop_spawns_thread(tmp_dirs, monkeypatch):
    """start_pull_loop creates a daemon thread without raising."""
    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_meta, "_db_path", None)
    romm_vsc.start_pull_loop(staging, archive, interval_sec=999999)  # long interval


# ── Isolation guard tests ──────────────────────────────────────────────────────


def test_cross_user_title_map_isolation(conn):
    """User A and B can map the same title to different rom_ids without conflict."""
    db.upsert_romm_title_map(conn, "user_a", TITLE, 1)
    db.upsert_romm_title_map(conn, "user_b", TITLE, 2)
    # Point lookups are strictly scoped
    assert db.get_romm_rom_id(conn, "user_a", TITLE) == 1
    assert db.get_romm_rom_id(conn, "user_b", TITLE) == 2
    # List view is strictly scoped — build title→rom_id dict for safe assertion
    a_roms = {r["title_id"]: r["rom_id"] for r in db.get_romm_title_map(conn, "user_a")}
    b_roms = {r["title_id"]: r["rom_id"] for r in db.get_romm_title_map(conn, "user_b")}
    assert a_roms.get(TITLE) == 1      # user_a sees their own mapping
    assert a_roms.get(TITLE) != 2      # user_a does NOT see user_b's rom_id
    assert b_roms.get(TITLE) == 2      # user_b sees their own mapping
    assert b_roms.get(TITLE) != 1      # user_b does NOT see user_a's rom_id


def test_cross_user_save_sync_isolation(conn):
    """User A's loop-prevention record does not affect User B's pull."""
    db.record_romm_sync(conn, "user_a", ROM_ID, 7, "inbound", "txn-a")
    assert db.has_romm_sync(conn, "user_a", ROM_ID, 7, "inbound") is True
    assert db.has_romm_sync(conn, "user_b", ROM_ID, 7, "inbound") is False


def test_cross_user_game_cache_isolation(conn):
    """User A and B get separate game cache entries for the same rom_id."""
    db.upsert_romm_game_cache(conn, "user_a", ROM_ID, "Game A", "http://icon-a")
    db.upsert_romm_game_cache(conn, "user_b", ROM_ID, "Game B", "http://icon-b")
    cache_a = db.get_romm_game_cache(conn, "user_a", ROM_ID)
    cache_b = db.get_romm_game_cache(conn, "user_b", ROM_ID)
    assert cache_a["name"] == "Game A"
    assert cache_b["name"] == "Game B"


# ── romm_meta.ping ─────────────────────────────────────────────────────────────

import urllib.request as _urllib_request


def test_ping_success(monkeypatch):
    class _R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass

    monkeypatch.setattr(_urllib_request, "urlopen", lambda req, timeout=None: _R())
    assert romm_meta.ping("http://romm.local") is True


def test_ping_fails_on_exception(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(_urllib_request, "urlopen", _raise)
    assert romm_meta.ping("http://romm.local") is False


def test_ping_empty_host():
    assert romm_meta.ping("") is False


# ── list_all_saves_for_rom response-format handling ────────────────────────────


def _fake_urlopen(body: bytes):
    import io

    class _Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    return lambda req, timeout=None: _Resp()


def test_list_all_saves_for_rom_flat_list(monkeypatch):
    """Old RomM: /api/saves returns a flat JSON array."""
    import urllib.request as _ur

    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    body = b'[{"id": 7, "file_extension": "zip"}]'
    monkeypatch.setattr(_ur, "urlopen", _fake_urlopen(body))
    result = romm_meta.list_all_saves_for_rom(ROM_ID)
    assert result == [{"id": 7, "file_extension": "zip"}]


def test_list_all_saves_for_rom_paginated_dict(monkeypatch):
    """RomM 4.9+: /api/saves returns {"items": [...], "total": N}.
    Before the fix, iterating the dict's string keys caused TypeError and silently
    aborted the pull loop for all titles."""
    import urllib.request as _ur

    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    body = b'{"items": [{"id": 7, "file_extension": "zip"}], "total": 1}'
    monkeypatch.setattr(_ur, "urlopen", _fake_urlopen(body))
    result = romm_meta.list_all_saves_for_rom(ROM_ID)
    assert result == [{"id": 7, "file_extension": "zip"}]


def test_list_all_saves_for_rom_paginated_empty(monkeypatch):
    """RomM 4.9+ empty: {"items": [], "total": 0} must return [] without error."""
    import urllib.request as _ur

    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    body = b'{"items": [], "total": 0}'
    monkeypatch.setattr(_ur, "urlopen", _fake_urlopen(body))
    result = romm_meta.list_all_saves_for_rom(ROM_ID)
    assert result == []


def test_pull_ingests_cross_instance_save(conn, tmp_path, tmp_dirs, monkeypatch):
    """Save uploaded by dev OmniSave (different device, fresh romm_save_id) is ingested
    by prod's pull loop. Prod DB has no prior record of this save_id — it must NOT be
    blocked by any loop guard from a different instance."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()
    # Prod DB has never seen save_id=99 — simulates save uploaded by dev OmniSave
    assert not db.has_romm_sync(conn, USER, ROM_ID, 99, "inbound")
    monkeypatch.setattr(
        romm_meta,
        "list_all_saves_for_rom",
        lambda rid: [{"id": 99, "file_extension": "zip", "file_name": "game.zip"}],
    )
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: SAVE_BYTES)
    romm_vsc.pull(staging, archive)
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "inbound"), (
        "prod must ingest save uploaded by dev instance"
    )


def test_pull_loop_runs_immediately_on_startup(tmp_dirs, monkeypatch):
    """start_pull_loop fires pull() before the first sleep, not after.
    Before the fix the loop slept 15 min first — saves available at startup were
    invisible until the first poll completed."""
    import threading as _threading

    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_meta, "_db_path", None)  # pull is a no-op without db_path
    pulled = _threading.Event()
    monkeypatch.setattr(romm_vsc, "pull", lambda s, a: pulled.set())
    romm_vsc.start_pull_loop(staging, archive, interval_sec=9999)
    assert pulled.wait(timeout=2), "pull() must be called immediately at loop startup"


# ── pull_initialized — first-encounter baseline ───────────────────────────────


def test_pull_first_encounter_baselines_not_ingests(conn, tmp_path, tmp_dirs, monkeypatch):
    """First pull for a ROM (pull_initialized=0): mark existing saves as seen, do NOT ingest.

    Invariant: saves that existed in RomM before OmniSave connected must not be
    delivered to Switch clients. Only saves that arrive AFTER baseline are synced."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    conn.commit()

    staging, archive = tmp_dirs
    monkeypatch.setattr(
        romm_meta,
        "list_all_saves_for_rom",
        lambda rom_id: [{"id": 42, "file_extension": "zip", "file_name": "save.zip"}],
    )
    download_calls: list = []
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: download_calls.append(sid) or SAVE_BYTES)

    romm_vsc._pull_for_user(staging, archive, USER)

    assert not download_calls, "first encounter must not download saves"
    txns = conn.execute("SELECT COUNT(*) FROM sync_transactions WHERE direction='inbound'").fetchone()[0]
    assert txns == 0, "first encounter must not create inbound transactions"
    assert db.has_romm_sync(conn, USER, ROM_ID, 42, "inbound"), "existing save must be marked as seen"
    row = conn.execute(
        "SELECT pull_initialized FROM romm_title_map WHERE username=? AND rom_id=?", (USER, ROM_ID)
    ).fetchone()
    assert row["pull_initialized"] == 1, "pull_initialized must advance to 1 after baseline"


def test_pull_zero_saves_first_encounter_advances_state(conn, tmp_path, tmp_dirs, monkeypatch):
    """First pull with zero saves must still advance pull_initialized to 1.

    Prevents the edge case where a ROM starts empty → first real save gets
    baselined instead of ingested because first_encounter never clears."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    conn.commit()

    staging, archive = tmp_dirs
    monkeypatch.setattr(romm_meta, "list_all_saves_for_rom", lambda rom_id: [])

    romm_vsc._pull_for_user(staging, archive, USER)

    row = conn.execute(
        "SELECT pull_initialized FROM romm_title_map WHERE username=? AND rom_id=?", (USER, ROM_ID)
    ).fetchone()
    assert row["pull_initialized"] == 1, "pull_initialized must advance even when ROM has zero saves"


def test_pull_first_encounter_skips_non_zip_in_baseline(conn, tmp_path, tmp_dirs, monkeypatch):
    """Non-zip saves are NOT baselined — only ZIP saves establish the seen-record."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    conn.commit()

    monkeypatch.setattr(
        romm_meta,
        "list_all_saves_for_rom",
        lambda rid: [
            {"id": 1, "file_extension": "srm", "file_name": "game.srm"},
            {"id": 2, "file_extension": "zip", "file_name": "save.zip"},
        ],
    )
    romm_vsc._pull_for_user(staging, archive, USER)

    assert not db.has_romm_sync(conn, USER, ROM_ID, 1, "inbound"), "non-zip must NOT be baselined"
    assert db.has_romm_sync(conn, USER, ROM_ID, 2, "inbound"), "zip save must be baselined"
    row = conn.execute(
        "SELECT pull_initialized FROM romm_title_map WHERE username=? AND rom_id=?", (USER, ROM_ID)
    ).fetchone()
    assert row["pull_initialized"] == 1


def test_pull_established_ingests_all_new_saves(conn, tmp_path, tmp_dirs, monkeypatch):
    """Established path ingests ALL saves that appeared after baseline, not just the latest.

    Saves uploaded by multiple clients between pull cycles must all be delivered
    so conflict resolution can pick the right HEAD."""
    staging, archive = tmp_dirs
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)
    conn.commit()

    monkeypatch.setattr(
        romm_meta,
        "list_all_saves_for_rom",
        lambda rid: [
            {"id": 3, "file_extension": "zip", "file_name": "s3.zip"},
            {"id": 7, "file_extension": "zip", "file_name": "s7.zip"},
        ],
    )
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: SAVE_BYTES)

    romm_vsc._pull_for_user(staging, archive, USER)

    txns = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='inbound'"
    ).fetchone()[0]
    assert txns == 2, "all post-baseline saves must be ingested"
    assert db.has_romm_sync(conn, USER, ROM_ID, 3, "inbound")
    assert db.has_romm_sync(conn, USER, ROM_ID, 7, "inbound")


def test_pull_established_ingests_new_save(conn, tmp_path, tmp_dirs, monkeypatch):
    """After baseline (pull_initialized=1), new save → ingest; existing seen save → skip."""
    _setup_romm(monkeypatch, tmp_path, conn)
    db.upsert_romm_title_map(conn, USER, TITLE, ROM_ID)
    db.mark_romm_pull_initialized(conn, USER, ROM_ID)  # already initialized
    db.record_romm_sync(conn, USER, ROM_ID, 42, "inbound", None)  # save 42 already seen
    db.upsert_virtual_device(conn, "romm:admin", "RomM", "romm-vsc", client_type="romm", owner_user_id=USER)
    db.set_user_config(conn, USER, "romm_source_id", "romm:admin")
    conn.commit()

    staging, archive = tmp_dirs
    monkeypatch.setattr(
        romm_meta,
        "list_all_saves_for_rom",
        lambda rom_id: [
            {"id": 42, "file_extension": "zip", "file_name": "save.zip"},  # already seen
            {"id": 99, "file_extension": "zip", "file_name": "save.zip"},  # new
        ],
    )
    monkeypatch.setattr(romm_meta, "download_save_content", lambda sid: SAVE_BYTES)

    romm_vsc._pull_for_user(staging, archive, USER)

    txns = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='inbound'"
    ).fetchone()[0]
    assert txns == 1, "only the new save (id=99) must be ingested"
    assert db.has_romm_sync(conn, USER, ROM_ID, 99, "inbound"), "new save must be recorded"
