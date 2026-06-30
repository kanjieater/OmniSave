"""Activity event ingestion API.

Accepts batches of timestamped activity events from trusted devices.
Platform-agnostic: the server does not know or care about the event source.
"""

import logging
import re
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])

_conn = None

_DEVICE_RE = re.compile(r"^[A-Za-z0-9:_-]{4,64}$")
_MAC_COLON_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_EVENT_TYPES = {
    "APPLICATION_STARTED",
    "APPLICATION_EXITED",
    "APPLICATION_FOCUSED",
    "APPLICATION_UNFOCUSED",
    "PROFILE_ACTIVE",
    "PROFILE_INACTIVE",
}


def init(conn) -> None:
    global _conn
    _conn = conn


def _device(request: Request) -> str | None:
    did = request.headers.get("X-Device-ID", "").strip()
    if _MAC_COLON_RE.match(did):
        did = did.replace(":", "").upper()
    return did if _DEVICE_RE.match(did) else None


@dataclass
class TrustedDevice:
    device_id: str
    user_id: str


def _require_device_auth(request: Request) -> "TrustedDevice | JSONResponse":
    device_id = _device(request)
    if not device_id:
        log.warning("auth: missing/invalid X-Device-ID from %s", request.client)
        return JSONResponse({"error": "X-Device-ID header required or invalid"}, status_code=401)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer sk_device_"):
        log.warning("auth: no valid Bearer from device=%s path=%s", device_id, request.url.path)
        return JSONResponse(
            {"error": "device token required — pair this device first"}, status_code=401
        )
    token = auth[7:]
    row = db.get_device_auth_by_token(_conn, token)
    if not row or row["device_id"] != device_id:
        log.warning(
            "auth: token mismatch device=%s token_prefix=%.12s path=%s",
            device_id,
            token,
            request.url.path,
        )
        return JSONResponse({"error": "invalid device token"}, status_code=401)
    deleted = _conn.execute(
        "SELECT deleted_at FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()
    if deleted and deleted["deleted_at"] is not None:
        log.warning("auth: device removed device=%s", device_id)
        return JSONResponse(
            {"error": "device has been removed — re-pair to continue"}, status_code=401
        )
    db.touch_device_last_seen(_conn, device_id)
    return TrustedDevice(device_id=device_id, user_id=row["user_id"])


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


# ── Models ────────────────────────────────────────────────────────────────────


class PlayEventIn(BaseModel):
    event_type: str
    application_id: str | None = None
    profile_id: str | None = None
    event_timestamp: int
    monotonic_timestamp: int


class PlayEventsBody(BaseModel):
    events: list[PlayEventIn]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/events")
def post_events(body: PlayEventsBody, request: Request):
    trusted = _require_device_auth(request)
    if isinstance(trusted, JSONResponse):
        return trusted

    if len(body.events) > 500:
        return _err("too many events in one batch (max 500)")

    for e in body.events:
        if e.event_type not in _EVENT_TYPES:
            return _err(f"invalid event_type: {e.event_type!r}")
        if e.application_id is not None and not _ID_RE.match(e.application_id):
            return _err(f"invalid application_id: {e.application_id!r}")
        if e.profile_id is not None and not _ID_RE.match(e.profile_id):
            return _err(f"invalid profile_id: {e.profile_id!r}")

    inserted = db.insert_play_events(
        _conn,
        trusted.device_id,
        trusted.user_id,
        [e.model_dump() for e in body.events],
    )
    _conn.commit()
    log.info(
        "activity: device=%s accepted=%d received=%d",
        trusted.device_id,
        inserted,
        len(body.events),
    )
    return {"accepted": inserted, "received": len(body.events)}
