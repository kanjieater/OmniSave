import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from fastapi.testclient import TestClient

import database as db
import processing
import sync_api
import sync_deliver_api
import ui_api
from main import app


@pytest.fixture()
def tmp_dirs(tmp_path):
    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    staging.mkdir()
    archive.mkdir()
    return staging, archive


@pytest.fixture()
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def sync_processing(monkeypatch):
    """Run background processing worker synchronously so tests don't race."""
    def _sync(txn_id, sess_id, staging, archive, conn_or_path):
        db_path = conn_or_path.path if hasattr(conn_or_path, "path") else conn_or_path
        processing._run(txn_id, sess_id, staging, archive, db_path)

    monkeypatch.setattr(processing, "submit", _sync)


@pytest.fixture()
def client(conn, tmp_dirs):
    staging, archive = tmp_dirs
    sync_api.init(conn, staging, archive)
    sync_deliver_api.init(conn, staging, archive)
    ui_api.init(conn, archive)
    return TestClient(app)


@pytest.fixture()
def device_token(client):
    """Pre-paired DEVICE_A token for tests that make raw sync API calls."""
    from helpers import pair_device, DEVICE_A
    return pair_device(client, DEVICE_A)
