"""Tests for GET /api/v1/ui/playtime/daily.

Verifies the per-device session reconstruction state machine:
APPLICATION_STARTED → APPLICATION_EXITED boundaries, PROFILE_ACTIVE requirement,
consecutive UNFOCUSED collapse, zero-duration exclusion, reboot/crash handling,
and device isolation.
"""

from helpers import DEVICE_A, DEVICE_B, auth_header, login_admin, pair_device, post_activity_events

APP = "0100F2C0115B6000"
OTHER_APP = "0100EC001DE7E000"
HOMEBREW_APP = "053EEFBFD7D71000"

# Base wall-clock timestamp: 2025-01-16 12:00:00 UTC
_BASE_TS = 1737028800


def _started(ts: int, mono: int, app: str = APP) -> dict:
    return {
        "event_type": "APPLICATION_STARTED",
        "application_id": app,
        "profile_id": None,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _exited(ts: int, mono: int, app: str = APP) -> dict:
    return {
        "event_type": "APPLICATION_EXITED",
        "application_id": app,
        "profile_id": None,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _profile_active(ts: int, mono: int) -> dict:
    return {
        "event_type": "PROFILE_ACTIVE",
        "application_id": None,
        "profile_id": "user1",
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _focused(ts: int, mono: int, app: str = APP, profile: str = "p1") -> dict:
    return {
        "event_type": "APPLICATION_FOCUSED",
        "application_id": app,
        "profile_id": profile,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _unfocused(ts: int, mono: int, app: str = APP, profile: str = "p1") -> dict:
    return {
        "event_type": "APPLICATION_UNFOCUSED",
        "application_id": app,
        "profile_id": profile,
        "event_timestamp": ts,
        "monotonic_timestamp": mono,
    }


def _session(ts: int, start_mono: int, dur_mono: int, app: str = APP) -> list[dict]:
    """One complete valid session: STARTED + PROFILE + FOCUSED + UNFOCUSED + EXITED."""
    return [
        _started(ts, start_mono - 1, app),
        _profile_active(ts, start_mono),
        _focused(ts, start_mono, app),
        _unfocused(ts + dur_mono, start_mono + dur_mono, app),
        _exited(ts + dur_mono, start_mono + dur_mono + 1, app),
    ]


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
    """One complete session with a 3600 s monotonic interval → 60 min."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
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
        *_session(_BASE_TS, start_mono=100, dur_mono=1800),
        # Session 2 — 60 min (same calendar day, higher mono)
        *_session(_BASE_TS + 7200, start_mono=2000, dur_mono=3600),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 90


def test_separate_days_returned_separately(client):
    """Sessions on different calendar days appear as separate rows."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # Day 1 — 30 min
        *_session(_BASE_TS, start_mono=100, dur_mono=1800),
        # Day 2 — 60 min
        *_session(_BASE_TS + 86400, start_mono=2000, dur_mono=3600),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 2
    assert days[0]["minutes"] == 30
    assert days[1]["minutes"] == 60


def test_day_total_not_truncated_per_game(client):
    """Two games each with 59 s sessions must sum to 1 min, not 0.

    Previous SQL implementation truncated 59 s → 0 per game before summing.
    The state machine accumulates raw seconds and divides once at day level.
    """
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # APP — 59 s
        *_session(_BASE_TS, start_mono=100, dur_mono=59, app=APP),
        # OTHER_APP — 59 s (higher mono)
        *_session(_BASE_TS + 200, start_mono=300, dur_mono=59, app=OTHER_APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 1   # (59 + 59) // 60 = 1, not 0


# ── title_id filter ───────────────────────────────────────────────────────────


def test_title_id_filter_isolates_game(client):
    """?title_id=X excludes sessions from other applications."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        *_session(_BASE_TS, start_mono=100, dur_mono=3600, app=APP),
        *_session(_BASE_TS + 86400, start_mono=4000, dur_mono=1800, app=OTHER_APP),
    ])
    r = client.get(f"/api/v1/ui/playtime/daily?title_id={APP}", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_no_title_id_returns_all_apps(client):
    """Without ?title_id, sessions from all applications contribute."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        *_session(_BASE_TS, start_mono=100, dur_mono=3600, app=APP),
        *_session(_BASE_TS + 86400, start_mono=4000, dur_mono=1800, app=OTHER_APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 2


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_orphan_focus_excluded(client):
    """FOCUSED event outside any session boundary (no STARTED) is ignored."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [_focused(_BASE_TS, mono=1)])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_session_without_profile_excluded_on_non_owned_device(client):
    """Session with no PROFILE event on a device not owned by the querying user → excluded.

    On an owned device, no-profile sessions ARE included (see
    test_owned_device_session_visible_without_profile_event). On a foreign device,
    we have no basis for attribution, so the session must stay invisible.
    """
    tok_b = _create_user(client, "user_b_noprof")
    _map_profile(client, DEVICE_A, "profX", "user_b_noprof")   # gives user_b access to events
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=99),
        _focused(_BASE_TS, mono=100),
        _unfocused(_BASE_TS + 3600, mono=3700),
        _exited(_BASE_TS + 3600, mono=3701),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b))
    assert r.json()["days"] == []


def test_zero_duration_interval_excluded(client):
    """FOCUSED and UNFOCUSED with identical monotonic values contribute nothing."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=999),
        _profile_active(_BASE_TS, mono=1000),
        _focused(_BASE_TS, mono=1000),
        _unfocused(_BASE_TS, mono=1000),          # dur = 0 — excluded
        _focused(_BASE_TS + 1000, mono=2000),
        _unfocused(_BASE_TS + 2200, mono=3200),   # dur = 1200 s = 20 min
        _exited(_BASE_TS + 2200, mono=3201),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 20


def test_consecutive_unfocused_collapsed(client):
    """Two consecutive UNFOCUSED events: only the first pairing is counted."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=999),
        _profile_active(_BASE_TS, mono=1000),
        _focused(_BASE_TS, mono=1000),
        _unfocused(_BASE_TS + 1800, mono=2800),   # dur = 1800 s = 30 min
        _unfocused(_BASE_TS + 1800, mono=2800),   # second consecutive — no-op in IN_SESSION
        _exited(_BASE_TS + 1800, mono=2801),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 30


def test_crash_session_counts_before_new_started(client):
    """Session ended by a new STARTED (crash/no EXIT) still emits its completed intervals."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # App A session — no EXIT, terminated by App B's STARTED
        _started(_BASE_TS, mono=49, app=APP),
        _profile_active(_BASE_TS, mono=50),
        _focused(_BASE_TS, mono=50, app=APP),
        _unfocused(_BASE_TS + 1800, mono=1850, app=APP),  # 1800 s = 30 min
        # App B STARTED closes App A's session
        _started(_BASE_TS + 1900, mono=1900, app=OTHER_APP),
        _profile_active(_BASE_TS + 1900, mono=1901),
        _focused(_BASE_TS + 1900, mono=1901, app=OTHER_APP),
        _unfocused(_BASE_TS + 3700, mono=3701, app=OTHER_APP),
        _exited(_BASE_TS + 3700, mono=3702, app=OTHER_APP),
    ])
    r = client.get(f"/api/v1/ui/playtime/daily?title_id={APP}", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 30


def test_open_session_excluded(client):
    """Session with STARTED but no EXITED (still running) is not emitted."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=999),
        _profile_active(_BASE_TS, mono=1000),
        _focused(_BASE_TS, mono=1000),
        _unfocused(_BASE_TS + 3600, mono=4600),
        # No EXITED — session remains open
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_focused_exited_without_unfocused_excluded(client):
    """Open FOCUSED interval closed by EXITED (no UNFOCUSED) is discarded."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=999),
        _profile_active(_BASE_TS, mono=1000),
        _focused(_BASE_TS, mono=1000),
        _exited(_BASE_TS + 3600, mono=4600),   # force-quit while focused
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_malformed_double_focus_does_not_crash(client):
    """FOCUS, FOCUS, UNFOCUS — second FOCUSED overwrites first; must not raise."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=99),
        _profile_active(_BASE_TS, mono=100),
        _focused(_BASE_TS, mono=100),
        _focused(_BASE_TS + 60, mono=200),           # overwrites — this is the active focus
        _unfocused(_BASE_TS + 3660, mono=3800),      # dur = 3800 - 200 = 3600 s = 60 min
        _exited(_BASE_TS + 3660, mono=3801),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    days = r.json()["days"]
    assert isinstance(days, list)
    for day in days:
        assert day["minutes"] >= 0


def test_result_is_sorted_by_date(client):
    """Response rows are ordered by date ascending."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # Post in chronological order; response must still be date-sorted
        *_session(_BASE_TS, start_mono=100, dur_mono=1800),
        *_session(_BASE_TS + 86400 * 2, start_mono=2000, dur_mono=1800),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    dates = [d["date"] for d in days]
    assert dates == sorted(dates)


# ── Device isolation and ordering ─────────────────────────────────────────────


def test_device_isolation(client):
    """Event streams from two devices are reconstructed independently.

    If streams were mixed, DEVICE_A's FOCUSED would pair with DEVICE_B's UNFOCUSED
    (or vice-versa) producing wrong durations. Correct result: 30 + 45 = 75 min.
    """
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=100, dur_mono=1800))
    post_activity_events(client, DEVICE_B, _session(_BASE_TS, start_mono=100, dur_mono=2700))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 75   # 1800 + 2700 = 4500 s // 60 = 75


def test_out_of_insertion_order_events(client):
    """Events with decreasing wall-clock but increasing monotonic are handled without crash."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        # Wall clock decreases; monotonic increases (simulates out-of-order wall time)
        _started(_BASE_TS + 3600, mono=50),
        _profile_active(_BASE_TS + 2400, mono=100),
        _focused(_BASE_TS + 1800, mono=100),
        _unfocused(_BASE_TS, mono=1900),           # dur = 1800 s
        _exited(_BASE_TS - 600, mono=1901),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    days = r.json()["days"]
    assert isinstance(days, list)
    assert all(d["minutes"] >= 0 for d in days)


# ── Profile attribution ────────────────────────────────────────────────────────


def _map_profile(client, device_id: str, profile_id: str, user_id: str) -> None:
    """Insert a device_profile_map entry directly — bypasses the claim API
    (which requires the profile to be in device_known_profiles first)."""
    import ui_api as _ui
    from datetime import datetime, timezone
    _ui._conn.execute(
        """
        INSERT OR REPLACE INTO device_profile_map
            (device_id, profile_id, user_id, profile_name, created_at)
        VALUES (?, ?, ?, '', ?)
        """,
        (device_id, profile_id, user_id, datetime.now(timezone.utc).isoformat()),
    )


def _create_user(client, username: str, password: str = "pass") -> str:
    """Create a non-admin user and return their session token."""
    admin_tok = login_admin(client)
    r = client.post(
        "/api/v1/ui/users",
        json={"username": username, "password": password},
        headers=auth_header(admin_tok),
    )
    assert r.status_code == 200, r.text
    return login_admin(client, username, password)


def test_profile_mapped_to_other_user_excluded(client):
    """Session whose active profile is mapped to a different OmniSave user is excluded."""
    token = login_admin(client)
    # Profile "user1" (used by _profile_active helper) → mapped to user_b, not admin
    _map_profile(client, DEVICE_A, "user1", "user_b")
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.json()["days"] == []


def test_profile_mapped_to_other_user_visible_to_that_user(client):
    """Session excluded from device owner is visible to the user the profile maps to."""
    tok_b = _create_user(client, "user_b")
    # Map "user1" profile on DEVICE_A to user_b
    _map_profile(client, DEVICE_A, "user1", "user_b")
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
    # user_b sees the session even though DEVICE_A is owned by admin
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_profile_mapped_to_same_user_included(client):
    """Session with profile explicitly mapped to the querying user is counted."""
    token = login_admin(client)
    _map_profile(client, DEVICE_A, "user1", "admin")
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_unattributed_profile_falls_to_device_owner(client):
    """Profile with no device_profile_map entry counts for the device owner."""
    token = login_admin(client)
    # No _map_profile call — profile "user1" has no mapping
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_32char_profile_id_truncated_for_lookup(client):
    """Switch emits 32-char hex UIDs; server truncates to [:16] for device_profile_map lookup."""
    tok_b = _create_user(client, "user_b_trunc")
    full_uid = "AABBCCDDEEFF001122334455667788FF"   # 32-char hex (Switch UID format)
    short_uid = full_uid[:16]                         # 16 chars stored in device_profile_map
    _map_profile(client, DEVICE_A, short_uid, "user_b_trunc")

    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10),
        {
            "event_type": "PROFILE_ACTIVE",
            "application_id": None,
            "profile_id": full_uid,
            "event_timestamp": _BASE_TS,
            "monotonic_timestamp": 50,
        },
        _focused(_BASE_TS, mono=100, profile=full_uid),
        _unfocused(_BASE_TS + 3600, mono=3700, profile=full_uid),
        _exited(_BASE_TS + 3600, mono=3701),
    ])

    tok_b_days = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b)).json()["days"]
    assert len(tok_b_days) == 1
    assert tok_b_days[0]["minutes"] == 60

    admin_tok = login_admin(client)
    assert client.get("/api/v1/ui/playtime/daily", headers=auth_header(admin_tok)).json()["days"] == []


def test_midnight_date_bucketing(client):
    """Sessions either side of midnight UTC are attributed to distinct dates."""
    # 2025-01-16 23:30:00 UTC
    ts_before = _BASE_TS + 41400
    # 2025-01-17 00:30:00 UTC
    ts_after = _BASE_TS + 45000

    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        *_session(ts_before, start_mono=100,   dur_mono=1800),
        *_session(ts_after,  start_mono=10000, dur_mono=1800),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    dates = [d["date"] for d in days]
    assert "2025-01-16" in dates
    assert "2025-01-17" in dates
    assert days[dates.index("2025-01-16")]["minutes"] == 30
    assert days[dates.index("2025-01-17")]["minutes"] == 30


def test_profile_active_while_focused_sets_attribution(client):
    """PROFILE_ACTIVE received while in FOCUSED state is captured (lines 2751-2753)."""
    tok_b = _create_user(client, "user_b_paf")
    _map_profile(client, DEVICE_A, "profX", "user_b_paf")
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10),
        _focused(_BASE_TS, mono=50),
        # PROFILE_ACTIVE while already FOCUSED — hits lines 2751-2753
        {"event_type": "PROFILE_ACTIVE", "application_id": None, "profile_id": "profX",
         "event_timestamp": _BASE_TS, "monotonic_timestamp": 60},
        _unfocused(_BASE_TS + 3600, mono=3700),
        _exited(_BASE_TS + 3600, mono=3701),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


def test_started_while_focused_emits_and_opens_new(client):
    """APPLICATION_STARTED in FOCUSED state clears focus, emits accumulated intervals, opens new (lines 2768-2771)."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10, app=APP),
        _profile_active(_BASE_TS, mono=20),
        _focused(_BASE_TS, mono=50, app=APP),
        _unfocused(_BASE_TS + 1800, mono=1850, app=APP),   # 30 min accumulated
        _focused(_BASE_TS + 1900, mono=1900, app=APP),     # re-enter FOCUSED state
        # STARTED while FOCUSED — hits lines 2768-2771
        _started(_BASE_TS + 2000, mono=2000, app=OTHER_APP),
        _profile_active(_BASE_TS + 2000, mono=2001),
        _focused(_BASE_TS + 2000, mono=2001, app=OTHER_APP),
        _unfocused(_BASE_TS + 5601, mono=5601, app=OTHER_APP),   # 5601-2001=3600s=60min
        _exited(_BASE_TS + 5601, mono=5602, app=OTHER_APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 90   # APP 30 min + OTHER_APP 60 min


def test_reboot_boundary_preserves_completed_pre_reboot_intervals(client):
    """Backward mono signals reboot; completed FOCUSED→UNFOCUSED intervals before
    the reboot are emitted, only the open FOCUSED interval (if any) is discarded.

    Pre-reboot events are POSTed first (lower insertion id), post-reboot events second
    (higher id). ORDER BY id yields high-mono pre-reboot events before low-mono
    post-reboot events, creating the backward jump.
    """
    token = login_admin(client)
    # Pre-reboot batch — higher mono, inserted first
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=1000),
        _profile_active(_BASE_TS, mono=1001),
        _focused(_BASE_TS, mono=1002),
        _unfocused(_BASE_TS + 1800, mono=2800),   # 30 min complete interval
    ])
    # Post-reboot batch — lower mono, inserted second → backward jump detected
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS + 7200, mono=100),       # mono=100 < prev_mono=2800 → _emit()+_reset()
        _profile_active(_BASE_TS + 7200, mono=101),
        _focused(_BASE_TS + 7200, mono=101),
        _unfocused(_BASE_TS + 10800, mono=3701),   # 60 min
        _exited(_BASE_TS + 10800, mono=3702),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    total = sum(d["minutes"] for d in days)
    assert total == 89   # pre-reboot 29m (1798s mono) preserved + post-reboot 60 min


def test_unmapped_active_profile_non_owner_excluded(client):
    """Session's active profile is unmapped and device not owned by querying user → excluded (line 2660).

    user_b has profY mapped on DEVICE_A (so events are visible in the WHERE clause),
    but the session's PROFILE_ACTIVE is for "user1" which has no mapping.
    """
    tok_b = _create_user(client, "user_b_nonowner")
    # Give user_b a foothold on DEVICE_A so the SELECT returns events
    _map_profile(client, DEVICE_A, "profY", "user_b_nonowner")
    # Session uses "user1" profile — not mapped to anyone
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=1000, dur_mono=3600))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b))
    assert r.json()["days"] == []


def test_profile_inactive_only_non_owner_excluded(client):
    """PROFILE_INACTIVE only (no ACTIVE) on device not owned by querying user → excluded (line 2663).

    user_b has profZ mapped on DEVICE_A so events are visible, but session has no
    PROFILE_ACTIVE — session_profile_id stays None, device owner is admin ≠ user_b.
    """
    tok_b = _create_user(client, "user_b_ionly")
    _map_profile(client, DEVICE_A, "profZ", "user_b_ionly")
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10),
        {"event_type": "PROFILE_INACTIVE", "application_id": None, "profile_id": "user1",
         "event_timestamp": _BASE_TS, "monotonic_timestamp": 20},
        _focused(_BASE_TS, mono=50),
        _unfocused(_BASE_TS + 3600, mono=3700),
        _exited(_BASE_TS + 3600, mono=3701),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b))
    assert r.json()["days"] == []


def test_profile_switch_mid_session_latest_wins(client):
    """PROFILE_ACTIVE(A) then PROFILE_ACTIVE(B) in one session — last active profile wins."""
    tok_b = _create_user(client, "user_b")
    _map_profile(client, DEVICE_A, "profA", "admin")
    _map_profile(client, DEVICE_A, "profB", "user_b")

    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10),
        {"event_type": "PROFILE_ACTIVE", "application_id": None, "profile_id": "profA",
         "event_timestamp": _BASE_TS, "monotonic_timestamp": 50},
        _focused(_BASE_TS, mono=100),
        _unfocused(_BASE_TS + 1800, mono=1900),    # 30 min interval
        {"event_type": "PROFILE_ACTIVE", "application_id": None, "profile_id": "profB",
         "event_timestamp": _BASE_TS + 1800, "monotonic_timestamp": 1900},  # switch after unfocus
        _exited(_BASE_TS + 1800, mono=1901),
    ])

    admin_tok = login_admin(client)
    # admin → profB is not theirs, so session is excluded
    assert client.get("/api/v1/ui/playtime/daily", headers=auth_header(admin_tok)).json()["days"] == []
    # user_b → profB maps to them, so session is included
    days = client.get("/api/v1/ui/playtime/daily", headers=auth_header(tok_b)).json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 30

# ── Owned device without PROFILE event ───────────────────────────────────────


def test_owned_device_session_visible_without_profile_event(client):
    """Session on owner's device with no PROFILE_ACTIVE/INACTIVE is included.

    First-boot scenario where the profile hasn't fired yet — the device
    is owned, so we know who it belongs to.
    """
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        _started(_BASE_TS, mono=10),
        _focused(_BASE_TS, mono=20),
        _unfocused(_BASE_TS + 3600, mono=3620),
        _exited(_BASE_TS + 3600, mono=3621),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 60


# ── Homebrew / non-retail title filtering ────────────────────────────────────


def test_homebrew_title_excluded(client):
    """Homebrew events dropped at ingest must not appear in playtime output."""
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, [
        *_session(_BASE_TS, start_mono=100, dur_mono=3600, app=HOMEBREW_APP),
        *_session(_BASE_TS, start_mono=4000, dur_mono=1800, app=APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    days = r.json()["days"]
    all_title_ids = [g["title_id"] for d in days for g in d["games"]]
    assert HOMEBREW_APP not in all_title_ids
    assert APP in all_title_ids
    retail_sec = next(
        g["total_sec"] for d in days for g in d["games"] if g["title_id"] == APP
    )
    assert retail_sec == 1800


def test_homebrew_state_machine_filter(client, conn):
    """State machine is_retail=False suppresses sessions already in the DB (historical data)."""
    import database as db
    pair_device(client, DEVICE_A)
    token = login_admin(client)
    db.insert_play_events(conn, DEVICE_A, "admin", [
        _started(_BASE_TS, 100, HOMEBREW_APP),
        _focused(_BASE_TS, 101, HOMEBREW_APP),
        _unfocused(_BASE_TS + 3600, 3701, HOMEBREW_APP),
        _exited(_BASE_TS + 3600, 3702, HOMEBREW_APP),
    ])
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["days"] == []


# ── Sub-minute day-level minutes ──────────────────────────────────────────────


def test_sub_minute_session_returns_minutes_one(client):
    """A session shorter than 60 s must return minutes=1, not 0.

    A zero minutes value would cause the day to be excluded from streak
    counts and rendered as a dark (no-play) cell in the heatmap.
    """
    token = login_admin(client)
    post_activity_events(client, DEVICE_A, _session(_BASE_TS, start_mono=100, dur_mono=30))
    r = client.get("/api/v1/ui/playtime/daily", headers=auth_header(token))
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["minutes"] == 1
    assert days[0]["games"][0]["total_sec"] == 30
