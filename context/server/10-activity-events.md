# Activity Event Ingestion

Trusted devices submit batches of timestamped activity events. The server stores raw facts
only — sessions, playtime totals, and aggregates are read-time derivations for a future API.
The server is platform-agnostic: it has no concept of what kind of device is producing events.

## Table: `device_play_events`

| Column | Type | Notes |
|---|---|---|
| `device_id` | TEXT | From auth |
| `owner_user_id` | TEXT | Stamped from `device_auth` at insert; immutable |
| `profile_id` | TEXT (empty string if absent) | Opaque client-supplied profile identifier |
| `application_id` | TEXT (empty string if absent) | Opaque client-supplied app/game identifier; empty string for profile-only events |
| `event_type` | TEXT | See vocabulary below |
| `event_timestamp` | INTEGER | Wall-clock POSIX seconds |
| `monotonic_timestamp` | INTEGER | Monotonic/steady-clock seconds; use for duration math |
| `recorded_at` | TEXT | Server receipt time (ISO-8601 UTC) |

Dedup key: `(device_id, event_type, event_timestamp, monotonic_timestamp, application_id, profile_id)` —
content-addressed. `INSERT OR IGNORE` makes resubmission always safe. Both `application_id` and
`profile_id` are `NOT NULL DEFAULT ''`; absent fields are stored as empty string (not NULL) so
the UNIQUE constraint fires correctly for profile-only events.

## Event type vocabulary

| Type | Meaning |
|---|---|
| `APPLICATION_STARTED` | Application launched |
| `APPLICATION_EXITED` | Application closed |
| `APPLICATION_FOCUSED` | Application gained focus |
| `APPLICATION_UNFOCUSED` | Application lost focus |
| `PROFILE_ACTIVE` | User profile became active |
| `PROFILE_INACTIVE` | User profile became inactive |

## Endpoint

`POST /api/v1/activity/events`

Auth: `X-Device-ID` header + `Authorization: Bearer sk_device_*` (same as sync endpoints).

Request body:
```json
{
  "events": [
    {
      "event_type": "APPLICATION_STARTED",
      "application_id": "optional-opaque-id",
      "profile_id": "optional-opaque-id",
      "event_timestamp": 1700000000,
      "monotonic_timestamp": 12345
    }
  ]
}
```

- Max 500 events per batch.
- `application_id` / `profile_id` validated as `[A-Za-z0-9_-]{1,64}` (generic, not platform-specific).
- Duplicate events silently ignored.

Response: `{"accepted": N, "received": N}`

## Read helpers (internal, not yet exposed via route)

`db.get_play_events(conn, device_id, application_id, owner_user_id, since)` — plain filtered SELECT.
Session/duration derivation is intentionally deferred to whatever future read API builds on this.

---

First producer: the OmniSaveSwitch sysmodule, which maps Nintendo's pdm event log to this
model — see that repo for client-specific detail.
