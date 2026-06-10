from __future__ import annotations

from typing import Callable, Mapping

from xcode_cli.qqchat.auth import UrllibJSONTransport
from xcode_cli.qqchat.events import QQReplyTarget


QQ_API_BASE_URL = "https://api.sgroup.qq.com"


class QQMessageClient:
    def __init__(self, access_token_getter: Callable[[], str], *, transport=None) -> None:
        self._access_token_getter = access_token_getter
        self._transport = transport or UrllibJSONTransport()

    def send_text_reply(
        self,
        target: QQReplyTarget,
        *,
        content: str,
        msg_id: str,
        msg_seq: int,
    ) -> dict[str, object]:
        access_token = self._access_token_getter()
        url = self._reply_url(target)
        payload = {
            "content": content,
            "msg_type": 0,
            "msg_id": msg_id,
            "msg_seq": msg_seq,
        }
        headers = {"Authorization": f"QQBot {access_token}"}

        try:
            status, body = self._transport.post_json(url, payload, headers=headers, timeout=10)
        except Exception as exc:
            raise RuntimeError(f"QQ message send failed: {self._sanitize(str(exc), access_token)}") from exc

        if not 200 <= status < 300:
            reason = self._safe_reason(body, access_token)
            raise RuntimeError(f"QQ message send failed with status {status}: {reason}")
        return dict(body) if isinstance(body, Mapping) else {}

    def _reply_url(self, target: QQReplyTarget) -> str:
        if target.kind == "c2c" and target.openid:
            return f"{QQ_API_BASE_URL}/v2/users/{target.openid}/messages"
        if target.kind == "group" and target.group_openid:
            return f"{QQ_API_BASE_URL}/v2/groups/{target.group_openid}/messages"
        raise ValueError("QQ reply target is missing required openid")

    def _safe_reason(self, body: object, access_token: str) -> str:
        if isinstance(body, Mapping):
            for key in ("message", "msg", "error_description", "error"):
                value = body.get(key)
                if value:
                    return self._sanitize(str(value), access_token)[:200]
        return "request rejected"

    def _sanitize(self, message: str, access_token: str) -> str:
        if access_token:
            message = message.replace(access_token, "<redacted>")
        message = message.replace("Authorization", "<authorization>")
        message = message.replace("authorization", "<authorization>")
        return message
