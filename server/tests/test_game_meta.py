"""Tests for game_meta.bulk_game_meta — covers label, RomM, and titledb resolution paths."""

import database as db
import game_meta


TITLE_A = "0100F2C0115B6000"
TITLE_B = "0100EC001DE7E000"
TITLE_C = "01007EF00011E000"


def test_bulk_empty_returns_empty(conn):
    assert game_meta.bulk_game_meta(conn, [], "admin") == {}


def test_bulk_label_overrides_titledb(conn):
    """A custom DB label wins over titledb for display_name."""
    db.set_label(conn, "game", TITLE_A, "My Custom Name")
    result = game_meta.bulk_game_meta(conn, [TITLE_A], "admin")
    assert result[TITLE_A]["display_name"] == "My Custom Name"


def test_bulk_deduplicates_title_ids(conn):
    """Duplicate title_ids in input produce one result entry each."""
    db.set_label(conn, "game", TITLE_A, "Dedup Test")
    result = game_meta.bulk_game_meta(conn, [TITLE_A, TITLE_A, TITLE_B], "admin")
    assert set(result.keys()) == {TITLE_A, TITLE_B}


def test_bulk_romm_cache_provides_name_and_icon(conn):
    """RomM title map + cache supply display_name and icon_url when no label exists."""
    rom_id = 42
    db.upsert_romm_title_map(conn, "admin", TITLE_B, rom_id)
    db.upsert_romm_game_cache(conn, "admin", rom_id, "RomM Game", "https://example.com/icon.png")
    result = game_meta.bulk_game_meta(conn, [TITLE_B], "admin")
    assert result[TITLE_B]["display_name"] == "RomM Game"
    assert result[TITLE_B]["icon_url"] == "https://example.com/icon.png"


def test_bulk_label_takes_priority_over_romm(conn):
    """Label wins over RomM for display_name; RomM icon_url still applies."""
    rom_id = 99
    db.upsert_romm_title_map(conn, "admin", TITLE_C, rom_id)
    db.upsert_romm_game_cache(conn, "admin", rom_id, "RomM Name", "https://example.com/romm.png")
    db.set_label(conn, "game", TITLE_C, "Label Name")
    result = game_meta.bulk_game_meta(conn, [TITLE_C], "admin")
    assert result[TITLE_C]["display_name"] == "Label Name"
    assert result[TITLE_C]["icon_url"] == "https://example.com/romm.png"


def test_bulk_no_username_skips_romm(conn):
    """Empty username skips RomM queries entirely."""
    rom_id = 77
    db.upsert_romm_title_map(conn, "admin", TITLE_A, rom_id)
    db.upsert_romm_game_cache(conn, "admin", rom_id, "Should Not Appear", "https://example.com/x.png")
    result = game_meta.bulk_game_meta(conn, [TITLE_A], "")
    assert result[TITLE_A]["display_name"] != "Should Not Appear"


def test_bulk_romm_title_map_no_cache_falls_to_titledb(conn):
    """RomM title map entry with no cache row falls through to titledb."""
    db.upsert_romm_title_map(conn, "admin", TITLE_B, 55)
    # No cache row inserted
    result = game_meta.bulk_game_meta(conn, [TITLE_B], "admin")
    # Should not crash and display_name comes from titledb (may be None or a string)
    assert TITLE_B in result

def test_bulk_partial_romm_mapping(conn):
    """Only titles with romm_title_map entries get RomM display_name; others fall to titledb."""
    rom_id = 11
    db.upsert_romm_title_map(conn, "admin", TITLE_A, rom_id)
    db.upsert_romm_game_cache(conn, "admin", rom_id, "Only A has RomM", None)
    # TITLE_B has no romm mapping
    result = game_meta.bulk_game_meta(conn, [TITLE_A, TITLE_B], "admin")
    assert result[TITLE_A]["display_name"] == "Only A has RomM"
    # TITLE_B falls through to titledb (may be None or a string, but must exist)
    assert TITLE_B in result
