"""
Device game catalog tests.

Covers: catalog storage, catalog-driven fanout (commit-time + backfill),
queue as drain-only, idempotency, reinstall behavior, ordering convergence.
"""

import database as db
from helpers import DEVICE_A, DEVICE_B, TITLE_1, TITLE_2, do_upload, pair_device, poll_queue, report_catalog, sync_hdrs

SAVE = b"catalog-test-save-" * 100
DEVICE_C = "CC0011DDEEFF"


# ── Catalog storage ────────────────────────────────────────────────────────────


def test_report_catalog_stores_rows(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1, TITLE_2])
    rows = conn.execute(
        "SELECT title_id FROM device_installed_games WHERE device_id=? ORDER BY title_id",
        (DEVICE_A,),
    ).fetchall()
    assert {r["title_id"] for r in rows} == {TITLE_1.upper(), TITLE_2.upper()}


def test_report_catalog_full_replace(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1, TITLE_2])
    # Report shorter list — TITLE_2 should disappear
    report_catalog(client, DEVICE_A, [TITLE_1])
    rows = conn.execute(
        "SELECT title_id FROM device_installed_games WHERE device_id=?", (DEVICE_A,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["title_id"] == TITLE_1.upper()


def test_report_catalog_idempotent(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1])
    report_catalog(client, DEVICE_A, [TITLE_1])
    count = conn.execute(
        "SELECT COUNT(*) FROM device_installed_games WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 1


def test_report_catalog_empty_clears_all(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1, TITLE_2])
    report_catalog(client, DEVICE_A, [])
    count = conn.execute(
        "SELECT COUNT(*) FROM device_installed_games WHERE device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 0


def test_report_catalog_invalid_title_id_rejected(client):
    r = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": ["not-valid-hex"]},
        headers={"X-Device-ID": DEVICE_A},
    )
    assert r.status_code == 400


def test_report_catalog_separate_per_device(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1])
    report_catalog(client, DEVICE_B, [TITLE_2])
    a_titles = {r["title_id"] for r in conn.execute(
        "SELECT title_id FROM device_installed_games WHERE device_id=?", (DEVICE_A,)
    ).fetchall()}
    b_titles = {r["title_id"] for r in conn.execute(
        "SELECT title_id FROM device_installed_games WHERE device_id=?", (DEVICE_B,)
    ).fetchall()}
    assert a_titles == {TITLE_1.upper()}
    assert b_titles == {TITLE_2.upper()}


# ── Commit-time fanout ─────────────────────────────────────────────────────────


def test_catalog_peer_gets_outbound_at_commit_time(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    rows = conn.execute(
        "SELECT state FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["state"] == "READY_FOR_RESTORE"


def test_uncataloged_device_gets_no_outbound_at_commit_time(client, conn):
    # DEVICE_B not in catalog — should get nothing
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]
    assert count == 0


def test_source_device_excluded_from_commit_fanout(client, conn):
    report_catalog(client, DEVICE_A, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=?", (DEVICE_A,)
    ).fetchone()[0]
    assert count == 0


def test_commit_fanout_multiple_catalog_peers(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    report_catalog(client, DEVICE_C, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    for device_id in (DEVICE_B, DEVICE_C):
        count = conn.execute(
            "SELECT COUNT(*) FROM sync_transactions "
            "WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
            (device_id,),
        ).fetchone()[0]
        assert count == 1


# ── Queue is drain-only ────────────────────────────────────────────────────────


def test_queue_never_creates_outbound_rows(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]

    # B is not in catalog — queue poll must not create rows
    poll_queue(client, DEVICE_B)

    after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound'"
    ).fetchone()[0]
    assert after == before


def test_queue_returns_existing_outbound_rows(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1
    assert pending[0]["title_id"] == TITLE_1.upper()


# ── Catalog backfill ───────────────────────────────────────────────────────────


def test_backfill_creates_outbound_when_catalog_added_after_upload(client, conn):
    # Upload first, DEVICE_B not yet in catalog
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    count_before = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]
    assert count_before == 0

    # B reports catalog — backfill must create outbound for the existing inbound HEAD
    report_catalog(client, DEVICE_B, [TITLE_1])

    count_after = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]
    assert count_after == 1


def test_backfill_idempotent_same_catalog_twice(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    report_catalog(client, DEVICE_B, [TITLE_1])
    report_catalog(client, DEVICE_B, [TITLE_1])  # second time — no new rows

    count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (DEVICE_B,),
    ).fetchone()[0]
    assert count == 1


def test_backfill_no_rows_when_no_inbound_head(client, conn):
    # No inbound uploads yet — backfill creates nothing
    report_catalog(client, DEVICE_B, [TITLE_1])

    count = conn.execute(
        "SELECT COUNT(*) FROM sync_transactions WHERE direction='outbound' AND target_device_id=?",
        (DEVICE_B,),
    ).fetchone()[0]
    assert count == 0


def test_backfill_only_creates_outbound_for_reported_titles(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    do_upload(client, DEVICE_A, TITLE_2, b"title2-save")

    # B only reports TITLE_1
    report_catalog(client, DEVICE_B, [TITLE_1])

    titles_with_outbound = {r["title_id"] for r in conn.execute(
        "SELECT title_id FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=?", (DEVICE_B,)
    ).fetchall()}
    assert TITLE_1.upper() in titles_with_outbound
    assert TITLE_2.upper() not in titles_with_outbound


# ── Ordering convergence ───────────────────────────────────────────────────────


def test_upload_first_catalog_later_converges(client, conn):
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    report_catalog(client, DEVICE_B, [TITLE_1])

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1


def test_catalog_first_upload_later_converges(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    assert len(pending) == 1


def test_catalog_removal_stops_future_fanout(client, conn):
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    # B has outbound now
    assert len(poll_queue(client, DEVICE_B)) == 1

    # B removes title from catalog
    report_catalog(client, DEVICE_B, [])

    # New upload for same title — B should not receive it
    do_upload(client, DEVICE_A, TITLE_1, b"newer-save")

    # Only the original outbound for seq=1; no new outbound for seq=2
    outbounds = conn.execute(
        "SELECT snapshot_sequence, state FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? ORDER BY snapshot_sequence",
        (DEVICE_B,),
    ).fetchall()
    seqs = [r["snapshot_sequence"] for r in outbounds if r["state"] != "SUPERSEDED"]
    assert len(seqs) <= 1


def test_reinstall_backfill_delivers_latest_head(client, conn):
    """Title removed from catalog, new upload arrives, title re-added → backfill delivers new HEAD."""
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)
    poll_queue(client, DEVICE_B)  # drain

    # Remove from catalog
    report_catalog(client, DEVICE_B, [])

    # New upload arrives while B has no catalog entry
    do_upload(client, DEVICE_A, TITLE_1, b"save-v2")

    # Re-add to catalog — backfill should deliver the latest HEAD (seq=2)
    report_catalog(client, DEVICE_B, [TITLE_1])

    pending = poll_queue(client, DEVICE_B)
    # There should be an outbound for seq=2 (the latest)
    active = [p for p in pending if p["title_id"] == TITLE_1.upper()]
    assert len(active) >= 1
    assert max(p["snapshot_sequence"] for p in active) == 2


def test_backfill_resolves_profile_per_title(client, conn):
    """Regression: target_profile_uid must be resolved per title, not once for the whole device.

    DEVICE_C has prior upload history with different Nintendo profiles per game.
    DEVICE_A uploads newer saves. Backfill should assign PROFILE_X to TITLE_1 and
    PROFILE_Y to TITLE_2, not a single device-default for both.
    """
    # Establish per-title profile history on DEVICE_C
    do_upload(client, DEVICE_C, TITLE_1, b"c-save-t1", user_key="PROFILE_X")
    do_upload(client, DEVICE_C, TITLE_2, b"c-save-t2", user_key="PROFILE_Y")

    # DEVICE_A uploads newer versions — these become the inbound HEADs
    do_upload(client, DEVICE_A, TITLE_1, b"a-save-t1-v2", user_key="PROFILE_X")
    do_upload(client, DEVICE_A, TITLE_2, b"a-save-t2-v2", user_key="PROFILE_Y")

    # DEVICE_C reports catalog — backfill fires (DEVICE_A's HEADs need delivery to DEVICE_C)
    report_catalog(client, DEVICE_C, [TITLE_1, TITLE_2])

    rows = conn.execute(
        "SELECT title_id, target_profile_uid FROM sync_transactions "
        "WHERE direction='outbound' AND target_device_id=? AND state='READY_FOR_RESTORE'",
        (DEVICE_C,),
    ).fetchall()
    profile_by_title = {r["title_id"]: r["target_profile_uid"] for r in rows}

    assert profile_by_title.get(TITLE_1.upper()) == "PROFILE_X"
    assert profile_by_title.get(TITLE_2.upper()) == "PROFILE_Y"


def test_backfill_does_not_redeliver_completed_snapshot(client, conn):
    """Re-reporting same catalog after ACK must not re-queue the completed snapshot."""
    report_catalog(client, DEVICE_B, [TITLE_1])
    do_upload(client, DEVICE_A, TITLE_1, SAVE)

    pending = poll_queue(client, DEVICE_B)
    txn_id = pending[0]["transaction_id"]

    # ACK the delivery
    tok_b = pair_device(client, DEVICE_B)
    client.post("/api/v1/sync/ack", json={"transaction_id": txn_id},
                headers=sync_hdrs(DEVICE_B, tok_b))

    # Re-report same catalog
    report_catalog(client, DEVICE_B, [TITLE_1])

    # Queue should be empty — no re-delivery of completed snapshot
    assert poll_queue(client, DEVICE_B) == []
