from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from xcode_cli.qqchat.config import QQChatConfig
from xcode_cli.qqchat.service import QQChatService


class FakeGateway:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.on_event = None

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, conversation_key, turn, *, tool_scope=None):
        self.calls.append((conversation_key, turn, tool_scope))
        return type("Result", (), {"text": "assistant reply", "session_id": "session-1", "error": None})()


class FakeReplyClient:
    def __init__(self):
        self.calls = []

    def send_text_reply(self, target, *, content, msg_id, msg_seq):
        self.calls.append((target, content, msg_id, msg_seq))


def _c2c_payload(message_id="msg-1", *, user_openid="user-openid", timestamp=None):
    return {
        "op": 0,
        "t": "C2C_MESSAGE_CREATE",
        "id": "event-1",
        "d": {
            "id": message_id,
            "content": "你好",
            "timestamp": timestamp,
            "author": {"user_openid": user_openid},
        },
    }


def _group_payload(
    message_id="group-msg-1",
    *,
    group_openid="group-openid",
    member_openid="member-openid",
    timestamp=None,
):
    return {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "id": "event-2",
        "d": {
            "id": message_id,
            "content": "群里看一下",
            "timestamp": timestamp,
            "group_openid": group_openid,
            "author": {"member_openid": member_openid},
        },
    }


def _wait_until_idle(service, timeout=1.0):
    assert service.wait_until_idle(timeout=timeout) is True


def test_start_is_idempotent():
    gateway = FakeGateway()
    service = QQChatService(gateway=gateway, runner=FakeRunner(), reply_client=FakeReplyClient())

    service.start()
    service.start()

    assert gateway.started == 1
    assert service.status()["state"] == "running"


def test_stop_closes_gateway():
    gateway = FakeGateway()
    service = QQChatService(gateway=gateway, runner=FakeRunner(), reply_client=FakeReplyClient())

    service.start()
    service.stop()

    assert gateway.stopped == 1
    assert service.status()["state"] == "stopped"


def test_handle_event_runs_external_turn_and_replies():
    runner = FakeRunner()
    replies = FakeReplyClient()
    service = QQChatService(gateway=FakeGateway(), runner=runner, reply_client=replies)
    service.start()

    service.handle_gateway_event(_c2c_payload())
    _wait_until_idle(service)
    service.stop()

    assert runner.calls[0][0] == "qq:c2c:user-openid"
    assert runner.calls[0][2].visible_tools == ("read_file", "grep", "glob", "task_list")
    assert runner.calls[0][2].execution_allowlist == ("read_file", "grep", "glob", "task_list")
    assert runner.calls[0][2].remote_approval is False
    assert replies.calls[0][1] == "assistant reply"
    assert replies.calls[0][2] == "msg-1"


def test_duplicate_event_does_not_call_runner_twice():
    runner = FakeRunner()
    service = QQChatService(gateway=FakeGateway(), runner=runner, reply_client=FakeReplyClient())
    service.start()

    service.handle_gateway_event(_c2c_payload("msg-1"))
    service.handle_gateway_event(_c2c_payload("msg-1"))
    _wait_until_idle(service)
    service.stop()

    assert len(runner.calls) == 1


def test_gateway_event_is_queued_and_not_run_inline():
    runner_started = threading.Event()
    release_runner = threading.Event()

    class BlockingRunner(FakeRunner):
        def run(self, conversation_key, turn, *, tool_scope=None):
            runner_started.set()
            release_runner.wait(timeout=1)
            return super().run(conversation_key, turn, tool_scope=tool_scope)

    service = QQChatService(gateway=FakeGateway(), runner=BlockingRunner(), reply_client=FakeReplyClient())
    service.start()

    started_at = time.monotonic()
    service.handle_gateway_event(_c2c_payload())
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert runner_started.wait(timeout=1)
    release_runner.set()
    _wait_until_idle(service)
    service.stop()


def test_disabled_c2c_does_not_call_runner():
    runner = FakeRunner()
    cfg = QQChatConfig(app_id="app", client_secret="secret", enable_c2c=False)
    service = QQChatService(gateway=FakeGateway(), runner=runner, reply_client=FakeReplyClient(), config=cfg)
    service.start()

    service.handle_gateway_event(_c2c_payload())
    _wait_until_idle(service)
    service.stop()

    assert runner.calls == []


def test_disabled_config_prevents_start():
    cfg = QQChatConfig(app_id="app", client_secret="secret", enabled=False)
    service = QQChatService(gateway=FakeGateway(), runner=FakeRunner(), reply_client=FakeReplyClient(), config=cfg)

    try:
        service.start()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected disabled QQchat to raise")

    assert "disabled" in message
    assert service.status()["state"] == "disabled"


def test_disabled_group_or_non_allowlisted_group_does_not_call_runner():
    runner = FakeRunner()
    cfg = QQChatConfig(
        app_id="app",
        client_secret="secret",
        enable_group_at=True,
        group_allowlist=["allowed-group"],
    )
    service = QQChatService(gateway=FakeGateway(), runner=runner, reply_client=FakeReplyClient(), config=cfg)
    service.start()

    service.handle_gateway_event(_group_payload(group_openid="blocked-group"))
    _wait_until_idle(service)
    service.stop()

    assert runner.calls == []


def test_owner_openids_limits_c2c_and_group_senders():
    runner = FakeRunner()
    cfg = QQChatConfig(app_id="app", client_secret="secret", owner_openids=["owner-openid"])
    service = QQChatService(gateway=FakeGateway(), runner=runner, reply_client=FakeReplyClient(), config=cfg)
    service.start()

    service.handle_gateway_event(_c2c_payload("msg-a", user_openid="other-openid"))
    service.handle_gateway_event(_group_payload("msg-b", member_openid="other-member"))
    _wait_until_idle(service)
    service.stop()

    assert runner.calls == []


def test_reply_content_is_truncated_to_configured_limit():
    class LongReplyRunner(FakeRunner):
        def run(self, conversation_key, turn, *, tool_scope=None):
            return type("Result", (), {"text": "abcdef", "session_id": "session-1", "error": None})()

    replies = FakeReplyClient()
    cfg = QQChatConfig(app_id="app", client_secret="secret", max_reply_chars=3)
    service = QQChatService(gateway=FakeGateway(), runner=LongReplyRunner(), reply_client=replies, config=cfg)
    service.start()

    service.handle_gateway_event(_c2c_payload())
    _wait_until_idle(service)
    service.stop()

    assert replies.calls[0][1] == "abc"


def test_expired_group_message_is_ignored():
    runner = FakeRunner()
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    expired = (now - timedelta(seconds=301)).isoformat()
    cfg = QQChatConfig(app_id="app", client_secret="secret", group_turn_timeout_seconds=300)
    service = QQChatService(
        gateway=FakeGateway(),
        runner=runner,
        reply_client=FakeReplyClient(),
        config=cfg,
        now=lambda: now,
    )
    service.start()

    service.handle_gateway_event(_group_payload(timestamp=expired))
    _wait_until_idle(service)
    service.stop()

    assert runner.calls == []


def test_gateway_status_updates_last_error():
    service = QQChatService(gateway=FakeGateway(), runner=FakeRunner(), reply_client=FakeReplyClient())

    service.handle_gateway_status("QQ gateway websocket closed")

    assert service.status()["last_error"] == "QQ gateway websocket closed"
