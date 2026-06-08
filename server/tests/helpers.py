"""Shared test constants and HTTP-level helpers."""

import math

import xxhash


def login_admin(client, username: str = "admin", password: str = "admin") -> str:
    """Log in and return the session token."""
    r = client.post("/api/v1/ui/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["admin_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

DEVICE_A = "AABBCCDDEEFF"
DEVICE_B = "112233445566"
TITLE_1 = "0100F2C0115B6000"
TITLE_2 = "0100EC001DE7E000"

CHECKPOINT_SIZE = 4 * 1024 * 1024   # 4 MB — must match sync_api.CHECKPOINT_SIZE
WINDOW_SIZE = 32 * 1024 * 1024       # 32 MB


def compute_ledger(data: bytes) -> list[int]:
    """Compute xxHash32 checkpoint ledger for a byte string."""
    ledger = []
    for off in range(0, len(data), CHECKPOINT_SIZE):
        block = data[off : off + CHECKPOINT_SIZE]
        ledger.append(xxhash.xxh32(block).intdigest())
    return ledger if ledger else [xxhash.xxh32(data).intdigest()]


def pair_device(client, device_id: str) -> str:
    """Ensure device is registered and paired. Idempotent — returns existing token if already paired.

    Saves and restores the admin session so a caller's pre-existing admin token is not
    invalidated. Clears cookies afterward so no auth state leaks into subsequent requests.
    """
    import ui_api as _ui  # module-level _conn is initialised by the client fixture
    client.post("/api/v1/sync/device-config", json={}, headers={"X-Device-ID": device_id})

    # Idempotent: if already paired, return existing token without rotating
    existing = _ui._conn.execute(
        "SELECT device_token FROM device_auth WHERE device_id=?", (device_id,)
    ).fetchone()
    if existing and existing[0]:
        client.cookies.clear()
        return existing[0]

    # First pairing — save current admin token so we don't clobber it
    row = _ui._conn.execute("SELECT value FROM server_config WHERE key='admin_token'").fetchone()
    saved_token = row[0] if row else None

    admin_tok = login_admin(client)
    r = client.post(
        f"/api/v1/ui/devices/{device_id}/token",
        headers=auth_header(admin_tok),
    )
    assert r.status_code == 200, f"pair_device failed: {r.text}"
    device_token = r.json()["token"]

    if saved_token:
        _ui._conn.execute(
            "UPDATE server_config SET value=? WHERE key='admin_token'", (saved_token,)
        )
    client.cookies.clear()
    return device_token


def do_upload(
    client,
    device_id: str,
    title_id: str,
    data: bytes,
    parent_seq=None,
    preservation=False,
    user_key: str = "",
    user_display: str = "",
    device_token: str | None = None,
) -> str:
    """Full V2 upload through the HTTP API. Returns transaction_id (READY_FOR_RESTORE after).

    Auto-pairs the device as admin if no device_token is provided.
    """
    if device_token is None:
        device_token = pair_device(client, device_id)

    sync_headers = {"X-Device-ID": device_id, "Authorization": f"Bearer {device_token}"}

    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={
            "title_id": title_id,
            "total_size_bytes": len(data),
            "parent_sequence_num": parent_seq,
            "preservation": preservation,
            "user_key": user_key,
            "user_display": user_display,
        },
        headers=sync_headers,
    )
    assert r.status_code == 200, r.text
    txn_id = r.json()["transaction_id"]
    session_id = r.json()["session_id"]

    ledger = compute_ledger(data)
    r = client.post(
        f"/api/v1/sync/sessions/{session_id}/manifest",
        json={"checkpoint_size": CHECKPOINT_SIZE, "checkpoint_ledger": ledger},
        headers=sync_headers,
    )
    assert r.status_code == 200, r.text

    offset = 0
    while offset < len(data):
        window = data[offset : offset + WINDOW_SIZE]
        r = client.put(
            f"/api/v1/sync/sessions/{session_id}/window?offset={offset}",
            content=window,
            headers=sync_headers,
        )
        assert r.status_code == 200, r.text
        new_svb = r.json()["server_verified_bytes"]
        if new_svb <= offset:
            break
        offset = new_svb

    r = client.post(
        f"/api/v1/sync/sessions/{session_id}/commit",
        headers=sync_headers,
    )
    assert r.status_code in (200, 202), r.text
    return txn_id


def sync_hdrs(device_id: str, token: str) -> dict:
    return {"X-Device-ID": device_id, "Authorization": f"Bearer {token}"}


def start_inbound(client, device_id: str, title_id: str, total_size_bytes: int,
                  device_token: str | None = None) -> tuple[str, str, str]:
    """Pair device (or reuse token), open inbound transaction. Returns (txn_id, session_id, device_token)."""
    if device_token is None:
        device_token = pair_device(client, device_id)
    r = client.post(
        "/api/v1/sync/transactions/inbound",
        json={"title_id": title_id, "total_size_bytes": total_size_bytes},
        headers=sync_hdrs(device_id, device_token),
    )
    assert r.status_code == 200, r.text
    return r.json()["transaction_id"], r.json()["session_id"], device_token


def do_ack(client, device_id: str, txn_id: str, token: str | None = None) -> None:
    """ACK a completed download."""
    if token is None:
        token = pair_device(client, device_id)
    r = client.post(
        "/api/v1/sync/ack",
        json={"transaction_id": txn_id},
        headers={"X-Device-ID": device_id, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def queue_get(client, device_id: str, token: str | None = None, params: str = "") -> "Response":
    """GET /queue with auth. Auto-pairs device if no token given. Returns the raw Response."""
    if token is None:
        token = pair_device(client, device_id)
    url = f"/api/v1/sync/queue{('?' + params) if params else ''}"
    return client.get(url, headers=sync_hdrs(device_id, token))


def report_catalog(client, device_id: str, title_ids: list[str]) -> None:
    """Pair device (if not already) then enroll it in the game catalog.

    Pairing first ensures owner_user_id is stamped before any fanout check runs.
    """
    pair_device(client, device_id)
    r = client.post(
        "/api/v1/sync/device-config",
        json={"installed_titles": title_ids},
        headers={"X-Device-ID": device_id},
    )
    assert r.status_code == 200, f"report_catalog failed: {r.text}"


def poll_queue(client, device_id: str, token: str | None = None) -> list:
    """GET /queue and return the pending list. Auto-pairs the device if no token given."""
    if token is None:
        token = pair_device(client, device_id)
    r = client.get(
        "/api/v1/sync/queue",
        headers={"X-Device-ID": device_id, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["pending"]
