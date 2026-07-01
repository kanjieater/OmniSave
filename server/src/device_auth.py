"""Shared device authentication helpers used by all API routers."""

import logging
import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

import database as db

log = logging.getLogger(__name__)

_DEVICE_RE = re.compile(r"^[A-Za-z0-9:_-]{4,64}$")
_MAC_COLON_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


@dataclass
class TrustedDevice:
    device_id: str
    user_id: str  # resolved from device_auth; never empty


def normalize_device_id(request: Request) -> str | None:
    """Return a canonical device ID from X-Device-ID header, or None if invalid."""
    did = request.headers.get("X-Device-ID", "").strip()
    if _MAC_COLON_RE.match(did):
        did = did.replace(":", "").upper()
    return did if _DEVICE_RE.match(did) else None


def require_device_auth(conn, request: Request) -> "TrustedDevice | JSONResponse":
    """Returns TrustedDevice on valid token. Returns 401 for everything else.
    No anonymous fallback — unpaired devices are rejected.
    """
    device_id = normalize_device_id(request)
    if not device_id:
        log.warning("auth: missing/invalid X-Device-ID from %s", request.client)
        return JSONResponse({"error": "X-Device-ID header required or invalid"}, status_code=401)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer sk_device_"):
        log.warning("auth: no valid Bearer device=%s path=%s", device_id, request.url.path)
        return JSONResponse(
            {"error": "device token required — pair this device first"}, status_code=401
        )
    token = auth[7:]
    row = db.get_device_auth_by_token(conn, token)
    if not row or row["device_id"] != device_id:
        log.warning(
            "auth: token mismatch device=%s token_prefix=%.12s path=%s",
            device_id,
            token,
            request.url.path,
        )
        return JSONResponse({"error": "invalid device token"}, status_code=401)
    deleted = conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()
    if deleted is None or deleted["deleted_at"] is not None:
        log.warning("auth: device removed device=%s", device_id)
        return JSONResponse(
            {"error": "device has been removed — re-pair to continue"}, status_code=401
        )
    db.touch_device_last_seen(conn, device_id)
    return TrustedDevice(device_id=device_id, user_id=row["user_id"])
