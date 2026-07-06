"""Activity event ingestion API.

Accepts batches of timestamped activity events from trusted devices.
Platform-agnostic: the server does not know or care about the event source.
"""

import logging
import re
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import database as db
import device_auth as _auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])

_conn = None

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

EventType = Literal[
    "APPLICATION_STARTED",
    "APPLICATION_EXITED",
    "APPLICATION_FOCUSED",
    "APPLICATION_UNFOCUSED",
    "PROFILE_ACTIVE",
    "PROFILE_INACTIVE",
]

# These event types always refer to a specific application; application_id is required.
_APP_EVENT_TYPES = {
    "APPLICATION_STARTED",
    "APPLICATION_EXITED",
    "APPLICATION_FOCUSED",
    "APPLICATION_UNFOCUSED",
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
    event_type: EventType
    application_id: str | None = None
    profile_id: str | None = None
    event_timestamp: int
    monotonic_timestamp: int


class PlayEventsBody(BaseModel):
    events: list[PlayEventIn] = Field(max_length=500)
    next_offset: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/offset")
def get_offset(request: Request):
    trusted = _require_device_auth(request)
    if isinstance(trusted, JSONResponse):
        return trusted
    return {"last_offset": db.get_activity_offset(_conn, trusted.device_id)}


@router.post("/events")
def post_events(body: PlayEventsBody, request: Request):
    trusted = _require_device_auth(request)
    if isinstance(trusted, JSONResponse):
        return trusted

    client_type = db.get_device_client_type(_conn, trusted.device_id)
    valid_events = []
    for e in body.events:
        if e.event_type in _APP_EVENT_TYPES and not e.application_id:
            log.warning(
                "activity: device=%s dropping %s: missing application_id",
                trusted.device_id,
                e.event_type,
            )
            continue
        if e.application_id is not None and not _ID_RE.match(e.application_id):
            log.warning(
                "activity: device=%s dropping event: invalid application_id %r",
                trusted.device_id,
                e.application_id,
            )
            continue
        if e.application_id is not None and not db._is_retail_app_id(
            e.application_id, client_type
        ):
            log.warning(
                "activity: device=%s dropping event: non-retail application_id %r",
                trusted.device_id,
                e.application_id,
            )
            continue
        if e.profile_id is not None and not _ID_RE.match(e.profile_id):
            log.warning(
                "activity: device=%s dropping event: invalid profile_id %r",
                trusted.device_id,
                e.profile_id,
            )
            continue
        valid_events.append(e)

    inserted = db.insert_play_events(
        _conn,
        trusted.device_id,
        trusted.user_id,
        [e.model_dump() for e in valid_events],
        next_offset=body.next_offset,
    )
    log.info(
        "activity: device=%s accepted=%d received=%d next_offset=%s",
        trusted.device_id,
        inserted,
        len(body.events),
        body.next_offset,
    )
    return {"accepted": inserted, "received": len(body.events)}
