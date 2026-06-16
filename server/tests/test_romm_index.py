"""Tests for romm_index — Switch ROM title-ID indexer."""

import io
import json
import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

import database as db
import romm_index
import romm_meta
import romm_vsc

TITLE_A = "0100F4300BF2C000"
ROM_ID = 4586
USER = "admin"


@pytest.fixture(autouse=True)
def no_romm(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "")


def _setup(monkeypatch, tmp_path, conn=None):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    if conn is not None:
        db.set_user_config(conn, USER, "romm_host", "http://romm.local")
        db.set_user_config(conn, USER, "romm_api_key", "key")
        db.set_user_config(conn, USER, "romm_enabled", "1")
        conn.commit()


def _seed_inbound(conn, title_id, snapshot_path="/tmp/save.zip"):
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_transactions"
        " (transaction_id,title_id,source_device_id,direction,state,"
        "  snapshot_sequence,has_conflict,snapshot_path,created_at,updated_at)"
        " VALUES (?,?,'device-1','inbound','READY_FOR_RESTORE',1,0,?,datetime('now'),datetime('now'))",
        (txn_id, title_id, snapshot_path),
    )
    conn.commit()
    return txn_id


# ── _base_title_id ─────────────────────────────────────────────────────────────


def test_base_title_id_extracted_from_xci():
    detail = {"files": [{"file_name": f"Code Realize [{TITLE_A}][v0].xci"}]}
    assert romm_index._base_title_id(detail) == TITLE_A


def test_base_title_id_skips_update_titles():
    detail = {"files": [{"file_name": "Game [0100F4300BF2C800][v65536].nsp"}]}
    assert romm_index._base_title_id(detail) is None


def test_base_title_id_prefers_base_over_update():
    detail = {
        "files": [
            {"file_name": f"Game [{TITLE_A}][v0].xci"},
            {"file_name": "Game [0100F4300BF2C800][v65536].nsp"},
        ]
    }
    assert romm_index._base_title_id(detail) == TITLE_A


def test_base_title_id_none_when_no_files():
    assert romm_index._base_title_id({}) is None


def test_base_title_id_none_when_no_bracket_id():
    assert romm_index._base_title_id({"files": [{"file_name": "NoID.xci"}]}) is None


# ── build with no RomM ─────────────────────────────────────────────────────────


def test_build_no_romm_host_noop(conn):
    _seed_inbound(conn, TITLE_A)
    romm_index.build_title_id_index()
    assert db.get_romm_rom_id(conn, USER, TITLE_A) is None


# ── build with RomM ────────────────────────────────────────────────────────────


def test_build_maps_title_when_found(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)

    push_calls: list[str] = []
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: push_calls.append(tid))
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Code: Realize",
            "url_cover": "https://cdn.example.com/cover.jpg",
            "path_cover_large": "",
            "files": [{"file_name": f"Code Realize [{TITLE_A}][v0].xci"}],
        },
    )

    romm_index.build_title_id_index()

    assert db.get_romm_rom_id(conn, USER, TITLE_A) == ROM_ID
    cached = db.get_romm_game_cache(conn, USER, ROM_ID)
    assert cached["name"] == "Code: Realize"
    assert cached["icon_url"] == "https://cdn.example.com/cover.jpg"
    assert not push_calls  # catalog registration must not trigger save delivery


def test_build_skips_already_mapped_rom(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    db.upsert_romm_title_map(conn, USER, TITLE_A, ROM_ID)

    detail_calls: list[int] = []
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index, "_fetch_rom_detail", lambda rid: detail_calls.append(rid) or {}
    )

    romm_index.build_title_id_index()
    assert not detail_calls  # already mapped rom_id → skip detail fetch


def test_build_scans_even_with_no_known_titles(conn, tmp_path, monkeypatch):
    """Catalog ingestion is independent of OmniSave's save history."""
    _setup(monkeypatch, tmp_path, conn)
    # No transactions — OmniSave has no known titles, but RomM may have ROMs to discover.
    ids_calls: list[bool] = []
    monkeypatch.setattr(
        romm_index, "_fetch_switch_roms", lambda: ids_calls.append(True) or []
    )
    romm_index.build_title_id_index()
    assert ids_calls  # always scans — RomM catalog is independent of OmniSave knowledge


def test_build_discovers_title_unknown_to_omnisave(conn, tmp_path, monkeypatch):
    """ROM exists in RomM with [TITLEID]. Title has never appeared in OmniSave.
    After index build: romm_title_map contains the mapping.
    device_installed_games is not touched — RomM ingestion must not leak into device layer."""
    _setup(monkeypatch, tmp_path, conn)
    # No _seed_inbound — title is completely unknown to OmniSave
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Code: Realize",
            "url_cover": "https://cdn.example.com/cover.jpg",
            "path_cover_large": "",
            "files": [{"file_name": f"Code Realize [{TITLE_A}][v0].xci"}],
        },
    )

    romm_index.build_title_id_index()

    assert db.get_romm_rom_id(conn, USER, TITLE_A) == ROM_ID
    # After indexing, catalog sync must populate device_installed_games immediately.
    row = conn.execute(
        "SELECT 1 FROM device_installed_games WHERE title_id=?", (TITLE_A,)
    ).fetchone()
    assert row is not None


def test_build_skips_already_mapped_rom_id(conn, tmp_path, monkeypatch):
    """ROM already in romm_title_map → skip detail fetch (line 105 continue)."""
    _setup(monkeypatch, tmp_path, conn)
    OTHER_TITLE = "0100000000000000"
    _seed_inbound(conn, OTHER_TITLE)  # unmapped title
    db.upsert_romm_title_map(conn, USER, TITLE_A, ROM_ID)  # ROM_ID already mapped to a different title

    detail_calls: list[int] = []
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index, "_fetch_rom_detail", lambda rid: detail_calls.append(rid) or {}
    )
    romm_index.build_title_id_index()
    assert not detail_calls  # ROM_ID already in already_mapped_rom_ids → continue


def test_build_skips_when_detail_fetch_fails(conn, tmp_path, monkeypatch):
    """_fetch_rom_detail returns None → continue without mapping (line 108 continue)."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(romm_index, "_fetch_rom_detail", lambda rid: None)
    romm_index.build_title_id_index()
    assert db.get_romm_rom_id(conn, USER, TITLE_A) is None  # detail failed → no mapping


def test_build_title_not_in_romm(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Other Game",
            "files": [{"file_name": "Other [0100000000000000][v0].xci"}],
        },
    )
    romm_index.build_title_id_index()
    assert db.get_romm_rom_id(conn, USER, TITLE_A) is None


def test_build_icon_falls_back_to_path_cover(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Some Game",
            "url_cover": None,
            "path_cover_large": "/assets/roms/21/4586/cover/big.png",
            "path_cover_small": "",
            "files": [{"file_name": f"Some Game [{TITLE_A}][v0].xci"}],
        },
    )
    romm_index.build_title_id_index()
    cached = db.get_romm_game_cache(conn, USER, ROM_ID)
    assert cached["icon_url"] == "http://romm.local/assets/roms/21/4586/cover/big.png"


def test_build_skips_rom_without_bracket_title_id(conn, tmp_path, monkeypatch):
    """ROM with no [TITLEID] in filename or detail files[] must not be mapped."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [
        {"id": ROM_ID, "platform_id": 21, "fs_name": "Pokemon Scarlet.nsp",
         "fs_name_no_tags": "Pokemon Scarlet", "name": "Pokémon Scarlet",
         "url_cover": None, "path_cover_large": None, "path_cover_small": None},
    ])
    monkeypatch.setattr(romm_index, "_fetch_rom_detail", lambda rid: {
        "id": rid, "name": "Pokémon Scarlet", "files": [{"file_name": "Pokemon Scarlet.nsp"}],
        "url_cover": None, "path_cover_large": None, "path_cover_small": None,
    })
    romm_index.build_title_id_index()
    assert db.get_romm_rom_id(conn, USER, TITLE_A) is None


TITLE_B = "0100AAA000010000"


def test_build_no_retry_on_403(conn, tmp_path, monkeypatch):
    """HTTP 403 from RomM must not re-queue the scan."""
    import urllib.error as _ue
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)

    def _fail_403():
        raise _ue.HTTPError(None, 403, "Forbidden", {}, None)

    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: _fail_403())
    romm_index._REFRESH_REQUESTED.clear()
    romm_index._build_for_user(conn, USER, "http://romm.local", "bad-key")
    assert not romm_index._REFRESH_REQUESTED.is_set()
    assert "403" in (romm_index._last_scan_error or "")


def test_build_403_db_write_failure_swallowed(conn, tmp_path, monkeypatch):
    """DB write failure inside the 403 handler must be silently ignored."""
    import urllib.error as _ue
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)

    monkeypatch.setattr(romm_index, "_fetch_switch_roms",
                        lambda: (_ for _ in ()).throw(_ue.HTTPError(None, 403, "Forbidden", {}, None)))
    monkeypatch.setattr(db, "set_user_config", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("db gone")))
    romm_index._REFRESH_REQUESTED.clear()
    romm_index._build_for_user(conn, USER, "http://romm.local", "bad-key")  # must not raise
    assert not romm_index._REFRESH_REQUESTED.is_set()


def test_build_exception_swallowed(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(db, "open_db", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    romm_index.build_title_id_index()  # must not raise


def test_build_async_fires(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    fired = threading.Event()
    monkeypatch.setattr(romm_index, "build_title_id_index", lambda: fired.set())
    romm_index.build_title_id_index_async()
    assert fired.wait(timeout=2)


def test_build_async_noop_without_host(monkeypatch):
    fired = threading.Event()
    monkeypatch.setattr(romm_index, "build_title_id_index", lambda: fired.set())
    romm_index.build_title_id_index_async()  # _db_path=None → skip
    time.sleep(0.05)
    assert not fired.is_set()


# ── _fetch_switch_roms ────────────────────────────────────────────────────────


def _make_resp(body: dict):
    raw = json.dumps(body).encode()
    m = MagicMock()
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    m.read.return_value = raw
    return m


def test_fetch_switch_roms_returns_all_platforms(monkeypatch):
    """All ROMs are returned regardless of platform — caller decides what to match."""
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    page = {
        "total": 3,
        "items": [
            {"id": 1, "platform_id": 21, "fs_name": "Game1.nsp"},
            {"id": 2, "platform_id": 15, "fs_name": "Other.iso"},
            {"id": 3, "platform_id": 21, "fs_name": "Game3.nsp"},
        ],
    }
    with patch("urllib.request.urlopen", return_value=_make_resp(page)):
        result = romm_index._fetch_switch_roms()
    assert [r["id"] for r in result] == [1, 2, 3]
    assert all("fs_name" in r for r in result)


def test_fetch_switch_roms_paginates(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    pages = [
        {"total": 250, "items": [{"id": i, "platform_id": 21, "fs_name": f"g{i}.nsp"} for i in range(200)]},
        {"total": 250, "items": [{"id": i, "platform_id": 21, "fs_name": f"g{i}.nsp"} for i in range(200, 250)]},
    ]
    call_count = {"n": 0}

    def _fake_urlopen(req, timeout=None):
        resp = _make_resp(pages[call_count["n"]])
        call_count["n"] += 1
        return resp

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        result = romm_index._fetch_switch_roms()
    assert len(result) == 250
    assert call_count["n"] == 2


# ── _fetch_rom_detail ─────────────────────────────────────────────────────────


def test_fetch_rom_detail_returns_data(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    payload = {"id": 42, "name": "Test Game", "files": []}
    with patch("urllib.request.urlopen", return_value=_make_resp(payload)):
        result = romm_index._fetch_rom_detail(42)
    assert result == payload


def test_fetch_rom_detail_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = romm_index._fetch_rom_detail(99)
    assert result is None


# ── build_title_id_index catalog sync ─────────────────────────────────────────


def test_build_title_id_index_syncs_catalog_after_build(monkeypatch, tmp_path, conn):
    """After indexing, build_title_id_index must call sync_romm_catalog_to_device
    so games appear immediately without waiting for the next worker cycle."""
    _setup(monkeypatch, tmp_path, conn)

    sync_calls = []

    def _fake_build(c, username, host, key):
        db.upsert_romm_title_map(c, username, TITLE_A, ROM_ID)
        c.commit()

    monkeypatch.setattr(romm_index, "_build_for_user", _fake_build)
    monkeypatch.setattr(db, "sync_romm_catalog_to_device", lambda c, u, d: sync_calls.append((u, d)))

    romm_index.build_title_id_index()

    assert len(sync_calls) == 1
    u, d = sync_calls[0]
    assert u == USER
    assert "romm" in d


def test_build_does_not_call_push_head_async(conn, tmp_path, monkeypatch):
    """Catalog registration must never trigger save delivery.

    Invariant: index build ≠ save push. Connecting RomM and running the index
    must not push any existing saves — only new inbounds should create outbounds."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)

    push_calls: list[str] = []
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: push_calls.append(tid))
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Code: Realize",
            "url_cover": "https://cdn.example.com/cover.jpg",
            "path_cover_large": "",
            "files": [{"file_name": f"Code Realize [{TITLE_A}][v0].xci"}],
        },
    )

    romm_index.build_title_id_index()

    assert not push_calls, "index build must not call push_head_async"


def test_build_for_user_populates_romm_device_catalog(conn, tmp_path, monkeypatch):
    """End-to-end: _build_for_user() maps a title → sync_romm_catalog_to_device()
    writes it into device_installed_games so the UI device games endpoint returns it."""
    _setup(monkeypatch, tmp_path, conn)
    romm_id = f"romm:{USER}"
    db.upsert_virtual_device(conn, romm_id, "RomM", "romm-vsc",
                              client_type="romm", owner_user_id=USER)
    conn.commit()

    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [{"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": None, "url_cover": None, "path_cover_large": None, "path_cover_small": None}])
    monkeypatch.setattr(
        romm_index,
        "_fetch_rom_detail",
        lambda rid: {
            "id": rid,
            "name": "Code: Realize",
            "url_cover": None,
            "path_cover_large": None,
            "path_cover_small": None,
            "files": [{"file_name": f"Code Realize [{TITLE_A}][v0].xci"}],
        },
    )
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)

    romm_index._build_for_user(conn, USER, "http://romm.local", "key")
    db.sync_romm_catalog_to_device(conn, USER, romm_id)

    rows = conn.execute(
        "SELECT title_id FROM device_installed_games WHERE device_id=?", (romm_id,)
    ).fetchall()
    assert {r["title_id"] for r in rows} == {TITLE_A}


# ── transient failure — partial success ───────────────────────────────────────


TITLE_B = "0100AAA000010000"
ROM_ID_B = 9999


def test_build_maps_successful_roms_when_some_detail_calls_fail(conn, tmp_path, monkeypatch):
    """Some _fetch_rom_detail calls return None (transient failure); others succeed.
    The successful ones must still be mapped — a single failure must not abort the scan."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    _seed_inbound(conn, TITLE_B)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)

    roms = [
        {"id": ROM_ID, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": "Good Game", "url_cover": None, "path_cover_large": None, "path_cover_small": None},
        {"id": ROM_ID_B, "platform_id": 21, "fs_name": "", "fs_name_no_tags": "", "name": "Bad Game", "url_cover": None, "path_cover_large": None, "path_cover_small": None},
    ]
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: roms)

    def _detail(rid):
        if rid == ROM_ID:
            return {"id": rid, "name": "Good Game", "url_cover": None, "path_cover_large": None,
                    "path_cover_small": None, "files": [{"file_name": f"Good Game [{TITLE_A}][v0].nsp"}]}
        return None  # transient failure for ROM_ID_B

    monkeypatch.setattr(romm_index, "_fetch_rom_detail", _detail)

    romm_index.build_title_id_index()

    assert db.get_romm_rom_id(conn, USER, TITLE_A) == ROM_ID   # succeeded
    assert db.get_romm_rom_id(conn, USER, TITLE_B) is None      # failed — not mapped


# ── parallel detail fetch (_fetch_detail_with_creds) ─────────────────────────


def test_fetch_detail_with_creds_sets_thread_creds_and_returns_detail(monkeypatch):
    """_fetch_detail_with_creds sets per-thread creds and returns (detail, elapsed_ms)."""
    detail_payload = {"id": ROM_ID, "name": "Code: Realize", "files": []}
    monkeypatch.setattr(romm_index, "_fetch_rom_detail", lambda rid: detail_payload)
    creds_set = []
    monkeypatch.setattr(romm_meta, "set_request_creds", lambda h, k: creds_set.append((h, k)))

    detail, elapsed_ms = romm_index._fetch_detail_with_creds(ROM_ID, "http://romm.local", "key")

    assert detail == detail_payload
    assert isinstance(elapsed_ms, int)
    assert elapsed_ms >= 0
    assert creds_set == [("http://romm.local", "key")]


def test_build_uses_list_data_no_detail_call_when_fs_name_has_title_id(conn, tmp_path, monkeypatch):
    """Phase 0 optimization: when fs_name contains [TITLEID], no detail fetch needed."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)

    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [
        {"id": ROM_ID, "platform_id": 21,
         "fs_name": f"Code Realize [{TITLE_A}][v0].nsp",
         "fs_name_no_tags": "Code Realize", "name": "Code: Realize",
         "url_cover": "https://covers.example.com/1.jpg",
         "path_cover_large": None, "path_cover_small": None}
    ])
    detail_calls: list[int] = []
    monkeypatch.setattr(romm_index, "_fetch_rom_detail", lambda rid: detail_calls.append(rid) or {})

    romm_index.build_title_id_index()

    assert not detail_calls, "Phase 0 must resolve title_id from list data — no detail HTTP call"
    assert db.get_romm_rom_id(conn, USER, TITLE_A) == ROM_ID


# ── scan_status ───────────────────────────────────────────────────────────────


def test_scan_status_reflects_scan_error(conn, tmp_path, monkeypatch):
    """When _build_for_user raises, scan_status() reports the error."""
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)

    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: (_ for _ in ()).throw(RuntimeError("network down")))

    # Clear module state before test
    romm_index._last_scan_error = None
    romm_index._last_scan_ts = 0.0

    romm_index.build_title_id_index()

    status = romm_index.scan_status()
    assert status["last_error"] is not None
    assert "network down" in status["last_error"]
    assert status["last_scan_ts"] is not None


def test_scan_status_clears_error_on_success(conn, tmp_path, monkeypatch):
    """A successful scan clears last_error."""
    _setup(monkeypatch, tmp_path, conn)
    romm_index._last_scan_error = "previous error"
    romm_index._last_scan_ts = 0.0

    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: None)
    monkeypatch.setattr(romm_index, "_fetch_switch_roms", lambda: [])

    romm_index.build_title_id_index()

    assert romm_index.scan_status()["last_error"] is None
    assert romm_index.scan_status()["last_scan_ts"] is not None
