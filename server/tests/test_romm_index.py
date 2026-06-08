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
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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
    assert TITLE_A in push_calls


def test_build_skips_already_mapped_rom(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    db.upsert_romm_title_map(conn, USER, TITLE_A, ROM_ID)

    detail_calls: list[int] = []
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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
        romm_index, "_fetch_switch_rom_ids", lambda: ids_calls.append(True) or []
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
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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
    # RomM ingestion must not write to device tables
    assert not conn.execute("SELECT 1 FROM device_installed_games").fetchone()


def test_build_skips_already_mapped_rom_id(conn, tmp_path, monkeypatch):
    """ROM already in romm_title_map → skip detail fetch (line 105 continue)."""
    _setup(monkeypatch, tmp_path, conn)
    OTHER_TITLE = "0100000000000000"
    _seed_inbound(conn, OTHER_TITLE)  # unmapped title
    db.upsert_romm_title_map(conn, USER, TITLE_A, ROM_ID)  # ROM_ID already mapped to a different title

    detail_calls: list[int] = []
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
    monkeypatch.setattr(romm_index, "_fetch_rom_detail", lambda rid: None)
    romm_index.build_title_id_index()
    assert db.get_romm_rom_id(conn, USER, TITLE_A) is None  # detail failed → no mapping


def test_build_title_not_in_romm(conn, tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, conn)
    _seed_inbound(conn, TITLE_A)
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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
    monkeypatch.setattr(romm_index, "_fetch_switch_rom_ids", lambda: [ROM_ID])
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


# ── _fetch_switch_rom_ids ─────────────────────────────────────────────────────


def _make_resp(body: dict):
    raw = json.dumps(body).encode()
    m = MagicMock()
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    m.read.return_value = raw
    return m


def test_fetch_switch_rom_ids_filters_platform(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    page = {
        "total": 3,
        "items": [
            {"id": 1, "platform_id": 21},
            {"id": 2, "platform_id": 15},
            {"id": 3, "platform_id": 21},
        ],
    }
    with patch("urllib.request.urlopen", return_value=_make_resp(page)):
        result = romm_index._fetch_switch_rom_ids()
    assert result == [1, 3]


def test_fetch_switch_rom_ids_paginates(monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    pages = [
        {"total": 250, "items": [{"id": i, "platform_id": 21} for i in range(200)]},
        {"total": 250, "items": [{"id": i, "platform_id": 21} for i in range(200, 250)]},
    ]
    call_count = {"n": 0}

    def _fake_urlopen(req, timeout=None):
        resp = _make_resp(pages[call_count["n"]])
        call_count["n"] += 1
        return resp

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        result = romm_index._fetch_switch_rom_ids()
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
