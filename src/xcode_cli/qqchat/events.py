from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


QQ_EVENT_C2C_MESSAGE_CREATE = "C2C_MESSAGE_CREATE"
QQ_EVENT_GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"


@dataclass(frozen=True)
class QQReplyTarget:
    kind: Literal["c2c", "group"]
    openid: str | None = None
    group_openid: str | None = None


@dataclass(frozen=True)
class QQIncomingMessage:
    event_id: str | None
    event_type: str
    message_id: str
    content: str
    timestamp: str | None
    conversation_key: str
    reply_target: QQReplyTarget
    author_openid: str | None
    group_openid: str | None
    member_openid: str | None
    raw_payload: dict[str, Any]


class QQEventNormalizer:
    def normalize(self, payload: Mapping[str, Any]) -> QQIncomingMessage | None:
        event_type = _string_or_none(payload.get("t"))
        if event_type == QQ_EVENT_C2C_MESSAGE_CREATE:
            return self._normalize_c2c(payload, event_type)
        if event_type == QQ_EVENT_GROUP_AT_MESSAGE_CREATE:
            return self._normalize_group(payload, event_type)
        return None

    def _normalize_c2c(self, payload: Mapping[str, Any], event_type: str) -> QQIncomingMessage | None:
        data = _mapping_or_none(payload.get("d"))
        if data is None:
            return None
        author = _mapping_or_none(data.get("author"))
        if author is None:
            return None

        message_id = _string_or_none(data.get("id"))
        user_openid = _string_or_none(author.get("user_openid"))
        if not message_id or not user_openid:
            return None

        return QQIncomingMessage(
            event_id=_string_or_none(payload.get("id")),
            event_type=event_type,
            message_id=message_id,
            content=_string_or_empty(data.get("content")),
            timestamp=_string_or_none(data.get("timestamp")),
            conversation_key=f"qq:c2c:{user_openid}",
            reply_target=QQReplyTarget(kind="c2c", openid=user_openid),
            author_openid=user_openid,
            group_openid=None,
            member_openid=None,
            raw_payload=dict(payload),
        )

    def _normalize_group(self, payload: Mapping[str, Any], event_type: str) -> QQIncomingMessage | None:
        data = _mapping_or_none(payload.get("d"))
        if data is None:
            return None
        author = _mapping_or_none(data.get("author"))
        if author is None:
            return None

        message_id = _string_or_none(data.get("id"))
        group_openid = _string_or_none(data.get("group_openid"))
        member_openid = _string_or_none(author.get("member_openid"))
        if not message_id or not group_openid or not member_openid:
            return None

        return QQIncomingMessage(
            event_id=_string_or_none(payload.get("id")),
            event_type=event_type,
            message_id=message_id,
            content=_string_or_empty(data.get("content")),
            timestamp=_string_or_none(data.get("timestamp")),
            conversation_key=f"qq:group:{group_openid}:member:{member_openid}",
            reply_target=QQReplyTarget(kind="group", group_openid=group_openid),
            author_openid=None,
            group_openid=group_openid,
            member_openid=member_openid,
            raw_payload=dict(payload),
        )


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""
