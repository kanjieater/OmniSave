"""Game display metadata helpers — single source of truth for icon and name resolution.

UI presentation layer only. Not for sync scheduling or retry decisions.

Priority order (both helpers):
  display_name: DB label → RomM cache name → titledb → None
  icon_url:     RomM cache icon → titledb → None
"""

import database as db
import titledb


def game_display_name(conn, title_id: str, username: str) -> str | None:
    row = conn.execute(
        "SELECT label FROM labels WHERE entity_type='game' AND entity_id=?", (title_id,)
    ).fetchone()
    if row:
        return row["label"]
    if username:
        rom_id = db.get_romm_rom_id(conn, username, title_id)
        if rom_id:
            cache = db.get_romm_game_cache(conn, username, rom_id)
            if cache and cache.get("name"):
                return cache["name"]
    return titledb.resolve_game_name(title_id)


def game_icon_url(conn, title_id: str, username: str) -> str | None:
    if username:
        rom_id = db.get_romm_rom_id(conn, username, title_id)
        if rom_id:
            cache = db.get_romm_game_cache(conn, username, rom_id)
            if cache and cache.get("icon_url"):
                return cache["icon_url"]
    return titledb.get_icon_url(title_id)
