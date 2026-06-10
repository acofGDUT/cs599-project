from xcode_cli.qqchat.events import QQReplyTarget
from xcode_cli.qqchat.message_client import QQMessageClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def post_json(self, url, payload, headers=None, timeout=10):
        self.calls.append((url, payload, headers or {}, timeout))
        return 200, {"id": "sent-message"}


def test_send_c2c_reply_uses_v2_user_endpoint():
    transport = FakeTransport()
    client = QQMessageClient(access_token_getter=lambda: "token", transport=transport)

    client.send_text_reply(
        QQReplyTarget(kind="c2c", openid="user-openid"),
        content="收到",
        msg_id="msg-1",
        msg_seq=1,
    )

    url, payload, headers, _timeout = transport.calls[0]
    assert url == "https://api.sgroup.qq.com/v2/users/user-openid/messages"
    assert headers["Authorization"] == "QQBot token"
    assert payload == {"content": "收到", "msg_type": 0, "msg_id": "msg-1", "msg_seq": 1}


def test_send_group_reply_uses_v2_group_endpoint():
    transport = FakeTransport()
    client = QQMessageClient(access_token_getter=lambda: "token", transport=transport)

    client.send_text_reply(
        QQReplyTarget(kind="group", group_openid="group-openid"),
        content="收到",
        msg_id="msg-2",
        msg_seq=2,
    )

    url, payload, headers, _timeout = transport.calls[0]
    assert url == "https://api.sgroup.qq.com/v2/groups/group-openid/messages"
    assert headers["Authorization"] == "QQBot token"
    assert payload["msg_seq"] == 2


def test_send_error_masks_token():
    class ErrorTransport(FakeTransport):
        def post_json(self, url, payload, headers=None, timeout=10):
            return 401, {"message": "bad secret-token Authorization"}

    client = QQMessageClient(access_token_getter=lambda: "secret-token", transport=ErrorTransport())

    try:
        client.send_text_reply(
            QQReplyTarget(kind="c2c", openid="user-openid"),
            content="收到",
            msg_id="msg-1",
            msg_seq=1,
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "secret-token" not in message
    assert "Authorization" not in message
    assert "401" in message
