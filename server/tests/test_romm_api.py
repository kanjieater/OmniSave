"""
RomM Metadata API tests — /api/v1/romm/*
"""

import threading

import pytest
from fastapi.testclient import TestClient

import database as db
import romm_api
import romm_meta
import romm_vsc
from helpers import login_admin, auth_header
from main import app

TITLE_A = "0100F2C0115B6000"
TITLE_A_LOWER = "0100f2c0115b6000"
TITLE_B = "01007EF00011E000"
ROM_ID = 42


@pytest.fixture()
def client(conn, monkeypatch, tmp_path):
    import sync_api
    import sync_deliver_api
    import ui_api

    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    staging.mkdir()
    archive.mkdir()

    sync_api.init(conn, staging, archive)
    sync_deliver_api.init(conn, staging, archive)
    ui_api.init(conn, archive)
    romm_api.init(conn)
    return TestClient(app)


@pytest.fixture()
def token(client):
    return login_admin(client)


def _auth(token):
    return auth_header(token)


# ── Search ────────────────────────────────────────────────────────────────────


def test_search_no_romm_host(client, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "")
    resp = client.get("/api/v1/romm/search?q=Zelda", headers=_auth(token))
    assert resp.status_code == 503


def test_search_returns_results(client, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    monkeypatch.setattr(
        romm_meta,
        "search_roms",
        lambda q, limit=10: [{"id": 1, "name": "Zelda", "icon_url": None}],
    )
    resp = client.get("/api/v1/romm/search?q=Zelda", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1
    assert resp.json()["results"][0]["name"] == "Zelda"


def test_search_missing_query(client, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    resp = client.get("/api/v1/romm/search", headers=_auth(token))
    assert resp.status_code == 400


# ── List mappings ─────────────────────────────────────────────────────────────


def test_list_mappings_empty(client, token):
    resp = client.get("/api/v1/romm/titles", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["mappings"] == []


def test_list_mappings_with_entries(client, conn, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    db.upsert_romm_game_cache(conn, "admin", ROM_ID, "Pokémon Scarlet", "http://icon")

    resp = client.get("/api/v1/romm/titles", headers=_auth(token))
    assert resp.status_code == 200
    mappings = resp.json()["mappings"]
    assert len(mappings) == 1
    assert mappings[0]["title_id"] == TITLE_A
    assert mappings[0]["rom_id"] == ROM_ID
    assert mappings[0]["name"] == "Pokémon Scarlet"


# ── Resolve ───────────────────────────────────────────────────────────────────


def test_resolve_not_mapped_titledb_fallback(client, token, monkeypatch):
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid: "Fallback Game")
    monkeypatch.setattr(titledb, "get_icon_url", lambda tid: None)
    resp = client.get(f"/api/v1/romm/titles/{TITLE_A}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_source"] == "titledb"
    assert data["display_name"] == "Fallback Game"
    assert data["rom_id"] is None


def test_resolve_romm_cached(client, conn, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    db.upsert_romm_game_cache(conn, "admin", ROM_ID, "Pokémon Scarlet", "http://icon")

    resp = client.get(f"/api/v1/romm/titles/{TITLE_A}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_source"] == "romm"
    assert data["display_name"] == "Pokémon Scarlet"
    assert data["rom_id"] == ROM_ID
    assert data["cache_pending"] is False


def test_resolve_cache_pending(client, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    resp = client.get(f"/api/v1/romm/titles/{TITLE_A}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["cache_pending"] is True
    assert resp.json()["rom_id"] == ROM_ID
    assert resp.json()["romm_name"] is None


# ── PUT mapping ───────────────────────────────────────────────────────────────


def test_put_mapping_triggers_background_cache(client, token, monkeypatch):
    called = []
    monkeypatch.setattr(
        romm_meta, "fetch_and_cache", lambda rom_id, c, u: called.append(rom_id)
    )
    resp = client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert ROM_ID in called


def test_put_mapping_syncs_romm_catalog(client, conn, token, monkeypatch):
    """PUT mapping adds the title to device_installed_games for the RomM device."""
    import romm_vsc as _romm_vsc
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    monkeypatch.setattr(_romm_vsc, "push_head_async", lambda tid: None)
    romm_device_id = _romm_vsc.get_user_romm_device_id(conn, "admin")

    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )

    members = db.get_catalog_members(conn, TITLE_A, "other-device")
    assert romm_device_id in members


def test_delete_mapping_removes_from_romm_catalog(client, conn, token, monkeypatch):
    """DELETE mapping removes the title from device_installed_games for the RomM device."""
    import romm_vsc as _romm_vsc
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    monkeypatch.setattr(_romm_vsc, "push_head_async", lambda tid: None)
    romm_device_id = _romm_vsc.get_user_romm_device_id(conn, "admin")

    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    client.delete(f"/api/v1/romm/titles/{TITLE_A}/mapping", headers=_auth(token))

    members = db.get_catalog_members(conn, TITLE_A, "other-device")
    assert romm_device_id not in members


def test_put_mapping_invalid_rom_id(client, token):
    resp = client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": 0},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_put_mapping_triggers_push_head(client, token, monkeypatch):
    push_calls: list[str] = []
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda tid: push_calls.append(tid))
    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    assert TITLE_A in push_calls


# ── DELETE mapping ────────────────────────────────────────────────────────────


def test_delete_mapping_success(client, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    resp = client.delete(f"/api/v1/romm/titles/{TITLE_A}/mapping", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resolve = client.get(f"/api/v1/romm/titles/{TITLE_A}", headers=_auth(token))
    assert resolve.json()["rom_id"] is None


def test_delete_mapping_idempotent(client, token):
    resp = client.delete(f"/api/v1/romm/titles/{TITLE_A}/mapping", headers=_auth(token))
    assert resp.status_code == 200


# ── Cache warm ────────────────────────────────────────────────────────────────


def test_cache_warm(client, token, monkeypatch):
    warmed = []
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    monkeypatch.setattr(romm_meta, "warm_cache", lambda conn, u: warmed.append(True))
    resp = client.post("/api/v1/romm/cache/warm", headers=_auth(token))
    assert resp.status_code == 202
    assert warmed


# ── Case normalization ────────────────────────────────────────────────────────


def test_title_id_case_normalization(client, conn, token, monkeypatch):
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda rom_id, c, u: None)
    # PUT with lowercase
    resp = client.put(
        f"/api/v1/romm/titles/{TITLE_A_LOWER}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    db.upsert_romm_game_cache(conn, "admin", ROM_ID, "Test Game", None)

    # GET with uppercase — must resolve the same mapping
    resp = client.get(f"/api/v1/romm/titles/{TITLE_A}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["rom_id"] == ROM_ID
    assert resp.json()["romm_name"] == "Test Game"

    # DB stores uppercase canonical form
    assert db.get_romm_rom_id(conn, "admin", TITLE_A) == ROM_ID
    assert db.get_romm_rom_id(conn, "admin", TITLE_A_LOWER) == ROM_ID


# ── DB helper edge cases ──────────────────────────────────────────────────────


def test_upsert_romm_game_cache_truncates_long_name(conn):
    long_name = "A" * 600
    db.upsert_romm_game_cache(conn, "admin", 99, long_name, None)
    cached = db.get_romm_game_cache(conn, "admin", 99)
    assert len(cached["name"]) == 512


def test_upsert_romm_game_cache_rejects_long_icon_url(conn):
    long_url = "http://example.com/" + "x" * 2048
    db.upsert_romm_game_cache(conn, "admin", 99, "Name", long_url)
    cached = db.get_romm_game_cache(conn, "admin", 99)
    assert cached["icon_url"] is None


def test_labels_set_and_get(conn):
    db.set_label(conn, "game", TITLE_A, "My Custom Name")
    assert db.get_label(conn, "game", TITLE_A) == "My Custom Name"


def test_labels_delete(conn):
    db.set_label(conn, "game", TITLE_A, "My Custom Name")
    db.delete_label(conn, "game", TITLE_A)
    assert db.get_label(conn, "game", TITLE_A) is None


# ── Auto-match ────────────────────────────────────────────────────────────────


def _auto_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "http://romm.local")
    monkeypatch.setattr(romm_meta, "ROMM_API_KEY", "key")
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")


def test_auto_match_maps_single_result(conn, tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid: "Zelda Tears")
    monkeypatch.setattr(
        romm_meta, "search_roms",
        lambda q, limit=10: [{"id": 7, "name": "Zelda Tears", "icon_url": None}],
    )
    romm_meta.try_auto_match(TITLE_A, "admin")
    assert db.get_romm_rom_id(conn, "admin", TITLE_A) == 7
    assert db.get_romm_game_cache(conn, "admin", 7)["name"] == "Zelda Tears"


def test_auto_match_skips_ambiguous(conn, tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid: "Mario")
    monkeypatch.setattr(
        romm_meta, "search_roms",
        lambda q, limit=10: [
            {"id": 1, "name": "Mario 1", "icon_url": None},
            {"id": 2, "name": "Mario 2", "icon_url": None},
        ],
    )
    romm_meta.try_auto_match(TITLE_A, "admin")
    assert db.get_romm_rom_id(conn, "admin", TITLE_A) is None


def test_auto_match_skips_no_name(conn, tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid: None)
    romm_meta.try_auto_match(TITLE_A, "admin")
    assert db.get_romm_rom_id(conn, "admin", TITLE_A) is None


def test_auto_match_skips_already_mapped(conn, tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)
    db.upsert_romm_title_map(conn, "admin", TITLE_A, 99)
    called = []
    monkeypatch.setattr(romm_meta, "search_roms", lambda q, limit=10: called.append(q) or [])
    romm_meta.try_auto_match(TITLE_A, "admin")
    assert not called


def test_auto_match_skips_no_romm_host(conn, monkeypatch):
    monkeypatch.setattr(romm_meta, "ROMM_HOST", "")
    romm_meta.try_auto_match(TITLE_A, "admin")
    assert db.get_romm_rom_id(conn, "admin", TITLE_A) is None


def test_auto_match_inflight_guard(tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(romm_meta, "_in_flight", {TITLE_A})
    called = []
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid: called.append(tid) or "Game")
    romm_meta.try_auto_match_async(TITLE_A, "admin")
    assert not called


def test_auto_match_exception_swallowed(tmp_path, monkeypatch):
    _auto_setup(monkeypatch, tmp_path)

    def _boom(path):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(db, "open_db", _boom)
    romm_meta.try_auto_match(TITLE_A, "admin")  # must not raise


def test_auto_match_async_fires(tmp_path, monkeypatch):
    monkeypatch.setattr(romm_meta, "_db_path", tmp_path / "test.db")
    fired = threading.Event()
    monkeypatch.setattr(romm_meta, "try_auto_match", lambda tid, u: fired.set())
    romm_meta.try_auto_match_async(TITLE_A, "admin")
    assert fired.wait(timeout=2)
    assert TITLE_A not in romm_meta._in_flight


# ── Auth required ─────────────────────────────────────────────────────────────


def test_romm_endpoints_require_auth(client):
    endpoints = [
        ("GET", "/api/v1/romm/search?q=test"),
        ("GET", "/api/v1/romm/titles"),
        ("GET", f"/api/v1/romm/titles/{TITLE_A}"),
    ]
    for method, path in endpoints:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} expected 401, got {resp.status_code}"


# ── VSC sync controls ─────────────────────────────────────────────────────────


def test_sync_push_returns_202(client, token):
    resp = client.post("/api/v1/romm/sync/push", headers=_auth(token))
    assert resp.status_code == 202
    assert resp.json()["ok"] is True


def test_sync_pull_not_initialized_returns_503(client, token):
    # romm_api.init was called without staging/archive in the fixture
    resp = client.post("/api/v1/romm/sync/pull", headers=_auth(token))
    assert resp.status_code == 503


def test_sync_pull_returns_202(conn, monkeypatch, tmp_path):
    import romm_vsc
    import sync_api
    import sync_deliver_api
    import ui_api

    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    staging.mkdir()
    archive.mkdir()

    sync_api.init(conn, staging, archive)
    sync_deliver_api.init(conn, staging, archive)
    ui_api.init(conn, archive)
    romm_api.init(conn, staging, archive)

    pulled = []
    monkeypatch.setattr(romm_vsc, "pull", lambda s, a: pulled.append(True))

    c = TestClient(app)
    token = login_admin(c)
    resp = c.post("/api/v1/romm/sync/pull", headers=_auth(token))
    assert resp.status_code == 202
    assert resp.json()["ok"] is True


# ── romm_index._base_title_id ─────────────────────────────────────────────────


def test_base_title_id_from_fs_name():
    from romm_index import _base_title_id

    detail = {"fs_name": "Owlboy [0100E570094E8000][v0].xci", "files": []}
    assert _base_title_id(detail) == "0100E570094E8000"


def test_base_title_id_from_files_list():
    from romm_index import _base_title_id

    detail = {"fs_name": "", "files": [{"file_name": "Owlboy [0100E570094E8000][v0].xci"}]}
    assert _base_title_id(detail) == "0100E570094E8000"


def test_base_title_id_ignores_update_ids():
    from romm_index import _base_title_id

    # Update title IDs end in 800, not 000 — should be ignored
    detail = {"fs_name": "Owlboy [0100E570094E8800][v1].xci", "files": []}
    assert _base_title_id(detail) is None


def test_base_title_id_no_bracket_id():
    from romm_index import _base_title_id

    detail = {"fs_name": "Owlboy.xci", "files": []}
    assert _base_title_id(detail) is None


# ── fetch_current_user classification ─────────────────────────────────────────


def _make_http_error(code: int):
    import urllib.error
    import urllib.request
    return urllib.error.HTTPError(url="http://x", code=code, msg="err", hdrs=None, fp=None)  # type: ignore[arg-type]


def test_fetch_current_user_auth_failed_403(monkeypatch):
    monkeypatch.setattr(romm_meta, "_effective_host", lambda: "http://romm.local")
    monkeypatch.setattr(romm_meta, "_effective_key", lambda: "badkey")
    monkeypatch.setattr(romm_meta, "_auth_headers", lambda: {})

    def _fail(*a, **kw):
        raise _make_http_error(403)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _fail)

    user, status, detail = romm_meta.fetch_current_user()
    assert user is None
    assert status == "auth_failed"
    assert "403" in detail


def test_fetch_current_user_network_error(monkeypatch):
    monkeypatch.setattr(romm_meta, "_effective_host", lambda: "http://romm.local")
    monkeypatch.setattr(romm_meta, "_effective_key", lambda: "key")
    monkeypatch.setattr(romm_meta, "_auth_headers", lambda: {})

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")))

    user, status, detail = romm_meta.fetch_current_user()
    assert user is None
    assert status == "network_error"


def test_fetch_current_user_success(monkeypatch):
    import io
    import json as _json
    monkeypatch.setattr(romm_meta, "_effective_host", lambda: "http://romm.local")
    monkeypatch.setattr(romm_meta, "_effective_key", lambda: "key")
    monkeypatch.setattr(romm_meta, "_auth_headers", lambda: {})

    class _FakeResp:
        status = 200
        def read(self): return _json.dumps({"id": 1, "username": "alice"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())

    user, status, detail = romm_meta.fetch_current_user()
    assert user == {"id": 1, "username": "alice"}
    assert status == "ok"
    assert detail == ""


def test_trigger_scan_fires_maybe_run_index(client, monkeypatch):
    """POST /scan must call both request_index_refresh and maybe_run_index."""
    import romm_index as _romm_index
    called = []
    monkeypatch.setattr(_romm_index, "request_index_refresh", lambda: called.append("refresh"))
    monkeypatch.setattr(_romm_index, "maybe_run_index", lambda: called.append("run"))
    token = login_admin(client)
    r = client.post("/api/v1/romm/scan", headers=_auth(token))
    assert r.status_code == 202
    assert called == ["refresh", "run"]


def test_put_mapping_remaps_rom_id_atomically(client, conn, monkeypatch):
    """Re-mapping the same rom_id to a different title_id replaces the old mapping.

    Regression: romm_title_map has UNIQUE(username,rom_id). Before the fix, upserting
    rom_id=X for title_B while title_A→rom_id=X already existed raised IntegrityError
    (silently dropped by INSERT OR REPLACE on the title_id key), leaving the old mapping
    intact and the new one never written."""
    monkeypatch.setattr(romm_meta, "fetch_and_cache", lambda *a, **kw: None)
    monkeypatch.setattr(romm_vsc, "push_head_async", lambda *a: None)

    token = login_admin(client)
    # Map TITLE_A → ROM_ID
    r = client.put(
        f"/api/v1/romm/titles/{TITLE_A}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    assert r.status_code == 200

    # Re-map same ROM_ID to TITLE_B — must succeed and move the mapping
    r = client.put(
        f"/api/v1/romm/titles/{TITLE_B}/mapping",
        json={"rom_id": ROM_ID},
        headers=_auth(token),
    )
    assert r.status_code == 200

    mappings = db.get_romm_title_map(conn, "admin")
    mapped_titles = {m["title_id"] for m in mappings}
    assert TITLE_B.upper() in mapped_titles, "new title must be mapped"
    assert TITLE_A.upper() not in mapped_titles, "old title must be unmapped"
