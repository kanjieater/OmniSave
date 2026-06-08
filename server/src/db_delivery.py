"""
Lazy peer-discovery helper for outbound delivery.

Finds READY_FOR_RESTORE inbound heads (latest sequence per title) that a
polling device should receive but does not yet have an active outbound for.
"""

import logging
from typing import Any

log = logging.getLogger(__name__)


def get_undelivered_heads(conn, device_id: str) -> list[dict[str, Any]]:
    """
    Return the latest non-conflict inbound transaction per title where
    device_id has not yet received it (no active outbound AND no completed
    delivery of this sequence or newer). Excludes saves from device_id itself.
    """
    rows = conn.execute(
        "SELECT st.transaction_id, st.title_id, COALESCE(st.user_key,'') AS user_key "
        "FROM sync_transactions st "
        "WHERE st.direction = 'inbound' "
        "  AND st.state = 'READY_FOR_RESTORE' "
        "  AND st.has_conflict = 0 "
        "  AND st.preservation = 0 "
        "  AND st.source_device_id != ? "
        "  AND st.snapshot_sequence = ("
        "      SELECT MAX(st2.snapshot_sequence) "
        "      FROM sync_transactions st2 "
        "      WHERE st2.title_id = st.title_id "
        "        AND COALESCE(st2.owner_user_id,'') = COALESCE(st.owner_user_id,'') "
        "        AND st2.direction = 'inbound' "
        "        AND st2.state = 'READY_FOR_RESTORE' "
        "        AND st2.has_conflict = 0 "
        "        AND st2.preservation = 0 "
        "        AND st2.source_device_id != ?"
        "  ) "
        "  AND NOT EXISTS ("
        "      SELECT 1 FROM sync_transactions outb "
        "      WHERE outb.direction = 'outbound' "
        "        AND outb.target_device_id = ? "
        "        AND outb.title_id = st.title_id "
        "        AND COALESCE(outb.owner_user_id,'') = COALESCE(st.owner_user_id,'') "
        "        AND outb.state IN ('READY_FOR_RESTORE','COMPLETED','FAILED') "
        "        AND outb.snapshot_sequence >= st.snapshot_sequence"
        "  )",
        (device_id, device_id, device_id),
    ).fetchall()
    return [dict(r) for r in rows]
