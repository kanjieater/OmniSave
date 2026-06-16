"""
Device Sync API — upload flow + queue poll.
/api/v1/sync/transactions/inbound, /sessions/*, /queue

Delivery endpoints (claim/download/ack/error) are in sync_deliver_api.py.
Protocol per context/server/01-sync-state-machine.md and xx-faster-network.md.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import xxhash
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
import processing
import titledb

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

_conn = None
_staging_dir: Path | None = None
_archive_dir: Path | None = None

_DEVICE_RE = re.compile(r"^[A-Za-z0-9:_-]{4,64}$")
_MAC_COLON_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_TITLE_RE = re.compile(r"^[A-Fa-f0-9]{16}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

CHECKPOINT_SIZE = 4 * 1024 * 1024  # 4 MB — xxHash32 granularity
WINDOW_SIZE = 64 * 1024 * 1024  # 64 MB — HTTP transport granularity


def init(conn, staging_dir: Path, archive_dir: Path) -> None:
    global _conn, _staging_dir, _archive_dir
    _conn = conn
    _staging_dir = staging_dir
    _archive_dir = archive_dir


def _device(request: Request) -> str | None:
    did = request.headers.get("X-Device-ID", "").strip()
    if _MAC_COLON_RE.match(did):
        did = did.replace(":", "").upper()
    return did if _DEVICE_RE.match(did) else None


@dataclass
class TrustedDevice:
    device_id: str
    user_id: str  # resolved from device_auth; never empty in this branch


def _require_device_auth(request: Request) -> "TrustedDevice | JSONResponse":
    """
    Returns TrustedDevice on valid token. Returns 401 for everything else.
    No anonymous fallback — unpaired devices are rejected.
    """
    device_id = _device(request)
    if not device_id:
        return JSONResponse({"error": "X-Device-ID header required or invalid"}, status_code=401)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer sk_device_"):
        return JSONResponse(
            {"error": "device token required — pair this device first"}, status_code=401
        )

    token = auth[7:]
    row = db.get_device_auth_by_token(_conn, token)
    if not row or row["device_id"] != device_id:
        return JSONResponse({"error": "invalid device token"}, status_code=401)
    # Reject soft-deleted devices even if their token somehow survived revocation
    deleted = _conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()
    if deleted and deleted["deleted_at"] is not None:
        return JSONResponse(
            {"error": "device has been removed — re-pair to continue"}, status_code=401
        )
    db.touch_device_last_seen(_conn, device_id)
    return TrustedDevice(device_id=device_id, user_id=row["user_id"])


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def _storage_ok() -> bool:
    try:
        stat = os.statvfs(_staging_dir)
        return (stat.f_bavail / stat.f_blocks) >= 0.05
    except Exception:
        return True


def _write_at_offset(path: Path, off: int, buf: bytes, exists: bool) -> None:
    with path.open("r+b" if exists else "wb") as f:
        f.seek(off)
        f.write(buf)


def _validate_window(
    data: bytes,
    start_offset: int,
    ledger: list[int],
    checkpoint_size: int,
    total_bytes: int,
) -> int:
    """
    Returns new contiguous verified offset after validating complete checkpoints.
    start_offset MUST be a checkpoint boundary (caller invariant).
    Partial tail (last bytes < checkpoint_size) deferred to next window.
    """
    verified = start_offset
    cp_idx = start_offset // checkpoint_size
    pos = 0

    while pos < len(data):
        if cp_idx >= len(ledger):
            break
        boundary = min((cp_idx + 1) * checkpoint_size, total_bytes)
        block_end = boundary - start_offset
        if block_end > len(data):
            break  # incomplete checkpoint — defer
        block = data[pos:block_end]
        if xxhash.xxh32(block).intdigest() != ledger[cp_idx]:
            return verified  # mismatch — svb stalls
        verified = boundary
        pos = block_end
        cp_idx += 1
    return verified


# ── 1. Initiate upload ────────────────────────────────────────────────────────


class InboundBody(BaseModel):
    title_id: str
    total_size_bytes: int
    hardware_type: str = ""
    parent_sequence_num: int | None = None
    preservation: bool = False  # True = pre-restore backup; never fans out, never advances HEAD
    user_key: str = ""  # opaque account UID hex from device; empty for legacy clients
    user_display: str = ""  # cosmetic account name; never used for routing


@router.post("/transactions/inbound")
def start_inbound(body: InboundBody, request: Request):
    # 1. Authenticate device — token required, no anonymous fallback
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    if not _TITLE_RE.match(body.title_id):
        return _err("invalid title_id")
    if body.total_size_bytes <= 0:
        return _err("invalid total_size_bytes")
    if not _storage_ok():
        return _err("insufficient storage", 507)

    # 2. Stamp owner_user_id — profile map takes priority, device owner is the fallback
    owner_user_id = None
    if body.user_key:
        owner_user_id = db.get_profile_owner(_conn, auth.device_id, body.user_key)
    if not owner_user_id:
        owner_user_id = auth.user_id

    # 3. Insert transaction with ownership already resolved
    db.upsert_device(_conn, auth.device_id, body.hardware_type)
    # Update known profiles cache whenever a user_key is seen
    if body.user_key:
        db.upsert_known_profile(_conn, auth.device_id, body.user_key, body.user_display or "")
    txn_id, session_id = db.create_inbound_transaction(
        _conn,
        device_id=auth.device_id,
        title_id=body.title_id,
        total_size_bytes=body.total_size_bytes,
        parent_sequence_num=body.parent_sequence_num,
        preservation=body.preservation,
        user_key=body.user_key,
        user_display=body.user_display,
        owner_user_id=owner_user_id,
    )
    db.log_event(
        _conn,
        "UPLOAD_STARTED",
        f"device={auth.device_id} title={body.title_id}",
        title_id=body.title_id,
        device_id=auth.device_id,
        transaction_id=txn_id,
        owner_user_id=owner_user_id,
    )
    log.info("inbound started txn=%s device=%s title=%s", txn_id[:8], auth.device_id, body.title_id)
    return {"transaction_id": txn_id, "session_id": session_id}


# ── 2. Post manifest (freeze checkpoint ledger) ───────────────────────────────


class ManifestBody(BaseModel):
    checkpoint_size: int
    checkpoint_ledger: list[int]


@router.post("/sessions/{session_id}/manifest")
def post_manifest(session_id: str, body: ManifestBody, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    if not _UUID_RE.match(session_id):
        return _err("invalid session_id")
    if body.checkpoint_size != CHECKPOINT_SIZE:
        return _err(f"checkpoint_size must be {CHECKPOINT_SIZE}")

    sess = db.get_session(_conn, session_id)
    if not sess:
        return _err("session not found", 404)
    if sess["session_state"] != "ACTIVE":
        return _err("session not active", 409)

    import math

    expected_count = math.ceil(sess["total_size_bytes"] / CHECKPOINT_SIZE)
    if len(body.checkpoint_ledger) != expected_count:
        return _err(f"ledger length {len(body.checkpoint_ledger)} != expected {expected_count}")
    for h in body.checkpoint_ledger:
        if not (0 <= h <= 0xFFFFFFFF):
            return _err("ledger contains out-of-range uint32 value")

    if sess["checkpoint_ledger"] is not None:
        return JSONResponse({"ok": True, "server_verified_bytes": 0}, status_code=200)

    db.set_session_manifest(_conn, session_id, json.dumps(body.checkpoint_ledger))
    log.info(
        "manifest posted session=%s checkpoints=%d", session_id[:8], len(body.checkpoint_ledger)
    )
    return {"ok": True, "server_verified_bytes": 0}


# ── 3. Upload window (idempotent, offset-addressed) ───────────────────────────


@router.put("/sessions/{session_id}/window")
async def upload_window(session_id: str, offset: int, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    if not _UUID_RE.match(session_id):
        return _err("invalid session_id")
    if offset < 0:
        return _err("offset must be non-negative")
    if not _storage_ok():
        return _err("insufficient storage", 507)

    sess = db.get_session(_conn, session_id)
    if not sess:
        return _err("session not found", 404)
    if sess["session_state"] != "ACTIVE":
        return _err("session not active", 409)
    if sess["checkpoint_ledger"] is None:
        return _err("manifest not posted yet", 400)

    svb = sess["server_verified_bytes"]
    total = sess["total_size_bytes"]

    # Idempotency — three cases
    if offset < svb:
        return {"server_verified_bytes": svb}
    if offset > svb:
        return JSONResponse(
            {"error": "offset ahead of server_verified_bytes", "server_verified_bytes": svb},
            status_code=409,
        )
    # offset == svb: normal path

    if offset != 0 and offset % CHECKPOINT_SIZE != 0:  # pragma: no cover
        return _err("offset must be checkpoint-aligned")

    # Phase 1: read body, write at explicit offset, validate — ALL outside DB lock
    import asyncio

    data = await request.body()
    if not data:
        return _err("empty request body")
    if len(data) > total - offset:
        return _err(
            f"window exceeds declared total_size_bytes: "
            f"offset={offset} len={len(data)} total={total}",
            400,
        )

    ledger = json.loads(sess["checkpoint_ledger"])

    staging = _staging_dir / session_id / "save.zip"
    staging.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.get_event_loop().run_in_executor(
        None, _write_at_offset, staging, offset, data, staging.exists()
    )

    new_svb = _validate_window(data, offset, ledger, CHECKPOINT_SIZE, total)

    # Phase 2: acquire DB lock ONLY for the compare-and-advance
    _conn.execute("BEGIN IMMEDIATE")
    try:
        cur_svb = _conn.execute(
            "SELECT server_verified_bytes FROM upload_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()[0]
        if cur_svb != offset:  # pragma: no cover
            # Concurrent request already advanced — return winner's value
            _conn.execute("ROLLBACK")
            return {"server_verified_bytes": cur_svb}
        db.advance_server_verified(_conn, session_id, new_svb)
        _conn.execute("COMMIT")
    except Exception:  # pragma: no cover
        _conn.execute("ROLLBACK")
        raise

    return {"server_verified_bytes": new_svb}


# ── 4. Commit upload ──────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/commit")
def commit_upload(session_id: str, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    if not _UUID_RE.match(session_id):
        return _err("invalid session_id")

    sess = db.get_session(_conn, session_id)
    if not sess:
        return _err("session not found", 404)

    txn_id = sess["transaction_id"]
    promoted = db.transition_to_processing(_conn, session_id)

    if promoted is None:
        # Already in PROCESSING or beyond, or upload incomplete.
        svb = sess.get("server_verified_bytes")
        total = sess.get("total_size_bytes")
        if svb is not None and total is not None and svb < total:
            return _err(f"upload incomplete: verified={svb} total={total}", 400)
        return JSONResponse({"processing": True}, status_code=200)

    processing.submit(txn_id, session_id, _staging_dir, _archive_dir, _conn)
    log.info("commit accepted txn=%s", txn_id[:8])
    return JSONResponse({"processing": True}, status_code=202)


# ── 5. Upload session resume offset ──────────────────────────────────────────


@router.get("/sessions/{session_id}/resume")
def session_resume(session_id: str, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    device_id = auth.device_id
    if not _UUID_RE.match(session_id):
        return _err("invalid session_id")
    row = _conn.execute(
        "SELECT us.session_state, us.server_verified_bytes, us.total_size_bytes, "
        "st.source_device_id "
        "FROM upload_sessions us "
        "JOIN sync_transactions st ON st.transaction_id = us.transaction_id "
        "WHERE us.session_id = ?",
        (session_id,),
    ).fetchone()
    if not row or row["source_device_id"] != device_id:
        return _err("session not found", 404)
    return {
        "state": row["session_state"],
        "server_verified_bytes": row["server_verified_bytes"],
        "total_bytes": row["total_size_bytes"],
    }


# ── 6. Poll queue ─────────────────────────────────────────────────────────────


@router.get("/queue")
def poll_queue(
    request: Request,
    sync_generation: int = Query(default=0, ge=0),
):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    device_id = auth.device_id

    db.upsert_device(_conn, device_id)

    prefs_json = db.get_config(_conn, f"sync_prefs:{device_id}")
    sync_prefs = json.loads(prefs_json) if prefs_json else {}

    pending = db.get_pending_outbound(_conn, device_id)
    result = [
        {
            "transaction_id": p["transaction_id"],
            "title_id": p["title_id"],
            "snapshot_sequence": p["snapshot_sequence"],
            "total_bytes": p["total_size_bytes"] or 0,
            "checkpoint_size": CHECKPOINT_SIZE,
            "checkpoint_ledger": json.loads(p["checkpoint_ledger"])
            if p["checkpoint_ledger"]
            else [],
            "target_profile_uid": p["target_profile_uid"] or "",
        }
        for p in pending
    ]

    hint = None
    if not result:
        has_processing = _conn.execute(
            "SELECT COUNT(*) FROM sync_transactions "
            "WHERE direction = 'inbound' AND state = 'PROCESSING' AND source_device_id != ?",
            (device_id,),
        ).fetchone()[0]
        if has_processing:
            hint = "queue_hint"

    server_gen = db.db_get_sync_generation(_conn, device_id)
    backup_updates = []
    if sync_generation < server_gen:
        backup_updates = [
            {
                "title_id": r["title_id"],
                "snapshot_sequence": r["snapshot_sequence"],
                "committed_at": r["committed_at"],
            }
            for r in db.db_get_backup_updates_since(_conn, device_id, sync_generation)
        ]

    game_names = {}
    for p in result:
        tid = p["title_id"]
        name = titledb.resolve_game_name(tid)
        if name:
            game_names[tid] = name

    return {
        "pending": result,
        "hint": hint,
        "sync_prefs": sync_prefs,
        "sync_generation": server_gen,
        "backup_updates": backup_updates,
        "game_names": game_names,
    }


# ── Catalog backfill ──────────────────────────────────────────────────────────


def _backfill_outbound_for_device(conn, device_id: str, title_ids: list[str]) -> None:
    """Create READY_FOR_RESTORE outbound rows for a device that just added titles to its catalog.

    Uses the same sequence-aware HEAD selection as the old lazy-fork but scoped to specific
    title_ids. Idempotent: no new rows created if the device already has an active/completed
    outbound at or above the latest inbound HEAD sequence.
    """
    for raw_title_id in title_ids:
        title_id = raw_title_id.upper()
        rows = conn.execute(
            "SELECT st.transaction_id, st.title_id, COALESCE(st.user_key,'') AS user_key,"
            " st.snapshot_sequence, st.owner_user_id "
            "FROM sync_transactions st "
            "WHERE st.direction = 'inbound' "
            "  AND st.state = 'READY_FOR_RESTORE' "
            "  AND st.has_conflict = 0 "
            "  AND st.preservation = 0 "
            "  AND st.title_id = ? "
            "  AND st.source_device_id != ? "
            "  AND (st.owner_user_id IS NULL"
            "       OR st.owner_user_id = ("
            "           SELECT d.owner_user_id FROM devices d WHERE d.device_id = ?"
            "       )"
            "  )"
            "  AND st.snapshot_sequence = ("
            "      SELECT MAX(st2.snapshot_sequence) "
            "      FROM sync_transactions st2 "
            "      WHERE st2.title_id = st.title_id "
            "        AND COALESCE(st2.user_key,'') = COALESCE(st.user_key,'') "
            "        AND st2.direction = 'inbound' "
            "        AND st2.state = 'READY_FOR_RESTORE' "
            "        AND st2.has_conflict = 0 "
            "        AND st2.preservation = 0 "
            "        AND st2.source_device_id != ?"
            "  ) "
            "  AND NOT EXISTS ("
            "      SELECT 1 FROM sync_transactions outb "
            "      WHERE outb.direction = 'outbound' "
            "        AND outb.target_device_id = ? "
            "        AND outb.title_id = st.title_id "
            "        AND COALESCE(outb.user_key,'') = COALESCE(st.user_key,'') "
            "        AND outb.state IN ('READY_FOR_RESTORE','COMPLETED','FAILED') "
            "        AND outb.snapshot_sequence >= st.snapshot_sequence"
            "  )",
            (title_id, device_id, device_id, device_id, device_id),
        ).fetchall()

        for row in rows:
            try:
                target_profile = db.get_last_inbound_user_key(
                    conn, device_id, row["title_id"], row["owner_user_id"]
                ) or db.get_device_default_profile(conn, device_id)
                db.supersede_active_outbound(
                    conn, device_id, row["title_id"], row["owner_user_id"] or ""
                )
                outbound_id = db.create_outbound_transaction(
                    conn,
                    row["transaction_id"],
                    device_id,
                    target_profile_uid=target_profile,
                )
                if outbound_id is None:
                    log.warning(
                        "backfill INSERT ignored (duplicate) device=%s title=%s seq=%s",
                        device_id,
                        row["title_id"][:8],
                        row["snapshot_sequence"],
                    )
                    continue
                db.log_event(
                    conn,
                    "OUTBOUND_CREATED",
                    f"→ {device_id} (catalog backfill)",
                    title_id=row["title_id"],
                    device_id=device_id,
                    transaction_id=outbound_id,
                    owner_user_id=row["owner_user_id"],
                )
                log.info(
                    "backfill outbound=%s device=%s title=%s",
                    outbound_id[:8],
                    device_id,
                    row["title_id"][:8],
                )
            except Exception as exc:
                log.warning(
                    "backfill fork failed device=%s title=%s: %s", device_id, title_id[:8], exc
                )


# ── Device config / bootstrap ─────────────────────────────────────────────────


class KnownProfile(BaseModel):
    profile_id: str
    profile_name: str = ""


class DeviceConfigBody(BaseModel):
    known_profiles: list[KnownProfile] = []
    installed_titles: list[str] | None = None


@router.post("/device-config")
def device_config(body: DeviceConfigBody, request: Request):
    """
    Bootstrap endpoint (X-Device-ID only — no Bearer token required yet).

    1. Always: upsert reported known_profiles into device_known_profiles cache.
    2. If config_pending=1 AND devices.last_seen is within 15 minutes:
       return {"device_token": "<token>"} and clear the flag.
    3. Otherwise: return {}.
    """
    device_id = _device(request)
    if not device_id:
        return _err("X-Device-ID required", 400)

    # Register device on first contact; always refresh last_seen so the 15-minute
    # token-delivery window reflects when the device last contacted us.
    from datetime import UTC
    from datetime import datetime as _dt

    _bootstrap_now = _dt.now(UTC).isoformat()
    _conn.execute(
        "INSERT INTO devices (device_id, display_name, hardware_type, client_type, last_seen, created_at)"
        " VALUES (?, '', '', 'switch', ?, ?)"
        " ON CONFLICT(device_id) DO UPDATE SET"
        "   client_type='switch', last_seen=excluded.last_seen",
        (device_id, _bootstrap_now, _bootstrap_now),
    )

    # Update known profiles regardless of token state.
    # Auto-claim: if the device already has an owner and this profile hasn't been
    # claimed by anyone yet, claim it automatically so UI badges work without a
    # manual claim step in the web interface.
    _device_owner = db.get_device_owner(_conn, device_id)
    for p in body.known_profiles:
        if p.profile_id:
            db.upsert_known_profile(_conn, device_id, p.profile_id, p.profile_name)
            if _device_owner and db.get_profile_owner(_conn, device_id, p.profile_id) is None:
                db.upsert_device_profile(
                    _conn, device_id, p.profile_id, _device_owner, p.profile_name
                )
                db.backfill_owner_on_profile_claim(_conn, device_id, p.profile_id, _device_owner)

    # Catalog update: atomically replace installed-game inventory, then backfill outbounds.
    if body.installed_titles is not None:
        log.info(
            "device-config: received device_id=%s installed_titles_present=True count=%d profiles=%d",
            device_id,
            len(body.installed_titles),
            len(body.known_profiles or []),
        )
        for t in body.installed_titles:
            if not _TITLE_RE.match(t):
                return _err(f"invalid title_id in installed_titles: {t!r}")
        incoming_catalog = {t.upper() for t in body.installed_titles}
        catalog_changed = False
        _conn.execute("BEGIN IMMEDIATE")
        try:
            prev_catalog = {
                r["title_id"].upper()
                for r in _conn.execute(
                    "SELECT title_id FROM device_installed_games WHERE device_id=?",
                    (device_id,),
                ).fetchall()
            }
            catalog_changed = prev_catalog != incoming_catalog
            db.replace_device_catalog(_conn, device_id, body.installed_titles)
            _backfill_outbound_for_device(_conn, device_id, body.installed_titles)
            n = db.supersede_failed_outbounds_for_uninstalled(_conn)
            if n:
                log.info(
                    "device-config: superseded %d FAILED outbound(s) after catalog update for %s",
                    n,
                    device_id,
                )
            _conn.execute("COMMIT")
        except Exception:
            _conn.execute("ROLLBACK")
            raise
        log.info(
            "device-config: catalog committed device_id=%s prev=%d incoming=%d changed=%s",
            device_id,
            len(prev_catalog),
            len(incoming_catalog),
            catalog_changed,
        )
        if catalog_changed:
            import romm_index as _romm_index

            _romm_index.request_index_run_now()

    device_row = db.get_device(_conn, device_id)
    token = db.consume_pending_config(
        _conn, device_id, device_row["last_seen"] if device_row else None
    )
    if token:
        log.info("device-config: delivered token to %s", device_id)
        return {"device_token": token}

    # If device has no token and no owner yet, generate/refresh a pairing code
    # so the overlay can display it for the user to claim on the web UI.
    auth_row = _conn.execute("SELECT 1 FROM device_auth WHERE device_id=?", (device_id,)).fetchone()
    if not auth_row:
        pairing_code = db.create_pairing_code(_conn, device_id)
        return {"pairing_code": pairing_code, "pairing_expires_in": 900}
    return {}
