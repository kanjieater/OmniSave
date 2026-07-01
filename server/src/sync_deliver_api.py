"""
Device Sync API — delivery endpoints.
/transactions/{id}/range, /ack, /fail

No exclusive lease ownership. The server is a passive snapshot ledger.
Multiple devices may download the same snapshot concurrently.
"""

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import database as db
import device_auth as _auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

_conn = None
_staging_dir: Path | None = None
_archive_dir: Path | None = None

TrustedDevice = _auth.TrustedDevice


def init(conn, staging_dir: Path, archive_dir: Path) -> None:
    global _conn, _staging_dir, _archive_dir
    _conn = conn
    _staging_dir = staging_dir
    _archive_dir = archive_dir


def _require_device_auth(request: Request) -> "_auth.TrustedDevice | JSONResponse":
    return _auth.require_device_auth(_conn, request)


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


# ── Download restore bytes (byte oracle) ──────────────────────────────────────


@router.get("/transactions/{transaction_id}/range")
def download_range(transaction_id: UUID, offset: int, length: int, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    device_id = auth.device_id
    if offset < 0 or length <= 0:
        return _err("offset must be >= 0 and length must be > 0")

    txn_id = str(transaction_id)
    txn = db.get_transaction(_conn, txn_id)
    if not txn or txn.get("target_device_id") != device_id:
        return _err("not found or access denied", 404)
    if txn["state"] not in ("READY_FOR_RESTORE", "COMPLETED"):
        return _err("snapshot not available", 404)
    if not txn.get("snapshot_path"):
        return _err("snapshot not available", 404)

    save_path = Path(txn["snapshot_path"])
    if not save_path.exists():
        return _err("snapshot file missing", 404)

    total = txn.get("total_size_bytes") or save_path.stat().st_size
    if offset >= total:
        return _err("offset beyond end of file", 416)
    if offset + length > total:
        return _err("offset+length exceeds total_size_bytes", 416)

    data = bytearray(length)
    with save_path.open("rb") as f:
        f.seek(offset)
        read = f.readinto(data)

    return Response(content=bytes(data[:read]), media_type="application/octet-stream")


# ── ACK restore complete ───────────────────────────────────────────────────────


class AckBody(BaseModel):
    transaction_id: UUID


@router.post("/ack")
def ack_restore(body: AckBody, request: Request):
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    device_id = auth.device_id
    txn_id = str(body.transaction_id)

    ok = db.complete_outbound(_conn, device_id, txn_id)
    if not ok:
        return _err("ack rejected: transaction not found or wrong state", 409)

    txn = db.get_transaction(_conn, txn_id)
    if txn and txn.get("snapshot_sequence") is not None:
        db.upsert_device_title_head(_conn, txn["title_id"], device_id, txn["snapshot_sequence"])
    if txn:
        _conn.execute(
            "UPDATE sync_transactions SET state='SUPERSEDED', updated_at=?"
            " WHERE title_id=? AND target_device_id=? AND direction='outbound'"
            " AND state='FAILED' AND transaction_id != ?",
            (db._now(), txn["title_id"], device_id, txn_id),
        )
    seq = txn.get("snapshot_sequence") if txn else None
    db.log_event(
        _conn,
        "RESTORE_ACKED",
        f"device={device_id}" + (f" seq={seq}" if seq is not None else ""),
        title_id=txn["title_id"] if txn else None,
        device_id=device_id,
        transaction_id=txn_id,
        owner_user_id=txn.get("owner_user_id") if txn else None,
    )
    log.info("ACK txn=%s device=%s", txn_id[:8], device_id)
    return {"ok": True}


# ── Permanent inject failure ───────────────────────────────────────────────────


class FailBody(BaseModel):
    transaction_id: UUID
    error_code: str = ""


@router.post("/fail")
def delivery_fail(body: FailBody, request: Request):
    """Permanent inject failure — marks outbound FAILED, removed from queue."""
    auth = _require_device_auth(request)
    if isinstance(auth, JSONResponse):
        return auth
    device_id = auth.device_id
    txn_id = str(body.transaction_id)

    failed = db.fail_outbound(_conn, device_id, txn_id)
    txn = db.get_transaction(_conn, txn_id)
    db.log_event(
        _conn,
        "INJECT_FAILED",
        f"code={body.error_code} device={device_id}",
        title_id=txn["title_id"] if txn else None,
        device_id=device_id,
        transaction_id=txn_id,
        owner_user_id=txn.get("owner_user_id") if txn else None,
    )
    log.info(
        "delivery fail txn=%s code=%s marked=%s",
        txn_id[:8],
        body.error_code,
        failed,
    )
    return {"ok": True}
