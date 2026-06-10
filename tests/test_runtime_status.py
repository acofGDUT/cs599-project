from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from xcode_cli.core.runtime_status import RuntimeStatusStore


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path, monkeypatch) -> RuntimeStatusStore:
    import xcode_cli.paths

    xcode_dir = tmp_path / ".xcode"
    monkeypatch.setattr(xcode_cli.paths, "XCODE_DIR", xcode_dir, raising=True)
    for sub in ("sessions", "skills", "bin"):
        (xcode_dir / sub).mkdir(parents=True, exist_ok=True)

    return RuntimeStatusStore()


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-123", "D:\\Xcode")
        assert store._path.exists()

    def test_file_uses_pid(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-123", "D:\\Xcode")
        assert store._path.name == f"{os.getpid()}.json"

    def test_content_has_expected_fields(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-456", "D:\\Work")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert data["sessionId"] == "sid-456"
        assert data["cwd"] == "D:\\Work"
        assert data["status"] == "idle"
        assert isinstance(data["updatedAt"], int)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_status(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-1", "D:\\Xcode")
        store.update("busy")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert data["status"] == "busy"

    def test_update_updates_timestamp(self, tmp_path: Path, monkeypatch) -> None:
        import time

        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-1", "D:\\Xcode")
        first_ts = json.loads(store._path.read_text(encoding="utf-8"))["updatedAt"]
        time.sleep(0.05)
        store.update("idle")
        second_ts = json.loads(store._path.read_text(encoding="utf-8"))["updatedAt"]
        assert second_ts >= first_ts

    def test_update_noop_when_file_missing(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.update("busy")

    def test_update_session_id(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-1", "D:\\Xcode")
        store.update_session_id("sid-2")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert data["sessionId"] == "sid-2"
        assert data["pid"] == os.getpid()

    def test_update_session_id_noop_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.update_session_id("sid-2")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_deletes_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-1", "D:\\Xcode")
        store.delete()
        assert not store._path.exists()


# ---------------------------------------------------------------------------
# prune stale
# ---------------------------------------------------------------------------

class TestPruneStale:
    def test_prune_deletes_dead_pid_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        stale_path = store._dir / "12345.json"
        stale_path.write_text(
            json.dumps({"pid": 12345, "sessionId": "stale", "updatedAt": int(time.time() * 1000)}),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "_pid_exists", lambda pid: False)

        assert store.prune_stale() == 1
        assert not stale_path.exists()

    def test_prune_preserves_alive_pid_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        alive_path = store._dir / "12345.json"
        alive_path.write_text(
            json.dumps({"pid": 12345, "sessionId": "alive", "updatedAt": int(time.time() * 1000)}),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "_pid_exists", lambda pid: True)

        assert store.prune_stale() == 0
        assert alive_path.exists()

    def test_prune_uses_ttl_when_liveness_is_unknown(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        stale_path = store._dir / "12345.json"
        old_updated_at = int(time.time() * 1000) - RuntimeStatusStore.STALE_TTL_MS - 1000
        stale_path.write_text(
            json.dumps({"pid": 12345, "sessionId": "unknown", "updatedAt": old_updated_at}),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "_pid_exists", lambda pid: None)

        assert store.prune_stale() == 1
        assert not stale_path.exists()

    def test_prune_preserves_fresh_unknown_pid_file(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        fresh_path = store._dir / "12345.json"
        fresh_path.write_text(
            json.dumps({"pid": 12345, "sessionId": "fresh", "updatedAt": int(time.time() * 1000)}),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "_pid_exists", lambda pid: None)

        assert store.prune_stale() == 0
        assert fresh_path.exists()

    def test_prune_ignores_corrupt_json_without_crashing(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        corrupt_path = store._dir / "bad.json"
        corrupt_path.write_text("{", encoding="utf-8")

        store.prune_stale()

        assert not corrupt_path.exists()

    def test_create_prunes_existing_stale_files(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        stale_path = store._dir / "12345.json"
        stale_path.write_text(
            json.dumps({"pid": 12345, "sessionId": "stale", "updatedAt": int(time.time() * 1000)}),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "_pid_exists", lambda pid: False)

        store.create("current", "D:\\Xcode")

        assert not stale_path.exists()
        assert store._path.exists()

    def test_delete_noop_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.delete()

    def test_create_update_delete_lifecycle(self, tmp_path: Path, monkeypatch) -> None:
        store = _make_store(tmp_path, monkeypatch)
        store.create("sid-life", "D:\\Xcode")
        assert store._path.exists()
        store.update("busy")
        assert json.loads(store._path.read_text(encoding="utf-8"))["status"] == "busy"
        store.update("idle")
        assert json.loads(store._path.read_text(encoding="utf-8"))["status"] == "idle"
        store.delete()
        assert not store._path.exists()
