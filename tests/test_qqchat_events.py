from xcode_cli.qqchat.dedupe import QQMessageDedupe
from xcode_cli.qqchat.events import QQEventNormalizer


def test_normalize_c2c_message_create():
    payload = {
        "op": 0,
        "s": 42,
        "t": "C2C_MESSAGE_CREATE",
        "id": "event-1",
        "d": {
            "id": "msg-1",
            "content": "你好 Xcode",
            "timestamp": "2026-06-05T12:00:00+08:00",
            "author": {"user_openid": "user-openid"},
        },
    }

    result = QQEventNormalizer().normalize(payload)

    assert result is not None
    assert result.event_id == "event-1"
    assert result.event_type == "C2C_MESSAGE_CREATE"
    assert result.message_id == "msg-1"
    assert result.content == "你好 Xcode"
    assert result.conversation_key == "qq:c2c:user-openid"
    assert result.reply_target.kind == "c2c"
    assert result.reply_target.openid == "user-openid"


def test_normalize_group_at_message_create():
    payload = {
        "op": 0,
        "s": 43,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "id": "event-2",
        "d": {
            "id": "msg-2",
            "content": "@机器人 看一下 README",
            "group_openid": "group-openid",
            "author": {"member_openid": "member-openid"},
        },
    }

    result = QQEventNormalizer().normalize(payload)

    assert result is not None
    assert result.event_type == "GROUP_AT_MESSAGE_CREATE"
    assert result.group_openid == "group-openid"
    assert result.member_openid == "member-openid"
    assert result.conversation_key == "qq:group:group-openid:member:member-openid"
    assert result.reply_target.kind == "group"
    assert result.reply_target.group_openid == "group-openid"


def test_unknown_event_is_ignored():
    payload = {"op": 0, "t": "READY", "d": {}}

    assert QQEventNormalizer().normalize(payload) is None


def test_message_dedupe_allows_first_message_only_and_allocates_seq():
    dedupe = QQMessageDedupe()

    assert dedupe.reserve("msg-1") == 1
    assert dedupe.reserve("msg-1") is None
    assert dedupe.reserve("msg-2") == 1
