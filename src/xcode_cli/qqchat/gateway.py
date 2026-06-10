from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

from xcode_cli.qqchat.events import QQ_EVENT_C2C_MESSAGE_CREATE, QQ_EVENT_GROUP_AT_MESSAGE_CREATE


QQ_API_BASE_URL = "https://api.sgroup.qq.com"
GROUP_AND_C2C_INTENTS = 1 << 25


def build_identify_payload(access_token: str, *, intents: int = GROUP_AND_C2C_INTENTS) -> dict[str, Any]:
    return {
        "op": 2,
        "d": {
            "token": f"QQBot {access_token}",
            "intents": intents,
            "shard": [0, 1],
            "properties": {
                "os": "windows",
                "browser": "xcode",
                "device": "xcode",
            },
        },
    }


def build_heartbeat_payload(seq: int | None) -> dict[str, Any]:
    return {"op": 1, "d": seq}


def build_resume_payload(access_token: str, *, session_id: str, seq: int | None) -> dict[str, Any]:
    return {
        "op": 6,
        "d": {"token": f"QQBot {access_token}", "session_id": session_id, "seq": seq},
    }


class UrllibGatewayTransport:
    def get_json(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: int = 10,
    ) -> tuple[int, object]:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, _decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode_json_response(exc.read())


class QQGatewayClient:
    def __init__(
        self,
        access_token_getter: Callable[[], str],
        *,
        transport=None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        websocket_app_factory=None,
        sleep: Callable[[float], None] | None = None,
        reconnect_base_delay: float = 1.0,
        max_reconnect_attempts: int | None = None,
    ) -> None:
        self._access_token_getter = access_token_getter
        self._transport = transport or UrllibGatewayTransport()
        self._on_event = on_event
        self._on_status = on_status
        self._websocket_app_factory = websocket_app_factory
        self._sleep = sleep or time.sleep
        self._reconnect_base_delay = reconnect_base_delay
        self._max_reconnect_attempts = max_reconnect_attempts
        self._seq: int | None = None
        self._session_id: str | None = None
        self._last_access_token = ""
        self._stop_event = threading.Event()
        self._reconnect_requested = False
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._websocket_app = None

    @property
    def on_event(self) -> Callable[[dict[str, Any]], None] | None:
        return self._on_event

    @on_event.setter
    def on_event(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self._on_event = callback

    @property
    def on_status(self) -> Callable[[str], None] | None:
        return self._on_status

    @on_status.setter
    def on_status(self, callback: Callable[[str], None] | None) -> None:
        self._on_status = callback

    @property
    def seq(self) -> int | None:
        return self._seq

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def fetch_gateway_url(self) -> str:
        access_token = self._get_access_token()
        headers = {"Authorization": f"QQBot {access_token}"}
        try:
            status, body = self._transport.get_json(f"{QQ_API_BASE_URL}/gateway", headers=headers, timeout=10)
        except Exception as exc:
            raise RuntimeError(f"QQ gateway request failed: {self._sanitize(str(exc))}") from exc

        if not 200 <= status < 300:
            reason = self._safe_reason(body)
            raise RuntimeError(f"QQ gateway request failed with status {status}: {reason}")
        if not isinstance(body, Mapping) or not isinstance(body.get("url"), str):
            raise RuntimeError("QQ gateway response missing websocket URL")
        return body["url"]

    def handle_payload(self, payload: dict[str, Any]) -> None:
        seq = payload.get("s")
        if isinstance(seq, int):
            self._seq = seq

        op = payload.get("op")
        if op == 7:
            self._reconnect_requested = True
            self._emit_status("QQ gateway reconnect requested")
            self._close_websocket()
            return
        if op == 9:
            self._session_id = None
            self._seq = None
            self._reconnect_requested = True
            self._emit_status("QQ gateway invalid session; reconnecting with identify")
            self._close_websocket()
            return

        event_type = payload.get("t")
        if event_type == "READY":
            data = payload.get("d")
            if isinstance(data, Mapping) and isinstance(data.get("session_id"), str):
                self._session_id = data["session_id"]

        if op == 0 and event_type in {QQ_EVENT_C2C_MESSAGE_CREATE, QQ_EVENT_GROUP_AT_MESSAGE_CREATE}:
            if self._on_event is None:
                return
            try:
                self._on_event(payload)
            except Exception as exc:
                self._emit_status(f"QQ gateway event callback failed: {self._sanitize(str(exc))}")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._reconnect_requested = False
        gateway_url = self.fetch_gateway_url()
        websocket_app_factory = self._websocket_app_factory or self._load_websocket_app_factory()

        self._thread = threading.Thread(
            target=lambda: self._run_forever_loop(gateway_url, websocket_app_factory),
            name="qq-gateway",
            daemon=True,
        )
        self._thread.start()

    def _load_websocket_app_factory(self):
        import websocket  # type: ignore[import-not-found]

        return websocket.WebSocketApp

    def _build_websocket_app(self, gateway_url: str, websocket_app_factory):
        def on_open(ws) -> None:
            access_token = self._get_access_token()
            if self._session_id:
                payload = build_resume_payload(access_token, session_id=self._session_id, seq=self._seq)
            else:
                payload = build_identify_payload(access_token)
            ws.send(json.dumps(payload))

        def on_message(ws, message: str) -> None:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError as exc:
                self._emit_status(f"QQ gateway received invalid JSON: {exc.msg}")
                return
            if not isinstance(payload, dict):
                self._emit_status("QQ gateway received non-object payload")
                return
            self.handle_payload(payload)
            if payload.get("op") == 10:
                data = payload.get("d")
                if isinstance(data, Mapping):
                    interval = data.get("heartbeat_interval")
                    if isinstance(interval, (int, float)):
                        self._start_heartbeat(ws, float(interval) / 1000.0)

        def on_error(_ws, error: object) -> None:
            self._emit_status(f"QQ gateway websocket error: {self._sanitize(str(error))}")

        def on_close(_ws, _status_code, _message) -> None:
            self._emit_status("QQ gateway websocket closed")

        return websocket_app_factory(
            gateway_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

    def _run_forever_loop(self, gateway_url: str, websocket_app_factory) -> None:
        reconnect_attempts = 0
        while not self._stop_event.is_set():
            self._websocket_app = self._build_websocket_app(gateway_url, websocket_app_factory)
            try:
                self._websocket_app.run_forever()
            except Exception as exc:
                self._emit_status(f"QQ gateway run loop failed: {self._sanitize(str(exc))}")

            if self._stop_event.is_set():
                return
            if self._max_reconnect_attempts is not None and reconnect_attempts >= self._max_reconnect_attempts:
                self._emit_status("QQ gateway reconnect limit reached")
                return

            reconnect_attempts += 1
            if self._reconnect_requested:
                self._reconnect_requested = False
            else:
                self._emit_status("QQ gateway disconnected; reconnecting")

            delay = min(self._reconnect_base_delay * (2 ** max(reconnect_attempts - 1, 0)), 30.0)
            if delay > 0:
                self._sleep(delay)
            if self._stop_event.is_set():
                return
            try:
                gateway_url = self.fetch_gateway_url()
            except Exception as exc:
                self._emit_status(f"QQ gateway reconnect fetch failed: {self._sanitize(str(exc))}")

    def stop(self) -> None:
        self._stop_event.set()
        self._close_websocket()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2)

    def wait_until_stopped(self, *, timeout: float = 1.0) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    def _start_heartbeat(self, ws, interval_seconds: float) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def run() -> None:
            while not self._stop_event.wait(interval_seconds):
                try:
                    ws.send(json.dumps(build_heartbeat_payload(self._seq)))
                except Exception as exc:
                    self._emit_status(f"QQ gateway heartbeat failed: {self._sanitize(str(exc))}")
                    return

        self._heartbeat_thread = threading.Thread(target=run, name="qq-gateway-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _get_access_token(self) -> str:
        access_token = self._access_token_getter()
        self._last_access_token = access_token
        return access_token

    def _close_websocket(self) -> None:
        if self._websocket_app is None:
            return
        try:
            self._websocket_app.close()
        except Exception as exc:
            self._emit_status(f"QQ gateway close failed: {self._sanitize(str(exc))}")

    def _safe_reason(self, body: object) -> str:
        if isinstance(body, Mapping):
            for key in ("message", "msg", "error_description", "error"):
                value = body.get(key)
                if value:
                    return self._sanitize(str(value))[:200]
        return "request rejected"

    def _sanitize(self, message: str) -> str:
        if self._last_access_token:
            message = message.replace(self._last_access_token, "<redacted>")
        return message

    def _emit_status(self, message: str) -> None:
        if self._on_status is None:
            return
        try:
            self._on_status(message)
        except Exception:
            return


def _decode_json_response(data: bytes) -> object:
    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"message": data.decode("utf-8", errors="replace")[:200]}
