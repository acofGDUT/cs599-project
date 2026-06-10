from __future__ import annotations

import json
import os
import time
from pathlib import Path

from xcode_cli.paths import ensure_xcode_home


class RuntimeStatusStore:
    STALE_TTL_MS = 24 * 60 * 60 * 1000

    def __init__(self) -> None:
        root = ensure_xcode_home()
        self._dir = root / "sessions"
        self._pid = os.getpid()

    @property
    def _path(self) -> Path:
        return self._dir / f"{self._pid}.json"

    def create(self, session_id: str, cwd: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self.prune_stale()
        data = {
            "pid": self._pid,
            "sessionId": session_id,
            "cwd": cwd,
            "status": "idle",
            "updatedAt": int(time.time() * 1000),
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update(self, status: str) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        data["status"] = status
        data["updatedAt"] = int(time.time() * 1000)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update_session_id(self, session_id: str) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        data["sessionId"] = session_id
        data["updatedAt"] = int(time.time() * 1000)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def delete(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def prune_stale(self, ttl_ms: int | None = None) -> int:
        """Remove status files whose owning process is gone.

        Runtime status is advisory UI state. Cleanup must never block startup.
        """
        ttl = self.STALE_TTL_MS if ttl_ms is None else ttl_ms
        now_ms = int(time.time() * 1000)
        deleted = 0
        try:
            candidates = list(self._dir.glob("*.json"))
        except OSError:
            return 0

        for path in candidates:
            if path == self._path:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                if self._safe_unlink(path):
                    deleted += 1
                continue

            pid = self._coerce_pid(data.get("pid"), fallback=path.stem)
            if pid == self._pid:
                continue

            should_delete = False
            if pid is None:
                should_delete = self._is_ttl_expired(data.get("updatedAt"), now_ms, ttl)
            else:
                alive = self._pid_exists(pid)
                if alive is False:
                    should_delete = True
                elif alive is None:
                    should_delete = self._is_ttl_expired(data.get("updatedAt"), now_ms, ttl)

            if should_delete and self._safe_unlink(path):
                deleted += 1

        return deleted

    @staticmethod
    def _coerce_pid(value: object, *, fallback: str) -> int | None:
        for candidate in (value, fallback):
            try:
                pid = int(candidate)
            except (TypeError, ValueError):
                continue
            return pid if pid > 0 else None
        return None

    @staticmethod
    def _is_ttl_expired(updated_at: object, now_ms: int, ttl_ms: int) -> bool:
        try:
            updated_ms = int(updated_at)
        except (TypeError, ValueError):
            return True
        return updated_ms <= 0 or now_ms - updated_ms > ttl_ms

    @staticmethod
    def _safe_unlink(path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def _pid_exists(pid: int) -> bool | None:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            return RuntimeStatusStore._windows_pid_exists(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    @staticmethod
    def _windows_pid_exists(pid: int) -> bool | None:
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited_information = 0x1000
            still_active = 259
            error_invalid_parameter = 87
            error_access_denied = 5

            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int

            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                if not ok:
                    return None
                return exit_code.value == still_active

            error = ctypes.get_last_error()
            if error == error_invalid_parameter:
                return False
            if error == error_access_denied:
                return True
            return None
        except Exception:
            return None
