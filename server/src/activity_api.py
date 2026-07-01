"""Activity event ingestion API.

Accepts batches of timestamped activity events from trusted devices.
Platform-agnostic: the server does not know or care about the event source.
"""

import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
import device_auth as _auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])

_conn = None

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


def _require_device_auth(request: Request) -> "_auth.TrustedDevice | JSONResponse":
    return _auth.require_device_auth(_conn, request)


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
    log.info(
        "activity: device=%s accepted=%d received=%d",
        trusted.device_id,
        inserted,
        len(body.events),
    )
    return {"accepted": inserted, "received": len(body.events)}
