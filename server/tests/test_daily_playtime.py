"""Tests for GET /api/v1/ui/playtime/daily.

Covers the session-pairing SQL (nearest-exit algorithm), aggregation, filtering,
and documented edge-case behaviour for malformed event streams.
"""

from helpers import DEVICE_A, auth_header, login_admin, post_activity_events

APP = "0100F2C0115B6000"
OTHER_APP = "0100EC001DE7E000"

# Base wall-clock timestamp: 2025-01-16 12:00:00 UTC (arbitrary, well within the DB)
_BASE_TS = 1737028800


def _started(ts: int, mono: int, app: str = APP, profile: str = "p1") -> dict:
    return {
        "event_type": "APPLICATION_STARTED",
        "application_id": app,
        "profile_id": profile,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _exited(ts: int, mono: int, app: str = APP, profile: str = "p1") -> dict:
    return {
        "event_type": "APPLICATION_EXITED",
        "application_id": app,
        "profile_id": profile,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_requires_auth(client):
    r = client.get("/api/v1/ui/playtime/daily")
    assert r.status_code == 401


# ── Empty state ───────────────────────────────────────────────────────────────


def test_empty_no_events(client):
    token = login_admin(client)
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json() == {"days": []}


# ── Basic session → minutes ───────────────────────────────────────────────────


def test_daily_minutes_single_session(client):
    """One STARTED + EXITED pair → correct minute count on that day."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=1000),
        _exited(_BASE_TS + 3600, mono=4600),   # 3600 s monotonic diff = 60 min
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


# ── Aggregation ───────────────────────────────────────────────────────────────


def test_aggregates_multiple_sessions_same_day(client):
    """Two sessions on the same UTC day are summed."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # Session 1 — 30 min
        _started(_BASE_TS, mono=100),
        _exited(_BASE_TS + 1800, mono=1900),
        # Session 2 — 60 min (same calendar day)
        _started(_BASE_TS + 7200, mono=7300),
        _exited(_BASE_TS + 10800, mono=10900),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 90  # 30 + 60


def test_separate_days_returned_separately(client):
    """Sessions on different calendar days appear as separate rows."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=100),
        _exited(_BASE_TS + 1800, mono=1900),
        # Next day: _BASE_TS + 86400
        _started(_BASE_TS + 86400, mono=200000),
        _exited(_BASE_TS + 86400 + 3600, mono=203600),  # 3600 s monotonic diff = 60 min
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 2
    assert days[0]["minutes"] == 30
    assert days[1]["minutes"] == 60


# ── title_id filter ───────────────────────────────────────────────────────────


def test_title_id_filter_isolates_game(client):
    """?title_id=X excludes activity from other applications."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=100, app=APP),
        _exited(_BASE_TS + 3600, mono=3700, app=APP),
        _started(_BASE_TS + 86400, mono=200000, app=OTHER_APP),
        _exited(_BASE_TS + 86400 + 1800, mono=201800, app=OTHER_APP),
    ])
    r = client.get(f"/api/v1/ui/playtime/daily?title_id={APP}", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_no_title_id_returns_all_apps(client):
    """Without ?title_id, all applications contribute."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=100, app=APP),
        _exited(_BASE_TS + 3600, mono=3700, app=APP),
        _started(_BASE_TS + 86400, mono=200000, app=OTHER_APP),
        _exited(_BASE_TS + 86400 + 1800, mono=201800, app=OTHER_APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 2


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_orphan_start_excluded(client):
    """STARTED with no matching EXITED contributes nothing."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=1),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_session_cap_excludes_long_sessions(client):
    """EXITED more than 86400 s after STARTED is excluded (>24 h cap)."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=1000),
        _exited(_BASE_TS + 90000, mono=1000 + 86401),  # 86401 s > cap
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_malformed_double_start_does_not_crash(client):
    """START, START, EXIT — documents best-effort behaviour; must not raise."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=100),
        _started(_BASE_TS + 60, mono=200),
        _exited(_BASE_TS + 3660, mono=3800),  # nearest exit after both starts
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    days = r.json()["days"]
    # Both STARTs pair with the same EXIT under the nearest-exit algorithm;
    # minutes may be over-counted. We only assert the response is valid.
    assert isinstance(days, list)
    for day in days:
        assert day["minutes"] >= 0


def test_result_is_sorted_by_date(client):
    """Response rows are ordered by date ascending."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS + 86400 * 2, mono=300000),
        _exited(_BASE_TS + 86400 * 2 + 1800, mono=301800),
        _started(_BASE_TS, mono=100),
        _exited(_BASE_TS + 1800, mono=1900),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    dates = [d["date"] for d in days]
    assert dates == sorted(dates)
