"""Queue batch-limit invariants: /queue returns at most 50 items (FIFO)."""

import uuid

from helpers import DEVICE_A, do_ack, pair_device, poll_queue

BATCH_SIZE = 50  # must match LIMIT in database.get_pending_outbound


def _seed_outbound_rows(conn, device_id: str, count: int) -> list[str]:
    """Insert `count` READY_FOR_RESTORE outbound rows directly.

    Returns transaction_ids in insertion order (oldest first by auto-increment id).
    """
    now = "2026-01-01T00:00:00Z"
    txn_ids = []
    for i in range(count):
        txn_id = str(uuid.uuid4())
        title_id = f"0100{i:012X}"
        conn.execute(
            "INSERT INTO sync_transactions "
            "(transaction_id,title_id,source_device_id,direction,state,snapshot_sequence,"
            "target_device_id,sha256,snapshot_path,total_size_bytes,checkpoint_ledger,"
            "user_key,target_profile_uid,owner_user_id,created_at,updated_at) "
            "VALUES (?,?,?,'outbound','READY_FOR_RESTORE',1,?,?,?,0,'[]','',NULL,NULL,?,?)",
            (txn_id, title_id, DEVICE_A, device_id, "a" * 64, "/app/data/archive/fake", now, now),
        )
        txn_ids.append(txn_id)
    conn.commit()
    return txn_ids


def test_queue_caps_pending_at_batch_size(client, conn):
    """More than BATCH_SIZE READY_FOR_RESTORE items → /queue returns exactly BATCH_SIZE."""
    device_id = "BATCHTEST0001"
    pair_device(client, device_id)
    _seed_outbound_rows(conn, device_id, BATCH_SIZE + 30)

    pending = poll_queue(client, device_id)
    assert len(pending) == BATCH_SIZE


def test_queue_returns_oldest_first(client, conn):
    """Returned items are the oldest (lowest id) rows — FIFO drain."""
    device_id = "BATCHTEST0002"
    pair_device(client, device_id)
    all_ids = _seed_outbound_rows(conn, device_id, BATCH_SIZE + 10)

    pending = poll_queue(client, device_id)
    returned = {item["transaction_id"] for item in pending}

    assert returned == set(all_ids[:BATCH_SIZE])


def test_queue_advances_after_ack(client, conn):
    """ACKing the first batch causes the next poll to return the next batch."""
    device_id = "BATCHTEST0003"
    token = pair_device(client, device_id)
    _seed_outbound_rows(conn, device_id, BATCH_SIZE + 10)

    batch1 = [item["transaction_id"] for item in poll_queue(client, device_id, token)]
    assert len(batch1) == BATCH_SIZE

    for txn_id in batch1:
        do_ack(client, device_id, txn_id, token)

    batch2 = [item["transaction_id"] for item in poll_queue(client, device_id, token)]
    assert len(batch2) == 10
    assert not set(batch1) & set(batch2)
