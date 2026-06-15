"""
Title database — resolves Switch TitleIDs to human-readable game names.

Lookup precedence (enforced in resolve_game_name):
  1. Custom user label from DB (via resolve_game_name with conn=)
  2. US English titledb (blawar/titledb US.en.json)
  3. All other regions merged (GB, AU, JP, DE, FR, ES, IT, NL, RU, KR, ZH, HK)
  4. None  (caller applies title_id as final fallback)

On startup, US + all fallback regions are prefetched in background threads.
ETag / Last-Modified headers avoid re-downloading unchanged blobs on restart.

Custom override via OMNISAVE_TITLEDB env var (path to local JSON, any region)
takes over entirely for the US slot; regional prefetch still runs.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_TITLEDB_PATH = os.environ.get("OMNISAVE_TITLEDB", "")
_DATA_DIR = Path(os.environ.get("OMNISAVE_DATA", "/app/data"))
_SKIP_REGIONS = os.environ.get("OMNISAVE_TITLEDB_SKIP_REGIONS", "").lower() in ("1", "true", "yes")

_CACHE_US = _DATA_DIR / "titledb_cache_us.json"
_META_US = _DATA_DIR / "titledb_meta_us.json"
_URL_US = "https://raw.githubusercontent.com/blawar/titledb/master/US.en.json"

# All non-US regions merged into a single fallback DB.
# Downloaded sequentially in priority order: EN → JP → rest.
# First-write-wins merge, so earlier regions win name conflicts.
_FALLBACK_REGIONS: list[tuple[str, str]] = [
    # English
    ("GB", "en"),
    # Japanese
    ("JP", "ja"),
    ("AU", "en"),
    # Rest
    ("DE", "de"),
    ("FR", "fr"),
    ("ES", "es"),
    ("IT", "it"),
    ("NL", "nl"),
    ("RU", "ru"),
    ("KR", "ko"),
    ("ZH", "zh"),
    ("HK", "zh"),
]

_db_us: dict | None = None
_db_extra: dict | None = None  # None = not yet loaded; {} = loaded but empty
_lock_us = threading.Lock()
_lock_extra = threading.Lock()
_name_index: dict[str, str] | None = None  # lowercase name → title_id (base games only)
_lock_name_index = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse(raw: dict) -> dict:
    result = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            tid = v.get("id") or k
        else:
            tid = k
        result[str(tid).upper()] = v
    return result


def _load_json_file(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        log.warning("titledb: could not read %s: %s", path, exc)
        return None


def _read_meta(meta_path: Path) -> dict:
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except Exception:
            pass
    return {}


def _write_meta(meta_path: Path, etag: str | None, last_modified: str | None) -> None:
    try:
        meta_path.write_text(json.dumps({"etag": etag, "last_modified": last_modified}))
    except Exception as exc:
        log.warning("titledb: could not write meta %s: %s", meta_path, exc)


def _fetch_and_cache(
    url: str, cache_path: Path, meta_path: Path, lock: threading.Lock, db_ref_setter
) -> None:
    """Download url → cache_path, respecting ETag / Last-Modified, then swap the in-memory db."""
    try:
        meta = _read_meta(meta_path)
        headers: dict[str, str] = {"User-Agent": "OmniSave/1.0"}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

        log.info("titledb: fetching %s", url)
        req = urllib.request.Request(url, headers=headers)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 304:
                    log.info("titledb: %s not modified (304), keeping cache", url)
                    return
                data = resp.read().decode("utf-8")
                etag = resp.headers.get("ETag")
                last_modified = resp.headers.get("Last-Modified")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                log.info("titledb: %s not modified (304), keeping cache", url)
                return
            raise
        elapsed = time.perf_counter() - t0
        size_kb = len(data.encode()) // 1024

        raw = json.loads(data)
        parsed = _parse(raw)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(raw))
        _write_meta(meta_path, etag, last_modified)

        with lock:
            db_ref_setter(parsed)
        log.info(
            "titledb: cached %s — %d entries, %d KB in %.1fs",
            url.split("/")[-1],
            len(parsed),
            size_kb,
            elapsed,
        )
    except Exception as exc:
        log.warning("titledb: fetch failed for %s: %s", url, exc)


def _ensure_us() -> dict:
    global _db_us
    if _db_us is not None:
        return _db_us
    with _lock_us:
        if _db_us is not None:
            return _db_us
        _db_us = {}

        if _TITLEDB_PATH:
            raw = _load_json_file(Path(_TITLEDB_PATH))
            if raw:
                _db_us = _parse(raw)
                log.info("titledb: loaded %d entries from OMNISAVE_TITLEDB", len(_db_us))
                return _db_us
            log.warning("titledb: OMNISAVE_TITLEDB unreadable, falling through to cache")

        raw = _load_json_file(_CACHE_US)
        if raw:
            _db_us = _parse(raw)
            log.info("titledb: loaded %d cached US entries", len(_db_us))
        return _db_us


def _ensure_extra() -> dict:
    """Load all cached regional files into _db_extra on first access (first-write-wins)."""
    if _SKIP_REGIONS:
        return {}
    global _db_extra
    if _db_extra is not None:
        return _db_extra
    with _lock_extra:
        if _db_extra is not None:
            return _db_extra
        merged: dict = {}
        for region, lang in _FALLBACK_REGIONS:
            cache = _DATA_DIR / f"titledb_cache_{region.lower()}_{lang}.json"
            raw = _load_json_file(cache)
            if raw:
                for k, v in _parse(raw).items():
                    if k not in merged:
                        merged[k] = v
        _db_extra = merged
        log.info("titledb: loaded %d extra entries from regional caches", len(_db_extra))
        return _db_extra


def _extract_name(entry) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry or None
    if isinstance(entry, dict):
        return (
            entry.get("name")
            or entry.get("title")
            or entry.get("titleName")
            or entry.get("bannerTitle")
        ) or None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prefetch() -> None:
    """Spawn background threads to prefetch US + all regional fallbacks.

    Regional downloads run sequentially in a single thread to avoid bursting
    13 simultaneous writes to the data directory (critical on NAS mounts).
    Set OMNISAVE_TITLEDB_SKIP_REGIONS=true to skip regional downloads entirely.
    """
    log.info("titledb: prefetch pid=%d skip_regions=%s", os.getpid(), _SKIP_REGIONS)

    def _set_us(parsed):
        global _db_us
        _db_us = parsed

    def _make_extra_merger():
        def _merge(parsed):
            global _db_extra
            with _lock_extra:
                if _db_extra is None:
                    _db_extra = {}
                for k, v in parsed.items():
                    if k not in _db_extra:
                        _db_extra[k] = v

        return _merge

    if not _TITLEDB_PATH:
        threading.Thread(
            target=_fetch_and_cache,
            args=(_URL_US, _CACHE_US, _META_US, _lock_us, _set_us),
            daemon=True,
            name="titledb-fetch-us",
        ).start()

    if not _SKIP_REGIONS:
        merger = _make_extra_merger()

        def _fetch_regions() -> None:
            for region, lang in _FALLBACK_REGIONS:
                url = f"https://raw.githubusercontent.com/blawar/titledb/master/{region}.{lang}.json"
                cache = _DATA_DIR / f"titledb_cache_{region.lower()}_{lang}.json"
                meta = _DATA_DIR / f"titledb_meta_{region.lower()}_{lang}.json"
                _fetch_and_cache(url, cache, meta, _lock_extra, merger)

        threading.Thread(
            target=_fetch_regions,
            daemon=True,
            name="titledb-fetch-regions",
        ).start()


def get_us_name(title_id: str) -> str | None:
    return _extract_name(_ensure_us().get(title_id.upper()))


def get_jp_name(title_id: str) -> str | None:
    return _extract_name(_ensure_extra().get(title_id.upper()))


def resolve_game_name(title_id: str, conn=None) -> str | None:
    """
    Priority: DB label > US titledb > all regional fallbacks.
    Returns None if no name found — caller applies title_id as final fallback.
    """
    if conn is not None:
        import database

        label = database.get_label(conn, "game", title_id.upper())
        if label:
            return label
    return get_us_name(title_id) or _extract_name(_ensure_extra().get(title_id.upper()))


def get_icon_url(title_id: str) -> str | None:
    tid = title_id.upper()
    entry = _ensure_us().get(tid)
    if isinstance(entry, dict) and entry.get("iconUrl"):
        return entry["iconUrl"]
    entry = _ensure_extra().get(tid)
    if isinstance(entry, dict) and entry.get("iconUrl"):
        return entry["iconUrl"]
    return None


_NAME_STRIP_RE = re.compile(r"[™®©:'\"\-!?,.]")


def _norm_name(name: str) -> str:
    """Normalize a game name for fuzzy matching: strip symbols/punctuation, collapse whitespace."""
    name = _NAME_STRIP_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def find_title_id_by_name(name: str) -> str | None:
    """Reverse lookup: given a display name, return the base-game title_id.

    Matches after normalizing both sides (strips ™/®/©/:/'/-/etc., collapses whitespace).
    Only base games (title_ids ending in '000') are indexed.
    Returns None if no match or the name is ambiguous (>1 title_id normalizes to same key).
    """
    global _name_index
    if _name_index is None:
        with _lock_name_index:
            if _name_index is None:
                idx: dict[str, list[str]] = {}
                for source in (_ensure_us(), _ensure_extra()):
                    for tid, entry in source.items():
                        if not tid.upper().endswith("000"):
                            continue
                        n = _extract_name(entry)
                        if n:
                            key = _norm_name(n)
                            if key not in idx:
                                idx[key] = []
                            if tid not in idx[key]:
                                idx[key].append(tid)
                _name_index = {k: v[0] for k, v in idx.items() if len(v) == 1}
    return _name_index.get(_norm_name(name))


# TODO: remove after frontend fully migrated to resolve_game_name()
def get_name(title_id: str) -> str | None:
    return get_us_name(title_id)
