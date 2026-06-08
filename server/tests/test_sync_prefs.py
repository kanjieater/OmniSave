"""
Sync preferences enforcement tests.

Invariant: sync_prefs must be enforced at the fork boundary in processing._process().
Client-side enforcement (sysmodule) is tested separately in C++.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, poll_queue, queue_get, login_admin, auth_header, report_catalog

DEVICE_C = "CCDDEE001122"
SAVE = b"save-payload-" * 100


def _bootstrap(client) -> str:
    return login_admin(client)


def _hdr(token: str) -> dict:
    return auth_header(token)


def _set_prefs(client, token: str, device_id: str, prefs: list[dict]) -> None:
    r = client.post(
        f"/api/v1/ui/devices/{device_id}/games/sync/batch",
        json={"preferences": prefs},
        headers=_hdr(token),
    )
    assert r.status_code == 200, r.text


# ── Fork-time enforcement ─────────────────────────────────────────────────────


def test_disabled_game_not_forked_at_processing(client, conn):
    """Disabling TITLE_1 for B before A uploads: processing must not fork an outbound for B."""
    token = _bootstrap(client)
    report_catalog(client, DEVICE_B, [TITLE_1])

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    # No outbound should have been forked for B
    row = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()[0]
    assert row == 0, "processing fork must respect sync_prefs"

    pending = poll_queue(client, DEVICE_B)
    assert not any(p["title_id"] == TITLE_1.upper() for p in pending)


def test_processing_fork_skips_disabled_peer_keeps_enabled(client, conn):
    """3 devices: B disabled, C enabled. A uploads → outbound for C only."""
    token = _bootstrap(client)
    # Disable B before any peer upload so no outbound is ever created for B
    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    report_catalog(client, DEVICE_B, [TITLE_1])
    report_catalog(client, DEVICE_C, [TITLE_1])

    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    b_count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()[0]
    c_count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_C, TITLE_1.upper()),
    ).fetchone()[0]
    assert b_count == 0, "disabled peer must not receive outbound"
    assert c_count >= 1, "enabled peer must receive outbound"


def test_disable_does_not_affect_other_device(client, conn):
    """Disabling TITLE_1 for B must not affect C's delivery."""
    token = _bootstrap(client)
    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])
    report_catalog(client, DEVICE_C, [TITLE_1])

    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending_c = poll_queue(client, DEVICE_C)
    assert any(p["title_id"] == TITLE_1.upper() for p in pending_c)


# ── Cancel in-flight outbounds ────────────────────────────────────────────────


def test_disable_cancels_inflight_outbound(client, conn):
    """READY_FOR_RESTORE outbound exists; disable → state=CANCELLED; B polls → not in pending."""
    token = _bootstrap(client)
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    row = conn.execute(
        "SELECT state FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()
    assert row is not None
    assert row["state"] == "CANCELLED", "set_sync_prefs must cancel in-flight outbound"

    pending_after = poll_queue(client, DEVICE_B)
    assert not any(p["title_id"] == TITLE_1.upper() for p in pending_after)


# ── Re-enable delivery ────────────────────────────────────────────────────────


def test_reenable_game_appears_after_next_upload(client, conn):
    """Disable then re-enable TITLE_1 for B; A uploads new save → B gets delivery."""
    token = _bootstrap(client)
    report_catalog(client, DEVICE_B, [TITLE_1])

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    # Still disabled — should not appear
    assert not any(p["title_id"] == TITLE_1.upper() for p in poll_queue(client, DEVICE_B))

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": True}])
    do_upload(client, DEVICE_A, TITLE_1, b"re-enabled-save")

    pending = poll_queue(client, DEVICE_B)
    assert any(p["title_id"] == TITLE_1.upper() for p in pending)


def test_cancelled_does_not_block_future_delivery(client, conn):
    """CANCELLED outbound for B/TITLE_1 must not prevent future delivery on re-enable."""
    token = _bootstrap(client)
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    # Confirm CANCELLED row exists
    row = conn.execute(
        "SELECT state FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND title_id=?",
        (DEVICE_B, TITLE_1.upper()),
    ).fetchone()
    assert row["state"] == "CANCELLED"

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": True}])
    do_upload(client, DEVICE_A, TITLE_1, b"post-cancel-save")

    pending = poll_queue(client, DEVICE_B)
    assert any(p["title_id"] == TITLE_1.upper() for p in pending), \
        "CANCELLED row must not block future delivery discovery"


# ── CANCELLED is terminal and non-retryable ───────────────────────────────────


def test_retry_cannot_revive_cancelled(client, conn):
    """retry_outbound must not transition CANCELLED → READY_FOR_RESTORE."""
    token = _bootstrap(client)
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    cancelled_txn = conn.execute(
        "SELECT transaction_id FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND state='CANCELLED'",
        (DEVICE_B,),
    ).fetchone()
    assert cancelled_txn is not None
    txn_id = cancelled_txn["transaction_id"]

    r = client.post(
        f"/api/v1/ui/outbounds/{txn_id}/retry",
        headers=_hdr(token),
    )
    assert r.status_code in (404, 400, 409), "retry must reject CANCELLED rows"

    state = conn.execute(
        "SELECT state FROM sync_transactions WHERE transaction_id=?", (txn_id,)
    ).fetchone()["state"]
    assert state == "CANCELLED", "state must remain CANCELLED after rejected retry"


# ── Queue response includes sync_prefs ───────────────────────────────────────


def test_queue_returns_sync_prefs(client, conn):
    """/queue response includes sync_prefs map for the polling device."""
    token = _bootstrap(client)
    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])

    r = queue_get(client, DEVICE_B)
    assert r.status_code == 200
    body = r.json()
    assert "sync_prefs" in body
    assert body["sync_prefs"].get(TITLE_1) is False


def test_queue_sync_prefs_empty_for_new_device(client, conn):
    """/queue returns empty sync_prefs map when device has no stored preferences."""
    r = queue_get(client, DEVICE_B)
    assert r.status_code == 200
    body = r.json()
    assert "sync_prefs" in body
    assert body["sync_prefs"] == {}


def test_queue_game_names_populated_when_titledb_has_name(client, conn, monkeypatch):
    """/queue game_names includes server-resolved title name for pending items."""
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name",
                        lambda tid, conn=None: "New Pokemon Snap" if tid == TITLE_1.upper() else None)

    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, b"snap-save")
    r = queue_get(client, DEVICE_B)
    assert r.status_code == 200
    body = r.json()
    assert "game_names" in body
    assert body["game_names"].get(TITLE_1.upper()) == "New Pokemon Snap"


def test_queue_game_names_empty_when_titledb_unknown(client, conn, monkeypatch):
    """/queue game_names is empty when titledb has no name for the title."""
    import titledb
    monkeypatch.setattr(titledb, "resolve_game_name", lambda tid, conn=None: None)

    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, b"snap-save")
    r = queue_get(client, DEVICE_B)
    assert r.status_code == 200
    body = r.json()
    assert body.get("game_names", {}) == {}


# ── Default-allow: unknown titles ────────────────────────────────────────────


def test_enabled_by_default_when_no_prefs(client, conn):
    """With no sync_prefs set, all titles are enabled (default allow)."""
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    assert any(p["title_id"] == TITLE_1.upper() for p in pending), \
        "default-allow: title must appear when no prefs set"


def test_disabling_one_title_does_not_block_another(client, conn):
    """Disabling TITLE_1 for B must not suppress TITLE_2 delivery."""
    token = _bootstrap(client)
    _set_prefs(client, token, DEVICE_B, [{"title_id": TITLE_1, "enabled": False}])
    report_catalog(client, DEVICE_B, [TITLE_1, TITLE_2])

    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    do_upload(client, DEVICE_A, TITLE_2, b"title2-save")

    pending = poll_queue(client, DEVICE_B)
    title_ids = {p["title_id"] for p in pending}
    assert TITLE_1.upper() not in title_ids, "TITLE_1 must be suppressed"
    assert TITLE_2.upper() in title_ids, "TITLE_2 must still be delivered"
