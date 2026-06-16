import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _ImmediateThread:
    """Runs the target synchronously so tests are deterministic."""

    def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def test_prefetch_starts_us_warmup(monkeypatch):
    """prefetch() starts the warmup thread when _db_us is None and no custom path."""
    import titledb

    calls = []
    monkeypatch.setattr(titledb, "_db_us", None)
    monkeypatch.setattr(titledb, "_warmup_us_started", False)
    monkeypatch.setattr(titledb, "_ensure_us", lambda: calls.append("ensure"))
    monkeypatch.setattr(titledb, "_fetch_and_cache", lambda *a, **kw: None)
    monkeypatch.setattr(titledb.threading, "Thread", _ImmediateThread)

    titledb.prefetch()

    assert "ensure" in calls


def test_prefetch_skips_warmup_if_already_loaded(monkeypatch):
    """prefetch() skips warmup if _db_us is already populated."""
    import titledb

    calls = []
    monkeypatch.setattr(titledb, "_db_us", {"already": "loaded"})
    monkeypatch.setattr(titledb, "_warmup_us_started", False)
    monkeypatch.setattr(titledb, "_ensure_us", lambda: calls.append("ensure"))
    monkeypatch.setattr(titledb, "_fetch_and_cache", lambda *a, **kw: None)
    monkeypatch.setattr(titledb.threading, "Thread", _ImmediateThread)

    titledb.prefetch()

    assert "ensure" not in calls
