"""
UI Control Plane — /api/v1/ui/*

Username/password login with session token (HttpOnly cookie + Bearer header).
Default credentials on first run: admin / admin.
All derived state (status, sync_state) computed by shared helpers — never duplicated.
"""

import hashlib as _hashlib
import json
import logging
import re
import re as _re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import database as db
import game_meta
import romm_meta
import titledb

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ui", tags=["ui"])

_conn = None
_archive_dir: Path | None = None
_RESET_FLAG = Path("/config/reset_admin.flag")
_TITLE_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9:_-]{4,64}$")
_STATE_MAP = {
    "READY_FOR_RESTORE": "COMMITTED",
    "PROCESSING": "PERSISTED",
    "UPLOADING": "RECEIVED",
    "FAILED": "FAILED",
    "COMPLETED": "COMMITTED",
    "SUPERSEDED": "SUPERSEDED",
    "DEDUPED": "DUPLICATE",
}

_PBKDF2_ITERS = 260_000


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERS}:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, iters_str, salt, expected = stored.split(":", 4)
        dk = _hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters_str))
        return secrets.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def seed_default_credentials(conn) -> None:
    """Seed admin/admin credentials on first run. No-op if already set."""
    if not db.get_config(conn, "admin_username"):
        db.set_config(conn, "admin_username", "admin")
    if not db.get_config(conn, "admin_password_hash"):
        db.set_config(conn, "admin_password_hash", _hash_password("admin"))
    if not db.get_config(conn, "admin_created_at"):
        db.set_config(conn, "admin_created_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


def init(conn, archive_dir: Path | None = None) -> None:
    global _conn, _archive_dir
    _conn = conn
    _archive_dir = archive_dir
    seed_default_credentials(conn)
    _check_reset_flag()


def _check_reset_flag() -> None:
    if _RESET_FLAG.exists():
        admin_username = db.get_config(_conn, "admin_username") or "admin"
        db.delete_auth_sessions_for_user(_conn, admin_username)
        db.set_config(_conn, "admin_password_hash", _hash_password("admin"))
        _RESET_FLAG.unlink(missing_ok=True)
        log.warning("admin credentials reset via reset flag — password reset to 'admin'")


def _archive_size(transaction_id: str) -> int | None:
    if _archive_dir is None:
        return None
    p = _archive_dir / transaction_id / "save.zip"
    try:
        return p.stat().st_size
    except OSError:
        return None


# ── Shared derivation helpers (single source of truth) ────────────────────────


def _game_status(conn, title_id: str) -> str:
    """SYNCED if any successful save exists, NO_DATA otherwise.
    Games never show ERROR — upload failures are device-level events."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sync_transactions "
        "WHERE title_id=? AND direction='inbound' "
        "AND state IN ('READY_FOR_RESTORE','COMPLETED') AND sha256 IS NOT NULL",
        (title_id,),
    ).fetchone()
    return "SYNCED" if (row and row["n"]) else "NO_DATA"


def _game_display_name(conn, title_id: str, username: str) -> str | None:
    return game_meta.game_display_name(conn, title_id, username)


def _game_icon_url(conn, title_id: str, username: str) -> str | None:
    return game_meta.game_icon_url(conn, title_id, username)


def _head_sequence(conn, title_id: str, owner_user_id: str | None = None) -> int | None:
    if owner_user_id:
        # Scope HEAD to saves from device profiles claimed by this user (T1).
        # Legacy saves (no user_key) fall back to owner_user_id for backward compat.
        row = conn.execute(
            "SELECT MAX(snapshot_sequence) FROM sync_transactions"
            " WHERE title_id=? AND direction='inbound' AND has_conflict=0 AND preservation=0"
            " AND state='READY_FOR_RESTORE'"
            " AND ("
            "  (COALESCE(user_key,'') != '' AND (source_device_id, user_key) IN ("
            "   SELECT device_id, profile_id FROM device_profile_map WHERE user_id=?))"
            "  OR (COALESCE(user_key,'') = '' AND owner_user_id = ?))",
            (title_id, owner_user_id, owner_user_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(snapshot_sequence) FROM sync_transactions"
            " WHERE title_id=? AND direction='inbound' AND has_conflict=0 AND preservation=0"
            " AND state='READY_FOR_RESTORE'",
            (title_id,),
        ).fetchone()
    return row[0] if row else None


def _has_pending_delivery(conn, device_id: str, title_id: str) -> bool:
    """True when a save exists on the server that this device has not yet received.

    Mirrors the dashboard pending_by_dev query exactly — counts outbound rows
    the processing worker has forked for this device. Callers must never leak
    the underlying state name; this helper is the only place it appears.
    """
    row = conn.execute(
        "SELECT 1 FROM sync_transactions"
        " WHERE target_device_id=? AND title_id=? AND direction='outbound'"
        " AND state='READY_FOR_RESTORE' LIMIT 1",
        (device_id, title_id),
    ).fetchone()
    return row is not None


def _sync_state_for_device(conn, device_id: str, title_id: str, head_seq: int | None) -> dict:
    """Per-request sync state.

    Primary signal: device_title_head.last_seq — updated when the device uploads
    (its own save) or ACKs a delivery.  If last_seq >= head_seq the device is SYNCED.
    Outbound transactions provide the DOWNLOADING / OUT_OF_SYNC signal for in-flight
    deliveries only when the device is not already known-synced."""
    dth = conn.execute(
        "SELECT last_seq FROM device_title_head WHERE title_id=? AND device_id=?",
        (title_id, device_id),
    ).fetchone()
    device_last_seq = dth["last_seq"] if dth else None

    # Active upload trumps SYNCED — device is pushing a newer save right now
    uploading = conn.execute(
        "SELECT 1 FROM sync_transactions st"
        " JOIN upload_sessions us ON us.transaction_id = st.transaction_id"
        " WHERE st.source_device_id=? AND st.title_id=? AND st.direction='inbound'"
        "  AND st.state='UPLOADING'"
        "  AND us.last_active_at > datetime('now', '-30 seconds')"
        " LIMIT 1",
        (device_id, title_id),
    ).fetchone()
    if uploading:
        return {
            "sync_state": "UPLOADING",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }

    # Device is SYNCED if its last known seq matches the current HEAD
    if head_seq is not None and device_last_seq is not None and device_last_seq >= head_seq:
        return {
            "sync_state": "SYNCED",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }

    # Device is SYNCED if it is the source of the HEAD — it already has that save locally.
    # This catches devices whose device_title_head wasn't backfilled from older processing runs.
    if head_seq is not None:
        head_from_device = conn.execute(
            "SELECT 1 FROM sync_transactions"
            " WHERE title_id=? AND direction='inbound' AND source_device_id=?"
            " AND snapshot_sequence=? AND preservation=0 LIMIT 1",
            (title_id, device_id, head_seq),
        ).fetchone()
        if head_from_device:
            return {
                "sync_state": "SYNCED",
                "local_sequence": head_seq,
                "cloud_head_sequence": head_seq,
            }

    # Check active outbound for in-flight delivery state
    row = conn.execute(
        "SELECT state, snapshot_sequence FROM sync_transactions"
        " WHERE target_device_id=? AND title_id=? AND direction='outbound'"
        " ORDER BY CASE state"
        "  WHEN 'DELIVERING' THEN 0 WHEN 'READY_FOR_RESTORE' THEN 1"
        "  WHEN 'COMPLETED' THEN 2 ELSE 3 END, snapshot_sequence DESC LIMIT 1",
        (device_id, title_id),
    ).fetchone()
    if not row:
        return {
            "sync_state": "NO_DELIVERY",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }
    state, seq = row["state"], row["snapshot_sequence"]
    if state == "DELIVERING":
        return {
            "sync_state": "DOWNLOADING",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }
    if state == "COMPLETED" and (head_seq is None or seq == head_seq):
        # Fallback for devices that ACKed before device_title_head was tracked
        return {
            "sync_state": "SYNCED",
            "local_sequence": seq,
            "cloud_head_sequence": head_seq,
        }
    if state == "FAILED":
        return {
            "sync_state": "DELIVERY_FAILED",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }
    if state == "SUPERSEDED":
        # All outbounds were superseded — delivery was cancelled. No active delivery.
        return {
            "sync_state": "NO_DELIVERY",
            "local_sequence": device_last_seq,
            "cloud_head_sequence": head_seq,
        }
    return {
        "sync_state": "OUT_OF_SYNC",
        "local_sequence": device_last_seq,
        "cloud_head_sequence": head_seq,
    }


def _romm_head_was_synced(conn, username: str, title_id: str, head_seq: int | None) -> bool:
    """True when the current HEAD was delivered to ANY romm device owned by this user.
    Handles source_id renames: the old device completed delivery, the new device has no transactions."""
    if head_seq is None:
        return False
    return bool(
        conn.execute(
            "SELECT 1 FROM sync_transactions"
            " WHERE title_id=? AND direction='outbound' AND state='COMPLETED'"
            " AND snapshot_sequence=?"
            " AND target_device_id IN"
            "  (SELECT device_id FROM devices WHERE owner_user_id=? AND client_type='romm')",
            (title_id, head_seq, username),
        ).fetchone()
    )


def _effective_sync_state(
    conn,
    username: str,
    device_id: str,
    client_type: str,
    title_id: str,
    head_seq: int | None,
) -> dict:
    """UI view-layer sync state. Not for scheduling or retry decisions.

    For romm virtual devices applies cross-device HEAD-delivery logic;
    caller must pass client_type to avoid a per-call DB round-trip.

    Gate order:
      1. Non-romm → base state unchanged.
      2. Base SYNCED → trust it (terminal, authoritative).
      3. _romm_head_was_synced → SYNCED (cross-device / rename recovery).
      4. Base DOWNLOADING → preserve in-flight delivery.
    """
    state = _sync_state_for_device(conn, device_id, title_id, head_seq)
    if client_type != "romm":
        return state
    if state["sync_state"] == "SYNCED":
        return state
    if _romm_head_was_synced(conn, username, title_id, head_seq):
        return {"sync_state": "SYNCED", "local_sequence": head_seq, "cloud_head_sequence": head_seq}
    return state


# ── Auth helpers ───────────────────────────────────────────────────────────────


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("os_session", "")


def _token_valid(request: Request) -> bool:
    return _current_username(request) is not None


def _current_username(request: Request) -> str | None:
    token = _extract_token(request)
    if not token:
        return None
    row = db.get_auth_user_by_token(_conn, token)
    return row["username"] if row else None


def _is_admin(request: Request) -> bool:
    username = _current_username(request)
    if not username:
        return False
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    return secrets.compare_digest(username, admin_username)


def _auth_err(request: Request) -> JSONResponse | None:
    if not _token_valid(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _admin_err(request: Request) -> JSONResponse | None:
    """Return 401/403 if not authenticated or not the admin account."""
    err = _auth_err(request)
    if err:
        return err
    if not _is_admin(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None


# ── Auth endpoints ─────────────────────────────────────────────────────────────


class LoginBody(BaseModel):
    username: str
    password: str


@router.get("/auth/status")
async def auth_status(request: Request):
    username = _current_username(request) or ""
    return {
        "bootstrapped": True,
        "authenticated": bool(username),
        "username": username,
        "is_admin": _is_admin(request),
        "server_now": int(datetime.now(UTC).timestamp() * 1000),
    }


@router.post("/auth/login")
def login(body: LoginBody, response: Response):
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    # Check admin account — encode to bytes so compare_digest handles non-ASCII safely
    if secrets.compare_digest(body.username.encode(), admin_username.encode()):
        stored_hash = db.get_config(_conn, "admin_password_hash") or ""
        if not _verify_password(body.password, stored_hash):
            return JSONResponse({"error": "invalid credentials"}, status_code=401)
        token = "sk_live_" + secrets.token_urlsafe(32)
        db.insert_auth_session(_conn, admin_username, token)
        response.set_cookie("os_session", token, httponly=True, samesite="lax")
        log.info("login: admin")
        return {"ok": True, "admin_token": token}
    # Check non-admin accounts
    row = db.get_auth_user(_conn, body.username)
    if not row or not _verify_password(body.password, row["password_hash"]):
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    token = "sk_live_" + secrets.token_urlsafe(32)
    db.insert_auth_session(_conn, body.username, token)
    response.set_cookie("os_session", token, httponly=True, samesite="lax")
    log.info("login: user=%s", body.username)
    return {"ok": True, "admin_token": token}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = _extract_token(request)
    if token:
        db.delete_auth_session_by_token(_conn, token)
    response.delete_cookie("os_session")
    return {"ok": True}


@router.post("/auth/rotate")
def rotate(request: Request, response: Response):
    err = _auth_err(request)
    if err:
        return err
    old_token = _extract_token(request)
    username = _current_username(request)
    token = "sk_live_" + secrets.token_urlsafe(32)
    if username:
        db.delete_auth_session_by_token(_conn, old_token)
        db.insert_auth_session(_conn, username, token)
    response.set_cookie("os_session", token, httponly=True, samesite="lax")
    log.info("token rotated")
    return {"admin_token": token}


# ── User management ────────────────────────────────────────────────────────────


class CreateUserBody(BaseModel):
    username: str
    password: str


@router.get("/users")
def list_users(request: Request):
    err = _admin_err(request)
    if err:
        return err
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    admin_created = db.get_config(_conn, "admin_created_at") or ""
    users = [{"username": admin_username, "is_admin": True, "created_at": admin_created}]
    for row in db.list_auth_users(_conn):
        users.append(
            {"username": row["username"], "is_admin": False, "created_at": row["created_at"]}
        )
    return {"users": users}


@router.post("/users")
def create_user(body: CreateUserBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _is_admin(request):
        return JSONResponse({"error": "admin only"}, status_code=403)
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    if not body.username.strip():
        return JSONResponse({"error": "username required"}, status_code=400)
    if secrets.compare_digest(body.username.strip(), admin_username):
        return JSONResponse({"error": "username reserved"}, status_code=409)
    if not body.password:
        return JSONResponse({"error": "password required"}, status_code=400)
    try:
        db.create_auth_user(_conn, body.username.strip(), _hash_password(body.password))
    except Exception:
        return JSONResponse({"error": "username already exists"}, status_code=409)
    log.info("user created: %s", body.username)
    return {"ok": True}


@router.delete("/users/{username}")
def delete_user(username: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _is_admin(request):
        return JSONResponse({"error": "admin only"}, status_code=403)
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    if secrets.compare_digest(username, admin_username):
        return JSONResponse({"error": "cannot delete admin"}, status_code=403)
    if not db.delete_auth_user(_conn, username):
        return JSONResponse({"error": "not found"}, status_code=404)
    log.info("user deleted: %s", username)
    return {"ok": True}


# ── Device pairing ─────────────────────────────────────────────────────────────


class PairByCodeBody(BaseModel):
    code: str


class AcceptShareBody(BaseModel):
    code: str


@router.post("/devices/pair")
def pair_by_code(body: PairByCodeBody, request: Request):
    """Claim a pairing code generated by an unpaired Switch. Caller becomes device owner."""
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    if not username:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    device_id = db.claim_pairing_code(_conn, body.code)
    if not device_id:
        return JSONResponse({"error": "invalid or expired pairing code"}, status_code=400)

    db.set_device_owner(_conn, device_id, username)
    db.create_device_token(_conn, device_id, username)
    _conn.execute("UPDATE devices SET deleted_at=NULL WHERE device_id=?", (device_id,))
    db.set_device_config_pending(_conn, device_id)
    device = db.get_device(_conn, device_id)
    log.info("pair-by-code: device=%s owner=%s", device_id, username)
    return {
        "device_id": device_id,
        "display_name": device["display_name"] or None if device else None,
    }


@router.post("/devices/accept-share")
def accept_share(body: AcceptShareBody, request: Request):
    """Accept a share code from a device owner. Grants the caller access to the device."""
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    if not username:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = db.claim_share_code(_conn, body.code)
    if not result:
        return JSONResponse({"error": "invalid or expired share code"}, status_code=400)
    device_id, granted_by = result
    if granted_by == username:
        return JSONResponse({"error": "cannot accept your own share code"}, status_code=400)

    db.grant_device_access(_conn, device_id, username, granted_by)

    # Auto-claim first globally-unclaimed profile; co-claims first profile when all taken
    # so the user always lands with a default (family-trust model — shared save visibility).
    if not db.get_user_has_claim_on_device(_conn, device_id, username):
        _first = db.get_auto_claim_profile(_conn, device_id)
        if _first:
            _profile_id, _profile_name = _first
            db.upsert_device_profile(_conn, device_id, _profile_id, username, _profile_name)
            db.backfill_owner_on_profile_claim(_conn, device_id, _profile_id, username)

    device = db.get_device(_conn, device_id)
    log.info("accept-share: device=%s user=%s granted_by=%s", device_id, username, granted_by)
    return {
        "device_id": device_id,
        "display_name": device["display_name"] or None if device else None,
    }


@router.post("/devices/{device_id}/share")
def generate_share_code(device_id: str, request: Request):
    """Generate a single-use share code for the device (owner only)."""
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    device = db.get_device(_conn, device_id)
    if not device:
        return JSONResponse({"error": "device not found"}, status_code=404)
    if device.get("owner_user_id") != username and not _is_admin(request):
        return JSONResponse({"error": "only the device owner can share"}, status_code=403)

    code = db.create_share_code(_conn, device_id, username)
    log.info("share-code generated: device=%s by=%s", device_id, username)
    return {"code": code, "expires_in": 900}


@router.get("/devices/{device_id}/access")
def list_device_access(device_id: str, request: Request):
    """List users with access to this device (owner or admin only)."""
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    device = db.get_device(_conn, device_id)
    if not device:
        return JSONResponse({"error": "device not found"}, status_code=404)
    if device.get("owner_user_id") != username and not _is_admin(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return {"access": db.list_device_access(_conn, device_id)}


@router.delete("/devices/{device_id}/access/{user_id}")
def revoke_device_access(device_id: str, user_id: str, request: Request):
    """Remove a shared user's access (owner or admin only)."""
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    device = db.get_device(_conn, device_id)
    if not device:
        return JSONResponse({"error": "device not found"}, status_code=404)
    if device.get("owner_user_id") != username and not _is_admin(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    db.revoke_device_access(_conn, device_id, user_id)
    return Response(status_code=204)


class PairDeviceBody(BaseModel):
    user_id: str = ""


def _valid_user_id(user_id: str) -> bool:
    """Check user_id resolves to admin or an auth_users entry."""
    admin_username = db.get_config(_conn, "admin_username") or "admin"
    if user_id == admin_username:
        return True
    return db.get_auth_user(_conn, user_id) is not None


@router.post("/devices/{device_id}/token")
def pair_device(
    device_id: str,
    request: Request,
    body: PairDeviceBody | None = Body(default=None),  # noqa: B008
):
    err = _auth_err(request)
    if err:
        return err
    if not db.get_device(_conn, device_id):
        return JSONResponse({"error": "device not found"}, status_code=404)

    requested_user_id = body.user_id if body else ""
    # Resolve user_id: admin may specify any; non-admin always gets their own
    if _is_admin(request) and requested_user_id:
        user_id = requested_user_id
        if not _valid_user_id(user_id):
            return JSONResponse({"error": "unknown user_id"}, status_code=400)
    else:
        user_id = _current_username(request) or ""
        if not user_id:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    existing = db.get_device_auth(_conn, device_id)
    if existing:
        # Non-admin can only rotate their own device
        if not _is_admin(request) and existing["user_id"] != user_id:
            return JSONResponse({"error": "device belongs to another user"}, status_code=403)
        token = db.rotate_device_token(_conn, device_id)
        log.info("device token rotated: %s → user=%s", device_id, user_id)
    else:
        token = db.create_device_token(_conn, device_id, user_id)
        db.set_device_owner(_conn, device_id, user_id)
        log.info("device paired: %s → user=%s", device_id, user_id)
    # Revive device if it was soft-deleted — re-pairing is the only path back to active
    _conn.execute("UPDATE devices SET deleted_at=NULL WHERE device_id=?", (device_id,))
    # Signal device to poll for token delivery (auto-delivery via device-config endpoint)
    db.set_device_config_pending(_conn, device_id)
    return {"token": token}


@router.delete("/devices/{device_id}/token")
def revoke_device(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    row = db.get_device_auth(_conn, device_id)
    if not row:
        return JSONResponse({"error": "device not paired"}, status_code=404)
    if not _is_admin(request) and row["user_id"] != _current_username(request):
        return JSONResponse({"error": "device belongs to another user"}, status_code=403)
    db.revoke_device_token(_conn, device_id)
    log.info("device token revoked: %s", device_id)
    return Response(status_code=204)


@router.get("/devices/{device_id}/token")
def device_token_status(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not db.get_device(_conn, device_id):
        return JSONResponse({"error": "device not found"}, status_code=404)
    row = db.get_device_auth(_conn, device_id)
    if not row:
        return {"has_token": False, "user_id": None, "last_seen": None}
    # Non-admin can only see their own device pairing
    if not _is_admin(request) and row["user_id"] != _current_username(request):
        return {"has_token": True, "user_id": None, "last_seen": None}
    return {"has_token": True, "user_id": row["user_id"], "last_seen": row["last_seen"]}


# ── Device profile mapping ─────────────────────────────────────────────────────


class ClaimProfileBody(BaseModel):
    user_id: str = ""


@router.get("/devices/{device_id}/profiles")
def list_device_profiles(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not db.get_device(_conn, device_id):
        return JSONResponse({"error": "device not found"}, status_code=404)
    profiles = db.list_device_profiles(_conn, device_id)
    current_user = _current_username(request)
    result = []
    for p in profiles:
        if p["profile_id"] == "0000000000000000":
            continue  # Nintendo sentinel for "no account" — not a real profile
        user_id = p["user_id"]
        # Non-admin: mask other users' user_id (just show "claimed")
        if user_id and user_id != current_user and not _is_admin(request):
            user_id = "__claimed__"
        result.append(
            {
                "profile_id": p["profile_id"],
                "profile_name": p["profile_name"],
                "display_hint": p["display_hint"],
                "user_id": user_id,
            }
        )
    return {"profiles": result}


@router.put("/devices/{device_id}/profiles/{profile_id}")
def claim_profile(
    device_id: str,
    profile_id: str,
    request: Request,
    body: ClaimProfileBody | None = Body(default=None),  # noqa: B008
):
    err = _auth_err(request)
    if err:
        return err
    if not db.get_device(_conn, device_id):
        return JSONResponse({"error": "device not found"}, status_code=404)
    # Profile must be known
    known = db.list_device_profiles(_conn, device_id)
    known_ids = {p["profile_id"] for p in known}
    if profile_id not in known_ids:
        return JSONResponse({"error": "profile not found on this device"}, status_code=404)

    # Resolve target user
    requested = body.user_id if body else ""
    if _is_admin(request) and requested:
        user_id = requested
        if not _valid_user_id(user_id):
            return JSONResponse({"error": "unknown user_id"}, status_code=400)
    else:
        user_id = _current_username(request) or ""
        if not user_id:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    # Snapshot profile_name at claim time
    profile_name = next(
        (p["display_hint"] or p["profile_name"] for p in known if p["profile_id"] == profile_id),
        "",
    )
    # When admin explicitly assigns this profile to another user, remove admin's own
    # auto-claim on that profile so ownership is unambiguous (admin was a placeholder).
    assigner = _current_username(request) or ""
    if _is_admin(request) and user_id != assigner:
        if _conn.execute(
            "SELECT 1 FROM device_profile_map WHERE device_id=? AND profile_id=? AND user_id=?",
            (device_id, profile_id, assigner),
        ).fetchone():
            db.backfill_owner_off_profile_unclaim(_conn, device_id, profile_id, assigner)
            db.delete_device_profile(_conn, device_id, profile_id, assigner)
    # If user is switching from a different profile on this device, null out delivery
    # ownership on the old profile's transactions (T3 — one profile per user per device).
    old_profile = db.get_user_profile_on_device(_conn, device_id, user_id)
    db.upsert_device_profile(_conn, device_id, profile_id, user_id, profile_name)
    db.backfill_owner_on_profile_claim(_conn, device_id, profile_id, user_id)
    if old_profile and old_profile != profile_id:
        db.backfill_owner_off_profile_unclaim(_conn, device_id, old_profile, user_id)
    log.info("profile claimed: device=%s profile=%s user=%s", device_id, profile_id[:8], user_id)
    return {"ok": True}


@router.delete("/devices/{device_id}/profiles/{profile_id}")
def unclaim_profile(
    device_id: str,
    profile_id: str,
    request: Request,
    target_user_id: str | None = None,
):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    # Admin with explicit target_user_id: target that user directly, even if admin also has a claim.
    if _is_admin(request) and target_user_id:
        row = _conn.execute(
            "SELECT user_id FROM device_profile_map"
            " WHERE device_id=? AND profile_id=? AND user_id=?",
            (device_id, profile_id, target_user_id),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "profile not claimed"}, status_code=404)
    else:
        # With multi-claim schema, filter by user_id so only this user's claim is checked.
        row = _conn.execute(
            "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=? AND user_id=?",
            (device_id, profile_id, username),
        ).fetchone()
        if not row:
            if _is_admin(request):
                # No own claim — may unclaim any single claimant; 409 if ambiguous.
                claimants = _conn.execute(
                    "SELECT user_id FROM device_profile_map WHERE device_id=? AND profile_id=?",
                    (device_id, profile_id),
                ).fetchall()
                if len(claimants) > 1:
                    return JSONResponse(
                        {
                            "error": "multiple claimants; specify ?target_user_id=",
                            "claimants": [r["user_id"] for r in claimants],
                        },
                        status_code=409,
                    )
                row = claimants[0] if claimants else None
                if not row:
                    return JSONResponse({"error": "profile not claimed"}, status_code=404)
            else:
                # Return 403 if the profile is claimed but by a different user.
                other = _conn.execute(
                    "SELECT 1 FROM device_profile_map WHERE device_id=? AND profile_id=?",
                    (device_id, profile_id),
                ).fetchone()
                if other:
                    return JSONResponse({"error": "profile not claimed by you"}, status_code=403)
                return JSONResponse({"error": "profile not claimed"}, status_code=404)
    target_user = row["user_id"]
    # Null out delivery ownership before removing the claim — keeps delivery and visibility
    # consistent with the profile-switch path in claim_profile.
    db.backfill_owner_off_profile_unclaim(_conn, device_id, profile_id, target_user)
    db.delete_device_profile(_conn, device_id, profile_id, target_user)
    log.info(
        "profile unclaimed: device=%s profile=%s user=%s", device_id, profile_id[:8], target_user
    )
    return Response(status_code=204)


# ── Dashboard ─────────────────────────────────────────────────────────────────


@router.get("/dashboard")
def dashboard(request: Request):
    err = _auth_err(request)
    if err:
        return err

    username = _current_username(request) or ""

    total_games = _conn.execute(
        "SELECT COUNT(DISTINCT title_id) FROM sync_transactions"
        " WHERE direction='inbound'"
        " AND ("
        "  (COALESCE(user_key,'') != '' AND (source_device_id, user_key) IN ("
        "   SELECT device_id, profile_id FROM device_profile_map WHERE user_id=?))"
        "  OR (COALESCE(user_key,'') = '' AND owner_user_id = ?))",
        (username, username),
    ).fetchone()[0]
    # total_devices computed below after device_rows is fetched via get_devices_for_user
    active_errors = _conn.execute(
        "SELECT COUNT(*) FROM sync_transactions st WHERE st.state='FAILED'"
        " AND NOT EXISTS (SELECT 1 FROM server_config sc"
        " WHERE sc.key = 'ack:' || st.transaction_id)"
        " AND ("
        "  (COALESCE(st.user_key,'') != '' AND (st.source_device_id, st.user_key) IN ("
        "   SELECT device_id, profile_id FROM device_profile_map WHERE user_id=?))"
        "  OR (COALESCE(st.user_key,'') = '' AND st.owner_user_id = ?))",
        (username, username),
    ).fetchone()[0]
    pending_titles = _conn.execute(
        "SELECT COUNT(DISTINCT title_id) FROM sync_transactions"
        " WHERE direction='outbound' AND state='READY_FOR_RESTORE'"
        " AND target_device_id IN ("
        "   SELECT device_id FROM device_access WHERE user_id=?"
        "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)",
        (username, username),
    ).fetchone()[0]

    game_rows = _conn.execute(
        "SELECT title_id, MAX(updated_at) AS last_activity,"
        " SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) AS snapshot_count"
        " FROM sync_transactions"
        " WHERE ("
        "  (COALESCE(user_key,'') != '' AND (source_device_id, user_key) IN ("
        "   SELECT device_id, profile_id FROM device_profile_map WHERE user_id=?))"
        "  OR (COALESCE(user_key,'') = '' AND owner_user_id = ?))"
        " GROUP BY title_id ORDER BY last_activity DESC LIMIT 10",
        (username, username),
    ).fetchall()

    pending_by_dev = {
        r["target_device_id"]: r["n"]
        for r in _conn.execute(
            "SELECT target_device_id, COUNT(DISTINCT title_id) AS n FROM sync_transactions"
            " WHERE direction='outbound' AND state='READY_FOR_RESTORE'"
            " AND target_device_id IN ("
            "   SELECT device_id FROM device_access WHERE user_id=?"
            "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)"
            " GROUP BY target_device_id",
            (username, username),
        ).fetchall()
    }
    failed_count_by_dev_dash = {
        r["target_device_id"]: r["n"]
        for r in _conn.execute(
            "SELECT f.target_device_id, COUNT(DISTINCT f.title_id) AS n FROM sync_transactions f"
            " WHERE f.direction='outbound' AND f.state='FAILED'"
            " AND f.target_device_id IN ("
            "   SELECT device_id FROM device_access WHERE user_id=?"
            "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM sync_transactions c"
            "   WHERE c.title_id=f.title_id AND c.target_device_id=f.target_device_id"
            "     AND c.direction='outbound'"
            "     AND c.state IN ('COMPLETED','READY_FOR_RESTORE','DELIVERING'))"
            " GROUP BY f.target_device_id",
            (username, username),
        ).fetchall()
    }

    event_rows = _conn.execute(
        "SELECT id, event_type, message, title_id, device_id, occurred_at FROM events"
        " WHERE (owner_user_id=?"
        "  OR (owner_user_id IS NULL AND device_id IN ("
        "   SELECT device_id FROM device_access WHERE user_id=?"
        "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)))"
        " ORDER BY id DESC LIMIT 20",
        (username, username, username),
    ).fetchall()

    device_rows = list(db.get_devices_for_user(_conn, username))
    total_devices = sum(1 for r in device_rows if not r.get("is_deleted"))

    return JSONResponse(
        {
            "stats": {
                "total_games": total_games,
                "total_devices": total_devices,
                "active_errors": active_errors,
                "pending_titles": pending_titles,
            },
            "recent_games": [
                {
                    "title_id": r["title_id"],
                    "display_name": _game_display_name(_conn, r["title_id"], username),
                    "icon_url": _game_icon_url(_conn, r["title_id"], username),
                    "last_activity": r["last_activity"],
                    "head_sequence": _head_sequence(_conn, r["title_id"], owner_user_id=username),
                    "status": _game_status(_conn, r["title_id"]),
                    "snapshot_count": r["snapshot_count"],
                }
                for r in game_rows
            ],
            "devices": [
                {
                    "device_id": r["device_id"],
                    "display_name": r["display_name"] or None,
                    "last_seen": r["last_seen"],
                    "pending_count": pending_by_dev.get(r["device_id"], 0),
                    "delivery_failed_count": failed_count_by_dev_dash.get(r["device_id"], 0),
                    "is_deleted": bool(r.get("is_deleted", False)),
                }
                for r in device_rows
            ],
            "recent_events": [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "summary": r["message"],
                    "title_id": r["title_id"],
                    "icon_url": _game_icon_url(_conn, r["title_id"], username)
                    if r["title_id"]
                    else None,
                    "device_id": r["device_id"],
                    "created_at": r["occurred_at"],
                }
                for r in event_rows
            ],
            "server_now": int(datetime.now(UTC).timestamp() * 1000),
        }
    )


# ── Games ─────────────────────────────────────────────────────────────────────


@router.get("/games")
def list_games(request: Request):
    err = _auth_err(request)
    if err:
        return err

    username = _current_username(request) or ""
    rows = _conn.execute(
        "SELECT * FROM ("
        "  SELECT title_id, MAX(updated_at) AS last_activity, COUNT(*) AS snapshot_count"
        "  FROM sync_transactions WHERE direction='inbound' AND owner_user_id=?"
        "  GROUP BY title_id"
        "  UNION"
        "  SELECT dig.title_id, NULL AS last_activity, 0 AS snapshot_count"
        "  FROM device_installed_games dig"
        "  JOIN devices d ON d.device_id = dig.device_id"
        "  WHERE d.owner_user_id=?"
        "    AND dig.title_id NOT IN ("
        "      SELECT title_id FROM sync_transactions"
        "      WHERE direction='inbound' AND owner_user_id=?"
        "    )"
        ") ORDER BY last_activity IS NULL, last_activity DESC",
        (username, username, username),
    ).fetchall()
    dev_counts = {
        r["title_id"]: r["dc"]
        for r in _conn.execute(
            "SELECT title_id, COUNT(DISTINCT source_device_id) AS dc"
            " FROM sync_transactions WHERE direction='inbound' AND owner_user_id=?"
            " GROUP BY title_id",
            (username,),
        ).fetchall()
    }

    return JSONResponse(
        {
            "games": [
                {
                    "title_id": r["title_id"],
                    "display_name": _game_display_name(_conn, r["title_id"], username),
                    "icon_url": _game_icon_url(_conn, r["title_id"], username),
                    "snapshot_count": r["snapshot_count"],
                    "device_count": dev_counts.get(r["title_id"], 0),
                    "last_activity": r["last_activity"],
                    "status": _game_status(_conn, r["title_id"]),
                }
                for r in rows
            ]
        }
    )


@router.get("/games/{title_id}")
def game_detail(title_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _TITLE_RE.match(title_id):
        return JSONResponse({"error": "invalid title_id"}, status_code=400)

    username = _current_username(request) or ""
    # Visibility is purely claim-based (T1): saves are visible only when the user has
    # claimed the device profile that created them. owner_user_id drives delivery; the
    # claim table drives UI visibility. No owned_devices fallback (T2).
    snaps = _conn.execute(
        "SELECT transaction_id, snapshot_sequence, source_device_id, sha256,"
        " parent_sequence_num, has_conflict, state, created_at, owner_user_id,"
        " user_key, user_display"
        " FROM sync_transactions"
        " WHERE title_id=? AND direction='inbound'"
        " AND state NOT IN ('FAILED', 'DEDUPED', 'UPLOADING')"
        " AND NOT (state='COMPLETED' AND sha256 IS NULL)"
        " AND ("
        "  (COALESCE(user_key,'') != '' AND (source_device_id, user_key) IN ("
        "   SELECT device_id, profile_id FROM device_profile_map WHERE user_id=?))"
        "  OR (COALESCE(user_key,'') = '' AND owner_user_id = ?))"
        " ORDER BY created_at DESC, snapshot_sequence DESC NULLS LAST",
        (title_id, username, username),
    ).fetchall()

    if not snaps:
        # Only 404 when the game exists somewhere in the system but not for this user.
        # If the title_id is completely unknown, return the empty 200 shell (NO_DATA).
        game_exists_globally = _conn.execute(
            "SELECT 1 FROM sync_transactions WHERE title_id=? LIMIT 1",
            (title_id,),
        ).fetchone()
        if game_exists_globally:
            has_access = _conn.execute(
                "SELECT 1 FROM sync_transactions WHERE title_id=? AND owner_user_id=?"
                " UNION "
                "SELECT 1 FROM ("
                "  SELECT device_id FROM device_installed_games WHERE title_id=?"
                "  UNION SELECT source_device_id FROM sync_transactions WHERE title_id=?"
                "  UNION SELECT target_device_id FROM sync_transactions WHERE title_id=?"
                ") AS t WHERE t.device_id IN ("
                "  SELECT device_id FROM device_profile_map WHERE user_id=?"
                "  UNION SELECT device_id FROM device_access WHERE user_id=?"
                "  UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)",
                (title_id, username, title_id, title_id, title_id, username, username, username),
            ).fetchone()
            if not has_access:
                return JSONResponse({"error": "not found"}, status_code=404)

    all_dev_rows = list(db.get_all_devices(_conn))
    dev_names = {r["device_id"]: (r["display_name"] or None) for r in all_dev_rows}
    dev_client_type = {r["device_id"]: (r["client_type"] or "") for r in all_dev_rows}
    head_seq = _head_sequence(_conn, title_id, owner_user_id=username)

    claimed_devices = {
        r["device_id"]
        for r in _conn.execute(
            "SELECT device_id FROM device_profile_map WHERE user_id=?", (username,)
        ).fetchall()
    }
    shared_devices = {
        r["device_id"]
        for r in _conn.execute(
            "SELECT device_id FROM device_access WHERE user_id=?", (username,)
        ).fetchall()
    }
    owned_devices = {
        r["device_id"]
        for r in _conn.execute(
            "SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL",
            (username,),
        ).fetchall()
    }
    visible_devices = claimed_devices | shared_devices | owned_devices
    device_ids = {s["source_device_id"] for s in snaps} & visible_devices
    for row in _conn.execute(
        "SELECT DISTINCT target_device_id FROM sync_transactions"
        " WHERE title_id=? AND direction='outbound'"
        " AND target_device_id IN ("
        "  SELECT device_id FROM device_profile_map WHERE user_id=?"
        "  UNION SELECT device_id FROM device_access WHERE user_id=?"
        "  UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)",
        (title_id, username, username, username),
    ).fetchall():
        device_ids.add(row["target_device_id"])

    # Virtual devices (e.g. RomM) are not in device_profile_map — include via transactions.
    for row in _conn.execute(
        "SELECT DISTINCT target_device_id FROM sync_transactions"
        " WHERE title_id=? AND direction='outbound'"
        " AND target_device_id IN (SELECT device_id FROM devices"
        "   WHERE owner_user_id=? AND client_type='romm' AND deleted_at IS NULL)",
        (title_id, username),
    ).fetchall():
        device_ids.add(row["target_device_id"])

    # Always include the user's active romm device — even when it has no transactions yet
    # (e.g. source_id was renamed; new device hasn't received a push for this title yet).
    for row in _conn.execute(
        "SELECT device_id FROM devices"
        " WHERE owner_user_id=? AND client_type='romm' AND deleted_at IS NULL",
        (username,),
    ).fetchall():
        device_ids.add(row["device_id"])

    # Always include devices that have this game in their installed catalog —
    # so "No save yet" games still show which device reported them.
    for row in _conn.execute(
        "SELECT device_id FROM device_installed_games"
        " WHERE title_id=? AND device_id IN ("
        "  SELECT device_id FROM device_profile_map WHERE user_id=?"
        "  UNION SELECT device_id FROM device_access WHERE user_id=?"
        "  UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)",
        (title_id, username, username, username),
    ).fetchall():
        device_ids.add(row["device_id"])

    dev_last_seen = {
        r["device_id"]: r["last_seen"]
        for r in _conn.execute("SELECT device_id, last_seen FROM devices").fetchall()
    }
    dev_hardware_type = {r["device_id"]: (r["hardware_type"] or None) for r in all_dev_rows}

    # VIEW MODEL: sync prefs for display only — not authoritative for sync decisions
    prefs_rows = _conn.execute(
        "SELECT key, value FROM server_config WHERE key LIKE 'sync_prefs:%'"
    ).fetchall()
    all_dev_prefs: dict[str, dict] = {}
    for _prow in prefs_rows:
        _did = _prow["key"][len("sync_prefs:") :]
        try:
            all_dev_prefs[_did] = json.loads(_prow["value"])
        except Exception:
            all_dev_prefs[_did] = {}

    # VIEW MODEL: last inbound sync timestamp per device for this title
    last_synced_rows = _conn.execute(
        "SELECT source_device_id, MAX(created_at) AS ts FROM sync_transactions"
        " WHERE title_id=? AND direction='inbound' AND state IN ('READY_FOR_RESTORE','COMPLETED')"
        " GROUP BY source_device_id",
        (title_id,),
    ).fetchall()
    dev_last_synced = {r["source_device_id"]: r["ts"] for r in last_synced_rows}
    # Fallback for romm devices: they receive saves (outbound) but never upload (inbound)
    romm_synced_rows = _conn.execute(
        "SELECT target_device_id, MAX(created_at) AS ts FROM sync_transactions"
        " WHERE title_id=? AND direction='outbound' AND state='COMPLETED'"
        " AND target_device_id IN (SELECT device_id FROM devices WHERE client_type='romm')"
        " GROUP BY target_device_id",
        (title_id,),
    ).fetchall()
    for _row in romm_synced_rows:
        if _row["target_device_id"] not in dev_last_synced:
            dev_last_synced[_row["target_device_id"]] = _row["ts"]

    # VIEW MODEL: which devices have a pending outbound delivery for this title
    pending_rows = _conn.execute(
        "SELECT DISTINCT target_device_id FROM sync_transactions"
        " WHERE title_id=? AND direction='outbound' AND state='READY_FOR_RESTORE'",
        (title_id,),
    ).fetchall()
    pending_devices = {r["target_device_id"] for r in pending_rows}

    # VIEW MODEL: latest FAILED outbound txn per device — for UI single retry
    # Exclude ghosts: FAILED rows where a COMPLETED delivery exists for same title+target
    failed_txn_rows = _conn.execute(
        "SELECT f.target_device_id, f.transaction_id FROM sync_transactions f"
        " WHERE f.title_id=? AND f.direction='outbound' AND f.state='FAILED'"
        " AND NOT EXISTS ("
        "   SELECT 1 FROM sync_transactions c"
        "   WHERE c.title_id=f.title_id AND c.target_device_id=f.target_device_id"
        "     AND c.direction='outbound' AND c.state='COMPLETED')"
        " ORDER BY f.created_at DESC",
        (title_id,),
    ).fetchall()
    failed_txn_by_device: dict[str, str] = {}
    for _frow in failed_txn_rows:
        if _frow["target_device_id"] not in failed_txn_by_device:
            failed_txn_by_device[_frow["target_device_id"]] = _frow["transaction_id"]

    def _matrix_entry(did: str) -> dict:
        # VIEW MODEL ONLY — do not use for sync decisions
        state = _effective_sync_state(
            _conn,
            username,
            did,
            dev_client_type.get(did, ""),
            title_id,
            head_seq,
        )
        return {
            "device_id": did,
            "device_name": dev_names.get(did),
            "last_seen": dev_last_seen.get(did),
            "hardware_type": dev_hardware_type.get(did),
            "client_type": dev_client_type.get(did) or None,
            "sync_enabled": all_dev_prefs.get(did, {}).get(title_id, True),
            "pending_delivery": did in pending_devices,
            "last_synced_at": dev_last_synced.get(did),
            "failed_transaction_id": failed_txn_by_device.get(did),
            **state,
        }

    return JSONResponse(
        {
            "title_id": title_id,
            "display_name": _game_display_name(_conn, title_id, username),
            "icon_url": _game_icon_url(_conn, title_id, username),
            "rom_id": db.get_romm_rom_id(_conn, username, title_id),
            "status": _game_status(_conn, title_id),
            "head_sequence": head_seq,
            "snapshots": [
                {
                    "transaction_id": s["transaction_id"],
                    "sequence_num": s["snapshot_sequence"],
                    "device_id": s["source_device_id"],
                    "device_name": dev_names.get(s["source_device_id"]),
                    "ingest_timestamp": s["created_at"],
                    "sha256": s["sha256"] or "",
                    "parent_sequence": s["parent_sequence_num"],
                    "state": _STATE_MAP.get(s["state"], "RECEIVED"),
                    "is_head": s["snapshot_sequence"] is not None
                    and s["snapshot_sequence"] == head_seq,
                    "archive_size_bytes": _archive_size(s["transaction_id"]),
                    "owner_user_id": s["owner_user_id"],
                    "device_user_key": s["user_key"] or "",
                    "device_user_display": s["user_display"] or "",
                }
                for s in snaps
            ],
            "device_sync_matrix": [_matrix_entry(did) for did in sorted(device_ids)],
        }
    )


# ── Events ────────────────────────────────────────────────────────────────────


@router.get("/events")
def list_events(request: Request, limit: int = 100):
    err = _auth_err(request)
    if err:
        return err
    limit = min(max(limit, 1), 500)
    username = _current_username(request) or ""
    rows = _conn.execute(
        "SELECT id, event_type, message, title_id, device_id, occurred_at FROM events"
        " WHERE (owner_user_id=?"
        " OR (owner_user_id IS NULL AND device_id IN ("
        "  SELECT device_id FROM device_access WHERE user_id=?"
        "  UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)))"
        " ORDER BY id DESC LIMIT ?",
        (username, username, username, limit),
    ).fetchall()
    return JSONResponse(
        {
            "events": [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "summary": r["message"],
                    "title_id": r["title_id"],
                    "icon_url": _game_icon_url(_conn, r["title_id"], username)
                    if r["title_id"]
                    else None,
                    "device_id": r["device_id"],
                    "created_at": r["occurred_at"],
                }
                for r in rows
            ]
        }
    )


# ── Errors ────────────────────────────────────────────────────────────────────


@router.get("/errors")
def list_errors(request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    rows = _conn.execute(
        "SELECT transaction_id, direction, title_id, source_device_id,"
        " target_device_id, state, updated_at"
        " FROM sync_transactions WHERE state='FAILED'"
        " AND (owner_user_id=?"
        "  OR (direction='outbound' AND target_device_id IN ("
        "   SELECT device_id FROM device_access WHERE user_id=?"
        "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)))"
        " ORDER BY updated_at DESC",
        (username, username, username),
    ).fetchall()
    result = []
    for r in rows:
        dev_id = r["source_device_id"] if r["direction"] == "inbound" else r["target_device_id"]
        dev_row = _conn.execute(
            "SELECT display_name, hardware_type, client_type FROM devices WHERE device_id=?",
            (dev_id,),
        ).fetchone()
        result.append(
            {
                "transaction_id": r["transaction_id"],
                "direction": r["direction"],
                "title_id": r["title_id"],
                "device_id": dev_id,
                "game_name": _game_display_name(_conn, r["title_id"], username)
                if r["title_id"]
                else None,
                "icon_url": _game_icon_url(_conn, r["title_id"], username)
                if r["title_id"]
                else None,
                "device_name": dev_row["display_name"] or None if dev_row else None,
                "hardware_type": dev_row["hardware_type"] or None if dev_row else None,
                "client_type": dev_row["client_type"] or None if dev_row else None,
                "state": r["state"],
                "created_at": r["updated_at"],
                "acknowledged": bool(db.get_config(_conn, f"ack:{r['transaction_id']}")),
            }
        )
    return JSONResponse({"errors": result})


@router.post("/errors/{transaction_id}/acknowledge")
def acknowledge_error(transaction_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    row = _conn.execute(
        "SELECT 1 FROM sync_transactions WHERE transaction_id=? AND state='FAILED'",
        (transaction_id,),
    ).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.set_config(_conn, f"ack:{transaction_id}", "1")
    return {"ok": True}


# ── Labels ────────────────────────────────────────────────────────────────────


class DeviceLabelBody(BaseModel):
    display_name: str


class GameLabelBody(BaseModel):
    display_name: str


@router.put("/labels/device/{device_id}")
def label_device(device_id: str, body: DeviceLabelBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    db.rename_device(_conn, device_id, body.display_name)
    return {"ok": True}


@router.delete("/labels/device/{device_id}")
def unlabel_device(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    _conn.execute("UPDATE devices SET display_name='' WHERE device_id=?", (device_id,))
    return Response(status_code=204)


@router.put("/labels/game/{title_id}")
def label_game(title_id: str, body: GameLabelBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _TITLE_RE.match(title_id):
        return JSONResponse({"error": "invalid title_id"}, status_code=400)
    _conn.execute(
        "INSERT INTO labels (entity_type, entity_id, label) VALUES ('game', ?, ?)"
        " ON CONFLICT(entity_type, entity_id) DO UPDATE SET label=excluded.label",
        (title_id, body.display_name),
    )
    return {"ok": True}


@router.delete("/labels/game/{title_id}")
def unlabel_game(title_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _TITLE_RE.match(title_id):
        return JSONResponse({"error": "invalid title_id"}, status_code=400)
    _conn.execute("DELETE FROM labels WHERE entity_type='game' AND entity_id=?", (title_id,))
    return Response(status_code=204)


# ── Devices ───────────────────────────────────────────────────────────────────


@router.get("/devices")
def list_devices(request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    rows = list(db.get_devices_for_user(_conn, username))

    pending_by_dev = {
        r["target_device_id"]: r["n"]
        for r in _conn.execute(
            "SELECT target_device_id, COUNT(DISTINCT title_id) AS n FROM sync_transactions"
            " WHERE direction='outbound' AND state='READY_FOR_RESTORE'"
            " AND target_device_id IN (SELECT device_id FROM device_access WHERE user_id=?"
            "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)"
            " GROUP BY target_device_id",
            (username, username),
        ).fetchall()
    }
    failed_count_by_dev = {
        r["target_device_id"]: r["n"]
        for r in _conn.execute(
            "SELECT f.target_device_id, COUNT(DISTINCT f.title_id) AS n FROM sync_transactions f"
            " WHERE f.direction='outbound' AND f.state='FAILED'"
            " AND f.target_device_id IN (SELECT device_id FROM device_access WHERE user_id=?"
            "   UNION SELECT device_id FROM devices WHERE owner_user_id=? AND deleted_at IS NULL)"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM sync_transactions c"
            "   WHERE c.title_id=f.title_id AND c.target_device_id=f.target_device_id"
            "     AND c.direction='outbound'"
            "     AND c.state IN ('COMPLETED','READY_FOR_RESTORE','DELIVERING'))"
            " GROUP BY f.target_device_id",
            (username, username),
        ).fetchall()
    }
    return JSONResponse(
        {
            "devices": [
                {
                    "device_id": r["device_id"],
                    "display_name": r["display_name"] or None,
                    "last_seen": r["last_seen"],
                    "hardware_type": r["hardware_type"],
                    "client_type": r["client_type"],
                    "owner_user_id": r.get("owner_user_id"),
                    "pending_count": pending_by_dev.get(r["device_id"], 0),
                    "delivery_failed_count": failed_count_by_dev.get(r["device_id"], 0),
                    "is_deleted": bool(r.get("is_deleted", False)),
                    "default_profile_uid": r.get("default_profile_uid") or None,
                    "default_profile_name": (
                        db.get_profile_display_name(_conn, r["device_id"], r["default_profile_uid"])
                        if r.get("default_profile_uid")
                        else None
                    ),
                }
                for r in rows
            ]
        }
    )


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    row = _conn.execute(
        "SELECT owner_user_id FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()
    if not row:
        return JSONResponse({"error": "device not found"}, status_code=404)
    if row["owner_user_id"] != username and not _is_admin(request):
        return JSONResponse({"error": "only the device owner can remove it"}, status_code=403)
    # Revoke token first so the device can't re-register itself via device-config
    db.revoke_device_token(_conn, device_id)
    _conn.execute("DELETE FROM device_access WHERE device_id=?", (device_id,))
    _conn.execute("DELETE FROM device_pairing_codes WHERE device_id=?", (device_id,))
    db.soft_delete_device(_conn, device_id)
    log.info("device deleted: %s", device_id)
    return Response(status_code=204)


class DefaultProfileBody(BaseModel):
    profile_uid: str | None = None


@router.put("/devices/{device_id}/default-profile")
def set_default_profile(device_id: str, body: DefaultProfileBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    device = db.get_device(_conn, device_id)
    if not device:
        return JSONResponse({"error": "device not found"}, status_code=404)
    if not db.user_has_device_access(_conn, device_id, username) and not _is_admin(request):
        return JSONResponse({"error": "device not found"}, status_code=404)
    is_owner = device.get("owner_user_id") == username or _is_admin(request)
    if is_owner:
        db.set_device_default_profile(_conn, device_id, body.profile_uid or None)
    else:
        db.set_user_device_default_profile(_conn, device_id, username, body.profile_uid or None)
    log.info(
        "default profile set: device=%s profile=%s by=%s", device_id, body.profile_uid, username
    )
    return {"ok": True}


@router.get("/devices/{device_id}/games")
def device_games(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    try:
        return _device_games_inner(device_id, username)
    except Exception as exc:
        log.exception("device_games: CRASH device=%s user=%s: %s", device_id, username, exc)
        raise


def _device_games_inner(device_id: str, username: str):
    rows = _conn.execute(
        "SELECT DISTINCT title_id FROM sync_transactions"
        " WHERE owner_user_id=?"
        " AND ("
        "   source_device_id=?"
        "   OR (target_device_id=? AND state NOT IN ('FAILED','CANCELLED','SUPERSEDED'))"
        " )"
        " UNION"
        " SELECT title_id FROM device_installed_games WHERE device_id=?"
        " ORDER BY title_id",
        (username, device_id, device_id, device_id),
    ).fetchall()
    prefs_json = db.get_config(_conn, f"sync_prefs:{device_id}")
    prefs = json.loads(prefs_json) if prefs_json else {}
    dev_row = db.get_device(_conn, device_id)
    device_client_type = dev_row["client_type"] if dev_row else ""
    games = []
    for r in rows:
        title_id = r["title_id"]
        head_seq = _head_sequence(_conn, title_id, owner_user_id=username)
        sync_info = _effective_sync_state(
            _conn,
            username,
            device_id,
            device_client_type,
            title_id,
            head_seq,
        )
        last_row = _conn.execute(
            "SELECT MAX(created_at) AS ts FROM sync_transactions"
            " WHERE source_device_id=? AND title_id=?"
            " AND direction='inbound' AND state IN ('READY_FOR_RESTORE','COMPLETED')",
            (device_id, title_id),
        ).fetchone()
        last_synced_at = last_row["ts"] if last_row else None
        if not last_synced_at and device_client_type == "romm":
            fallback = _conn.execute(
                "SELECT MAX(created_at) AS ts FROM sync_transactions"
                " WHERE title_id=? AND direction='outbound' AND state='COMPLETED'"
                " AND target_device_id IN"
                "  (SELECT device_id FROM devices WHERE owner_user_id=? AND client_type='romm')",
                (title_id, username),
            ).fetchone()
            last_synced_at = fallback["ts"] if fallback else None
        games.append(
            {
                "title_id": title_id,
                "display_name": _game_display_name(_conn, title_id, username),
                "icon_url": _game_icon_url(_conn, title_id, username),
                "sync_enabled": prefs.get(title_id, True),
                "sync_state": sync_info["sync_state"],
                "pending_delivery": _has_pending_delivery(_conn, device_id, title_id),
                "last_synced_at": last_synced_at,
            }
        )
    log.info("device_games: device=%s games=%d", device_id, len(games))
    result: dict = {"games": games}
    if device_client_type == "romm":
        import romm_index as _ri

        status = _ri.scan_status()
        result["scan_running"] = status["running"]
        result["scan_queued"] = status["queued"]
        result["scan_error"] = status["last_error"]
    return JSONResponse(result)


class SyncPrefItem(BaseModel):
    title_id: str
    enabled: bool


class SyncPrefBatch(BaseModel):
    preferences: list[SyncPrefItem]


@router.post("/devices/{device_id}/games/sync/batch")
def set_sync_prefs(device_id: str, body: SyncPrefBatch, request: Request):
    err = _auth_err(request)
    if err:
        return err
    prefs_json = db.get_config(_conn, f"sync_prefs:{device_id}")
    prefs = json.loads(prefs_json) if prefs_json else {}
    for item in body.preferences:
        prefs[item.title_id] = item.enabled
    db.set_config(_conn, f"sync_prefs:{device_id}", json.dumps(prefs))
    for item in body.preferences:
        if not item.enabled:
            n = db.cancel_outbound_for_title(_conn, device_id, item.title_id)
            if n:
                db.log_event(
                    _conn,
                    "OUTBOUND_CANCELLED",
                    f"{n} row(s) cancelled — user disabled title",
                    title_id=item.title_id,
                    device_id=device_id,
                )
    return {"ok": True}


# ── Snapshot management ───────────────────────────────────────────────────────


class PushTarget(BaseModel):
    device_id: str
    target_profile_uid: str | None = None


class PushBody(BaseModel):
    targets: list[PushTarget] = []


@router.post("/snapshots/{transaction_id}/push")
def push_snapshot(transaction_id: str, body: PushBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    txn = db.get_transaction(_conn, transaction_id)
    if not txn:
        return JSONResponse({"error": "not found"}, status_code=404)
    _pushable = {"READY_FOR_RESTORE", "COMPLETED"}
    if txn["direction"] != "inbound" or txn["state"] not in _pushable:
        return JSONResponse(
            {"error": f"snapshot not pushable (state={txn['state']})"}, status_code=400
        )
    if body.targets:
        targets = list({t.device_id: t for t in body.targets}.values())
    else:
        targets = [
            PushTarget(device_id=d["device_id"])
            for d in db.get_all_devices(_conn)
            if d["device_id"] != txn["source_device_id"]
        ]
    if not targets:
        return JSONResponse({"error": "no eligible target devices"}, status_code=400)
    outbound_ids = []
    for push_target in targets:
        device_id = push_target.device_id
        existing = db.get_active_outbound_for_snapshot(
            _conn, txn["snapshot_sequence"], txn["title_id"], device_id
        )
        if existing:
            outbound_ids.append(existing["transaction_id"])
            continue
        # Resolve target profile: explicit override → device default → None
        target_profile = (
            push_target.target_profile_uid
            or db.get_last_inbound_user_key(_conn, device_id, txn["title_id"], username)
            or db.get_user_device_default_profile(_conn, device_id, username)
        )
        db.upsert_device(_conn, device_id)
        db.supersede_active_outbound(
            _conn, device_id, txn["title_id"], txn.get("owner_user_id") or ""
        )
        oid = db.create_outbound_transaction(
            _conn,
            transaction_id,
            device_id,
            target_profile_uid=target_profile,
        )
        db.log_event(
            _conn,
            "OUTBOUND_CREATED",
            f"ui push → {device_id}",
            title_id=txn["title_id"],
            device_id=device_id,
            transaction_id=oid,
        )
        outbound_ids.append(oid)
    log.info("ui push txn=%s → %d device(s)", transaction_id[:8], len(outbound_ids))
    return JSONResponse({"ok": True, "outbound_ids": outbound_ids}, status_code=202)


@router.post("/devices/{device_id}/restore-all")
def device_restore_all(device_id: str, request: Request):
    """Queue the latest available save for every title that has any synced snapshot.

    Restores ALL titles with a HEAD — including ones the device is already current on
    and saves the device itself uploaded. Intended for full device restore (e.g. after
    reset). supersede_active_outbound cancels any in-progress delivery before re-queuing.
    """
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request) or ""
    if not _DEVICE_RE.match(device_id):
        return JSONResponse({"error": "invalid device_id"}, status_code=400)

    target_profile = db.get_user_device_default_profile(_conn, device_id, username)

    # Only restore titles the device actually has installed — prevents inject failures
    # for games that exist on another device but not this one.
    # Skip the catalog filter if the device has never reported a catalog (backwards compat).
    has_catalog = (
        _conn.execute(
            "SELECT 1 FROM device_installed_games WHERE device_id=? LIMIT 1", (device_id,)
        ).fetchone()
        is not None
    )
    catalog_clause = (
        "   AND EXISTS ("
        "     SELECT 1 FROM device_installed_games dig"
        "     WHERE dig.device_id = ? AND dig.title_id = st.title_id"
        "   )"
        if has_catalog
        else ""
    )

    # Find the HEAD for every title that has any synced snapshot — no exclusions
    # for source device or existing deliveries. supersede_active_outbound handles
    # cancelling stale deliveries before each new one is queued.
    rows = _conn.execute(
        "SELECT st.transaction_id, st.title_id, COALESCE(st.user_key,'') AS user_key,"
        " st.snapshot_sequence, st.owner_user_id"
        " FROM sync_transactions st"
        " WHERE st.direction = 'inbound'"
        "   AND st.state = 'READY_FOR_RESTORE'"
        "   AND st.has_conflict = 0"
        "   AND st.preservation = 0"
        "   AND st.snapshot_sequence = ("
        "     SELECT MAX(st2.snapshot_sequence)"
        "     FROM sync_transactions st2"
        "     WHERE st2.title_id = st.title_id"
        "       AND COALESCE(st2.owner_user_id,'') = COALESCE(st.owner_user_id,'')"
        "       AND st2.direction = 'inbound'"
        "       AND st2.state = 'READY_FOR_RESTORE'"
        "       AND st2.has_conflict = 0"
        "       AND st2.preservation = 0"
        "   )" + catalog_clause,
        ((device_id,) if has_catalog else ()),
    ).fetchall()

    queued = 0
    for row in rows:
        try:
            db.supersede_active_outbound(
                _conn, device_id, row["title_id"], row["owner_user_id"] or ""
            )
            oid = db.create_outbound_transaction(
                _conn,
                row["transaction_id"],
                device_id,
                target_profile_uid=target_profile,
            )
            if oid:
                db.log_event(
                    _conn,
                    "OUTBOUND_CREATED",
                    f"restore-all → {device_id}",
                    title_id=row["title_id"],
                    device_id=device_id,
                    transaction_id=oid,
                    owner_user_id=row["owner_user_id"],
                )
                queued += 1
        except Exception as exc:
            log.warning("restore_all: %s %s: %s", device_id, row["title_id"][:8], exc)

    log.info("restore-all device=%s queued=%d", device_id, queued)
    return {"ok": True, "queued": queued}


@router.post("/outbounds/{transaction_id}/retry")
def retry_outbound(transaction_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    txn = db.retry_outbound(_conn, transaction_id)
    if txn is None:
        return JSONResponse({"error": "not found or not retryable"}, status_code=404)
    db.log_event(
        _conn,
        "OUTBOUND_RETRY",
        "ui retry",
        title_id=txn["title_id"],
        device_id=txn["target_device_id"],
        transaction_id=transaction_id,
    )
    log.info("ui retry outbound=%s", transaction_id[:8])
    return JSONResponse({"ok": True, "transaction_id": transaction_id}, status_code=200)


@router.post("/devices/{device_id}/outbounds/retry-failed")
def retry_failed_outbounds(device_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _DEVICE_RE.match(device_id):
        return JSONResponse({"error": "invalid device_id"}, status_code=400)
    retried = db.retry_all_failed_outbounds(_conn, device_id)
    for r in retried:
        db.log_event(
            _conn,
            "OUTBOUND_RETRY",
            "ui retry-all",
            title_id=r["title_id"],
            device_id=device_id,
            transaction_id=r["txn_id"],
        )
    if retried:
        log.info("ui retry-all device=%s count=%d", device_id[:12], len(retried))
    return JSONResponse({"ok": True, "retried": len(retried)})


_TXN_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DL_UNSAFE_RE = _re.compile(r'[/\\:*?"<>|\x00-\x1f]')


@router.get("/snapshots/{transaction_id}/download")
def download_snapshot(transaction_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    if not _TXN_RE.match(transaction_id):
        return JSONResponse({"error": "invalid transaction_id"}, status_code=400)
    txn = db.get_transaction(_conn, transaction_id)
    if not txn or not txn.get("snapshot_path"):
        return JSONResponse({"error": "not found"}, status_code=404)
    archive = Path(txn["snapshot_path"])
    if not archive.exists():
        return JSONResponse({"error": "archive missing"}, status_code=404)
    raw_name = titledb.resolve_game_name(txn["title_id"], _conn) or txn["title_id"]
    safe_name = _DL_UNSAFE_RE.sub("", raw_name).strip()[:120] or "save"
    ts_str = ""
    try:
        from datetime import datetime

        ts_str = (
            datetime.fromisoformat((txn["created_at"] or "").replace("Z", "+00:00"))
            .astimezone(UTC)
            .strftime("%Y-%m-%d_%H-%M-%S")
        )
    except Exception:
        pass
    filename = f"{safe_name} [{ts_str}].zip" if ts_str else f"{safe_name}.zip"
    return FileResponse(archive, media_type="application/zip", filename=filename)


@router.delete("/snapshots/{transaction_id}")
def delete_snapshot(transaction_id: str, request: Request):
    err = _auth_err(request)
    if err:
        return err
    path = db.delete_snapshot(_conn, transaction_id)
    if path is None:
        return JSONResponse({"error": "not found or not deletable"}, status_code=404)
    if path:  # empty string = no archive file (duplicate save or already cleaned up)
        archive = Path(path)
        archive.unlink(missing_ok=True)
        try:
            archive.parent.rmdir()
        except OSError:
            pass
    log.info("snapshot deleted: %s", transaction_id[:8])
    return {"deleted": transaction_id}


# ── Settings ──────────────────────────────────────────────────────────────────


class RommSettingsBody(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    api_key: str | None = None
    source_id: str | None = None


@router.get("/settings/romm")
def get_romm_settings(request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request)
    enabled_val = db.get_user_config(_conn, username, "romm_enabled")
    host = db.get_user_config(_conn, username, "romm_host") or ""
    has_key = bool(db.get_user_config(_conn, username, "romm_api_key"))
    source_id = db.get_user_config(_conn, username, "romm_source_id") or f"romm:{username}"
    romm_username = db.get_user_config(_conn, username, "romm_username") or None
    romm_connect_status = db.get_user_config(_conn, username, "romm_connect_status") or ""
    romm_connect_detail = db.get_user_config(_conn, username, "romm_connect_detail") or ""
    return JSONResponse(
        {
            "enabled": enabled_val == "1",
            "host": host,
            "has_api_key": has_key,
            "source_id": source_id,
            "romm_username": romm_username,
            "romm_connect_status": romm_connect_status,
            "romm_connect_detail": romm_connect_detail,
        }
    )


@router.put("/settings/romm")
def put_romm_settings(body: RommSettingsBody, request: Request):
    err = _auth_err(request)
    if err:
        return err
    username = _current_username(request)
    # Read current device_id BEFORE any writes so we can retire it if it changes
    old_device_id = db.get_user_config(_conn, username, "romm_source_id")
    romm_device_id = old_device_id or f"romm:{username}"
    if body.source_id is not None and body.source_id.strip():
        romm_device_id = body.source_id.strip()
        db.set_user_config(_conn, username, "romm_source_id", romm_device_id)
    if body.enabled is not None:
        db.set_user_config(_conn, username, "romm_enabled", "1" if body.enabled else "0")
        db.upsert_virtual_device(
            _conn, romm_device_id, "RomM", "romm-vsc", client_type="romm", owner_user_id=username
        )
        if body.enabled:
            _conn.execute(
                "UPDATE devices SET deleted_at=NULL WHERE device_id=? AND client_type='romm'",
                (romm_device_id,),
            )
            db.sync_romm_catalog_to_device(_conn, username, romm_device_id)
            # Only trigger index here when this is a pure toggle-on (no credentials
            # being updated). If host/api_key are also in the request, the credential
            # verification path (below) handles the index trigger after auth succeeds.
            if body.host is None and body.api_key is None:
                import romm_index as _romm_index

                _romm_index.request_index_refresh()
                _romm_index.maybe_run_index()
        else:
            _conn.execute(
                "UPDATE devices SET deleted_at=? WHERE device_id=? AND client_type='romm'",
                (db._now(), romm_device_id),
            )
    if body.host is not None:
        db.set_user_config(_conn, username, "romm_host", body.host.rstrip("/"))
    if body.api_key is not None:
        db.set_user_config(_conn, username, "romm_api_key", body.api_key)
    db.upsert_virtual_device(
        _conn, romm_device_id, "RomM", "romm-vsc", client_type="romm", owner_user_id=username
    )
    # Retire the previous device if the source_id changed (avoids duplicates)
    if old_device_id and old_device_id != romm_device_id:
        _conn.execute(
            "UPDATE devices SET deleted_at=?"
            " WHERE device_id=? AND owner_user_id=? AND client_type='romm'",
            (db._now(), old_device_id, username),
        )
    has_host = bool(db.get_user_config(_conn, username, "romm_host"))
    has_key = bool(db.get_user_config(_conn, username, "romm_api_key"))
    fresh_username: str | None = None
    fresh_status = ""
    fresh_detail = ""
    if body.host is not None or body.api_key is not None:
        # Credentials changed — verify before exposing the device.
        host = db.get_user_config(_conn, username, "romm_host") or ""
        key = db.get_user_config(_conn, username, "romm_api_key") or ""
        if host and key:
            romm_meta.refresh_username_cache(_conn, username, host, key)
        fresh_username = db.get_user_config(_conn, username, "romm_username") or None
        fresh_status = db.get_user_config(_conn, username, "romm_connect_status") or ""
        fresh_detail = db.get_user_config(_conn, username, "romm_connect_detail") or ""
        if has_host and has_key and db.get_user_config(_conn, username, "romm_enabled") != "0":
            if fresh_username:
                # Auto-enable when credentials verify — removes need for a separate toggle.
                db.set_user_config(_conn, username, "romm_enabled", "1")
                _conn.execute(
                    "UPDATE devices SET deleted_at=NULL WHERE device_id=? AND client_type='romm'",
                    (romm_device_id,),
                )
                db.sync_romm_catalog_to_device(_conn, username, romm_device_id)
                import romm_index as _romm_index

                _romm_index.request_index_refresh()
                _romm_index.maybe_run_index()
            elif fresh_status == "auth_failed":
                # Confirmed bad credentials (401/403) — keep device hidden.
                # network_error / bad_response / unknown leave device state unchanged.
                _conn.execute(
                    "UPDATE devices SET deleted_at=? WHERE device_id=? AND client_type='romm'",
                    (db._now(), romm_device_id),
                )
    elif has_host and has_key and db.get_user_config(_conn, username, "romm_enabled") != "0":
        # Credentials unchanged (only enabled/source_id changed) — restore if previously verified.
        existing = db.get_user_config(_conn, username, "romm_username") or None
        if existing:
            _conn.execute(
                "UPDATE devices SET deleted_at=NULL WHERE device_id=? AND client_type='romm'",
                (romm_device_id,),
            )
    return JSONResponse(
        {
            "ok": True,
            "romm_username": fresh_username,
            "romm_connect_status": fresh_status,
            "romm_connect_detail": fresh_detail,
        }
    )


class RommUserBody(BaseModel):
    username: str


class ChangeCredentialsBody(BaseModel):
    current_password: str
    new_username: str = ""
    new_password: str = ""


@router.post("/settings/credentials")
def change_credentials(body: ChangeCredentialsBody, request: Request, response: Response):
    err = _auth_err(request)
    if err:
        return err

    if _is_admin(request):
        stored_hash = db.get_config(_conn, "admin_password_hash") or ""
        if not _verify_password(body.current_password, stored_hash):
            return JSONResponse({"error": "current password incorrect"}, status_code=403)
        if body.new_username:
            old_admin = db.get_config(_conn, "admin_username") or "admin"
            db.rename_auth_user(_conn, old_admin, body.new_username)
            db.set_config(_conn, "admin_username", body.new_username)
            log.info("admin username changed")
        if body.new_password:
            db.set_config(_conn, "admin_password_hash", _hash_password(body.new_password))
            cur_admin = db.get_config(_conn, "admin_username") or "admin"
            token = "sk_live_" + secrets.token_urlsafe(32)
            db.delete_auth_sessions_for_user(_conn, cur_admin)
            db.insert_auth_session(_conn, cur_admin, token)
            response.set_cookie("os_session", token, httponly=True, samesite="lax")
            log.info("admin password changed")
    else:
        username = _current_username(request)
        if not username:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        row = db.get_auth_user(_conn, username)
        if not row or not _verify_password(body.current_password, row["password_hash"]):
            return JSONResponse({"error": "current password incorrect"}, status_code=403)
        if body.new_password:
            db.set_auth_user_password(_conn, username, _hash_password(body.new_password))
            token = "sk_live_" + secrets.token_urlsafe(32)
            db.set_auth_user_session(_conn, username, token)
            response.set_cookie("os_session", token, httponly=True, samesite="lax")
            log.info("user password changed: %s", username)
        if body.new_username:
            try:
                db.rename_auth_user(_conn, username, body.new_username)
                log.info("user renamed: %s → %s", username, body.new_username)
            except Exception:
                return JSONResponse({"error": "username already exists"}, status_code=409)
    return {"ok": True}


@router.get("/settings")
def get_settings(request: Request):
    err = _auth_err(request)
    if err:
        return err
    device_ids = [r["device_id"] for r in _conn.execute("SELECT device_id FROM devices").fetchall()]
    romm_users = {}
    switch_users = {}
    for did in device_ids:
        val = db.get_config(_conn, f"romm_user:{did}")
        if val:
            romm_users[did] = val
        val2 = db.get_config(_conn, f"switch_user:{did}")
        if val2:
            switch_users[did] = val2

    # Per-user-key RomM mapping: query distinct user_keys from transactions
    user_key_rows = _conn.execute(
        "SELECT DISTINCT user_key, user_display FROM sync_transactions "
        "WHERE user_key IS NOT NULL AND user_key != '' "
        "ORDER BY user_key"
    ).fetchall()
    user_key_romm = {}
    for row in user_key_rows:
        uk = row["user_key"]
        mapping = db.get_config(_conn, f"romm_user_key:{uk}")
        user_key_romm[uk] = {
            "display_name": row["user_display"] or "",
            "romm_username": mapping or "",
        }

    username = db.get_config(_conn, "admin_username") or "admin"
    return JSONResponse(
        {
            "username": username,
            "romm_users": romm_users,
            "switch_users": switch_users,
            "user_key_romm": user_key_romm,
        }
    )


@router.put("/settings/romm_user/{device_id}")
def set_romm_user(device_id: str, body: RommUserBody, request: Request):
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    db.set_config(_conn, f"romm_user:{device_id}", body.username)
    return {"ok": True}


@router.delete("/settings/romm_user/{device_id}")
def clear_romm_user(device_id: str, request: Request):
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    db.set_config(_conn, f"romm_user:{device_id}", "")
    return {"ok": True}


class SwitchUserBody(BaseModel):
    username: str


@router.put("/settings/switch_user/{device_id}")
def set_switch_user(device_id: str, body: SwitchUserBody, request: Request):
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    db.set_config(_conn, f"switch_user:{device_id}", body.username)
    return {"ok": True}


@router.delete("/settings/switch_user/{device_id}")
def clear_switch_user(device_id: str, request: Request):
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
        return JSONResponse({"error": "device not found"}, status_code=404)
    db.set_config(_conn, f"switch_user:{device_id}", "")
    return {"ok": True}


_USER_KEY_RE = re.compile(r"^[0-9A-Fa-f]{1,32}$")


@router.put("/settings/user_key_romm/{user_key}")
def set_romm_user_by_key(user_key: str, body: RommUserBody, request: Request):
    """Map an opaque device user_key (account UID hex) to a RomM username."""
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _USER_KEY_RE.match(user_key):
        return JSONResponse({"error": "invalid user_key"}, status_code=400)
    db.set_config(_conn, f"romm_user_key:{user_key}", body.username)
    return {"ok": True}


@router.delete("/settings/user_key_romm/{user_key}")
def clear_romm_user_by_key(user_key: str, request: Request):
    if err := _auth_err(request):  # pragma: no cover
        return err
    if not _USER_KEY_RE.match(user_key):
        return JSONResponse({"error": "invalid user_key"}, status_code=400)
    db.set_config(_conn, f"romm_user_key:{user_key}", "")
    return {"ok": True}
