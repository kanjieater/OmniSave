"""
Background PROCESSING worker.

Runs in a ThreadPoolExecutor after POST /sessions/{id}/commit succeeds.
Moves staging save.zip to archive, hashes, computes checkpoint ledger,
assigns global sequence, forks outbound transactions.

Product invariant: every unique-hash upload produces a stored snapshot.
has_conflict is diagnostic telemetry only — never blocks, never shown to user.
"""

import hashlib
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import xxhash

import database as db
import romm_meta

log = logging.getLogger(__name__)

EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="processing")

CHECKPOINT_SIZE = 4 * 1024 * 1024  # 4 MB — xxHash32 granularity
WINDOW_SIZE = 32 * 1024 * 1024  # 32 MB — HTTP transport granularity


def submit(
    transaction_id: str, session_id: str, staging_dir: Path, archive_dir: Path, conn_or_path
) -> None:
    db_path = conn_or_path.path if hasattr(conn_or_path, "path") else conn_or_path
    EXECUTOR.submit(_run, transaction_id, session_id, staging_dir, archive_dir, db_path)


def ingest_direct(
    title_id: str,
    source_device_id: str,
    save_bytes: bytes,
    staging_dir: Path,
    archive_dir: Path,
    conn,
    owner_user_id: str | None = None,
) -> str | None:
    """Inject save bytes directly into the processing pipeline (bypasses upload protocol)."""
    txn_id, session_id = db.create_processing_transaction(
        conn,
        source_device_id,
        title_id,
        len(save_bytes),
        parent_sequence_num=None,
        owner_user_id=owner_user_id,
    )
    conn.commit()
    staging_file = staging_dir / session_id / "save.zip"
    staging_file.parent.mkdir(parents=True, exist_ok=True)
    staging_file.write_bytes(save_bytes)
    db.log_event(
        conn,
        "ROMM_INGEST_STARTED",
        f"title={title_id}",
        title_id=title_id,
        device_id=source_device_id,
        transaction_id=txn_id,
    )
    submit(txn_id, session_id, staging_dir, archive_dir, conn)
    return txn_id


def _run(
    transaction_id: str,
    session_id: str,
    staging_dir: Path,
    archive_dir: Path,
    db_path: Path,
) -> None:
    conn = db.open_db(db_path)
    try:
        _process(transaction_id, session_id, staging_dir, archive_dir, conn)
    except Exception as exc:
        log.error("PROCESSING failed txn=%s: %s", transaction_id[:8], exc)
        db.fail_transaction(conn, transaction_id)  # no-op if txn already in terminal state
        cur = db.get_transaction(conn, transaction_id)
        owner = cur.get("owner_user_id") if cur else None
        if cur and cur["state"] in ("READY_FOR_RESTORE", "DEDUPED"):
            db.log_event(
                conn,
                "PROCESSING_SIDE_EFFECT_FAILED",
                str(exc),
                transaction_id=transaction_id,
                owner_user_id=owner,
            )
        else:
            db.log_event(
                conn,
                "PROCESSING_FAILED",
                str(exc),
                transaction_id=transaction_id,
                owner_user_id=owner,
            )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(65536):
            h.update(block)
    return h.hexdigest()


def _compute_ledger(path: Path) -> list[int]:
    ledger = []
    with path.open("rb") as f:
        while True:
            block = f.read(CHECKPOINT_SIZE)
            if not block:
                break
            ledger.append(xxhash.xxh32(block).intdigest())
    return ledger


def _process(
    transaction_id: str,
    session_id: str,
    staging_dir: Path,
    archive_dir: Path,
    conn,
) -> None:
    sess = db.get_session(conn, session_id)
    txn = db.get_transaction(conn, transaction_id)
    if not sess or not txn:
        raise ValueError("session or transaction missing")
    if txn["state"] != "PROCESSING":
        raise ValueError(f"unexpected state: {txn['state']}")

    staging_file = staging_dir / session_id / "save.zip"
    archive_path = archive_dir / transaction_id / "save.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    if staging_file.exists():
        shutil.move(str(staging_file), str(archive_path))
        try:
            (staging_dir / session_id).rmdir()
        except OSError:  # pragma: no cover
            pass
    elif not archive_path.exists():
        raise FileNotFoundError(f"staging file missing for session {session_id}")
    # else: archive already in place from a prior interrupted run — proceed from hash

    sha256 = _sha256(archive_path)
    ledger = _compute_ledger(archive_path)
    title_id = txn["title_id"]
    romm_meta.try_auto_match_async(title_id)
    source_device = txn["source_device_id"]
    is_preservation = bool(txn.get("preservation", 0))

    # ── Atomic critical section: dedup check + seq assignment ─────────────────
    # SHA256 is computed OUTSIDE the lock (CPU-bound; holding BEGIN IMMEDIATE
    # during a 487 MB hash would starve other workers).  Everything that touches
    # the counter or transaction state lives inside the lock.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if db.save_already_committed(conn, title_id, sha256):
            # Duplicate content — no new artifact, no sequence awarded.
            conn.execute(
                "UPDATE sync_transactions SET sha256=? WHERE transaction_id=?",
                (sha256, transaction_id),
            )
            archive_path.unlink(missing_ok=True)
            try:
                archive_path.parent.rmdir()
            except OSError:
                pass
            db.complete_dedup_transaction(conn, transaction_id)
            existing = conn.execute(
                "SELECT snapshot_sequence FROM sync_transactions"
                " WHERE title_id=? AND sha256=? AND direction='inbound'"
                " AND snapshot_sequence IS NOT NULL"
                " ORDER BY snapshot_sequence ASC LIMIT 1",
                (title_id.upper(), sha256),
            ).fetchone()
            matching_seq = existing["snapshot_sequence"] if existing else "?"
            db.log_event(
                conn,
                "SNAPSHOT_DEDUPLICATED",
                f"sha256={sha256[:12]}… content unchanged — matches seq={matching_seq} "
                f"(no new snapshot; prior version already committed)",
                title_id=title_id,
                device_id=source_device,
                transaction_id=transaction_id,
                owner_user_id=txn.get("owner_user_id"),
            )
            conn.commit()
            log.info("PROCESSING dedup txn=%s sha=%s…", transaction_id[:8], sha256[:12])
            return

        # New, unique content confirmed — assign sequence atomically.
        seq = db.next_global_sequence(conn, title_id)
        conn.execute(
            "UPDATE sync_transactions SET snapshot_sequence=? WHERE transaction_id=?",
            (seq, transaction_id),
        )

        head_seq = db.get_head_sequence(conn, title_id)
        device_last_seq = db.get_device_last_seq(conn, title_id, source_device)

        # Diagnostic divergence check: telemetry only, never blocks or rejects.
        if head_seq is not None and device_last_seq is not None and device_last_seq < head_seq:
            has_conflict_diag = True
            log.warning(
                "DIAG_DIVERGENCE txn=%s title=%s device=%s device_last=%s head=%s "
                "(diagnostic only — snapshot still stored)",
                transaction_id[:8],
                title_id,
                source_device,
                device_last_seq,
                head_seq,
            )
        else:
            has_conflict_diag = False

        db.set_transaction_ledger(conn, transaction_id, json.dumps(ledger))
        db.finalize_inbound(
            conn,
            transaction_id=transaction_id,
            sha256=sha256,
            snapshot_path=str(archive_path),
            snapshot_sequence=seq,
            has_conflict=False,  # always 0; has_conflict_diag is telemetry only
        )

        if not is_preservation:
            db.upsert_device_title_head(conn, title_id, source_device, seq)

        db.db_push_backup_update(conn, source_device, title_id, seq)
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK")
        raise

    committed_seq = db.get_transaction(conn, transaction_id)["snapshot_sequence"] or seq
    seq = committed_seq

    db.log_event(
        conn,
        "SNAPSHOT_STORED",
        f"seq={seq} sha256={sha256[:12]}… preservation={is_preservation} diag_divergence={has_conflict_diag}",
        title_id=title_id,
        device_id=source_device,
        transaction_id=transaction_id,
        owner_user_id=txn.get("owner_user_id"),
    )
    log.info(
        "PROCESSING done txn=%s seq=%d preservation=%s",
        transaction_id[:8],
        seq,
        is_preservation,
    )

    # Preservation uploads: archived, done. No fanout, HEAD not advanced.
    if is_preservation:
        return

    # RomM VSC participates via catalog fanout (device_installed_games) like any other client.
    # romm_worker.py consumes the outbound transaction it receives below.
    catalog_peers = db.get_catalog_members(conn, title_id, source_device)
    for peer in catalog_peers:
        try:
            # Cross-user guard: skip peers owned by a different user.
            # Applies to all device types — physical Switch and RomM alike.
            # A txn with no owner (legacy) is allowed through; a device with no owner
            # is treated as unregistered and skipped when the txn has an owner.
            peer_dev = db.get_device(conn, peer)
            txn_owner = txn.get("owner_user_id")
            if txn_owner:
                peer_owner = peer_dev.get("owner_user_id") if peer_dev else None
                if peer_owner != txn_owner:
                    log.info(
                        "skipping fanout peer=%s peer_owner=%s txn_owner=%s (cross-user block)",
                        peer,
                        peer_owner,
                        txn_owner,
                    )
                    continue
            prefs_json = db.get_config(conn, f"sync_prefs:{peer}")
            prefs = json.loads(prefs_json) if prefs_json else {}
            if not prefs.get(title_id, True):
                log.info(
                    "skipping catalog fanout peer=%s title=%s (sync disabled)", peer, title_id[:8]
                )
                continue
            target_profile = db.get_last_inbound_user_key(
                conn, peer, title_id, txn.get("owner_user_id")
            ) or db.get_device_default_profile(conn, peer)
            db.supersede_active_outbound(conn, peer, title_id, txn.get("owner_user_id") or "")
            outbound_id = db.create_outbound_transaction(
                conn, transaction_id, peer, target_profile_uid=target_profile
            )
            if outbound_id is None:
                log.warning(
                    "catalog fanout INSERT ignored (duplicate) peer=%s title=%s seq=%s",
                    peer,
                    title_id[:8],
                    seq,
                )
                continue
            db.log_event(
                conn,
                "OUTBOUND_CREATED",
                f"→ {peer} (catalog fanout)",
                title_id=title_id,
                device_id=peer,
                transaction_id=outbound_id,
                owner_user_id=txn.get("owner_user_id"),
            )
            log.info("catalog fanout outbound=%s for peer=%s", outbound_id[:8], peer)
        except Exception as exc:
            log.error("catalog fanout failed for peer=%s: %s", peer, exc)
