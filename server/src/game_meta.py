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

def bulk_game_meta(conn, title_ids: list[str], username: str) -> dict[str, dict]:
    """Fetch display_name and icon_url for multiple title_ids in 3 queries instead of 2N."""
    if not title_ids:
        return {}

    ids = list(dict.fromkeys(title_ids))  # deduplicate, preserve order
    result: dict[str, dict] = {tid: {"display_name": None, "icon_url": None} for tid in ids}

    # 1. Custom labels (single IN query)
    placeholders = ",".join("?" * len(ids))
    for row in conn.execute(
        f"SELECT entity_id, label FROM labels WHERE entity_type='game' AND entity_id IN ({placeholders})",
        ids,
    ).fetchall():
        result[row["entity_id"]]["display_name"] = row["label"]

    # 2. RomM: title→rom_id then rom→cache (two IN queries)
    if username:
        upper_ids = [tid.upper() for tid in ids]
        map_rows = conn.execute(
            f"SELECT title_id, rom_id FROM romm_title_map WHERE username=? AND title_id IN ({placeholders})",
            [username, *upper_ids],
        ).fetchall()
        tid_to_romid = {row["title_id"]: row["rom_id"] for row in map_rows}

        if tid_to_romid:
            rom_ids = list(tid_to_romid.values())
            rom_ph = ",".join("?" * len(rom_ids))
            cache_rows = conn.execute(
                f"SELECT rom_id, name, icon_url FROM romm_game_cache WHERE username=? AND rom_id IN ({rom_ph})",
                [username, *rom_ids],
            ).fetchall()
            romid_to_cache = {row["rom_id"]: dict(row) for row in cache_rows}

            for tid in ids:
                rom_id = tid_to_romid.get(tid.upper())
                if not rom_id:
                    continue
                cache = romid_to_cache.get(rom_id)
                if not cache:
                    continue
                if result[tid]["display_name"] is None and cache.get("name"):
                    result[tid]["display_name"] = cache["name"]
                if cache.get("icon_url"):
                    result[tid]["icon_url"] = cache["icon_url"]

    # 3. titledb in-memory fallback for any gaps
    for tid in ids:
        if result[tid]["display_name"] is None:
            result[tid]["display_name"] = titledb.resolve_game_name(tid)
        if result[tid]["icon_url"] is None:
            result[tid]["icon_url"] = titledb.get_icon_url(tid)

    return result
