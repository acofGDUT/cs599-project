from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping


TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
REFRESH_SKEW_SECONDS = 60


class UrllibJSONTransport:
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
        timeout: int = 10,
    ) -> tuple[int, object]:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            url,
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, _decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode_json_response(exc.read())


class QQAuthClient:
    def __init__(self, app_id: str, client_secret: str, *, transport=None, now=None) -> None:
        self._app_id = app_id
        self._client_secret = client_secret
        self._transport = transport or UrllibJSONTransport()
        self._now = now or time.time
        self._access_token: str | None = None
        self._expires_at = 0.0

    def get_access_token(self) -> str:
        now = float(self._now())
        if self._access_token and now < self._expires_at - REFRESH_SKEW_SECONDS:
            return self._access_token

        payload = {"appId": self._app_id, "clientSecret": self._client_secret}
        try:
            status, body = self._transport.post_json(TOKEN_URL, payload, timeout=10)
        except Exception as exc:
            raise RuntimeError(f"QQ auth request failed: {self._sanitize(str(exc))}") from exc

        if status != 200:
            reason = self._safe_reason(body)
            raise RuntimeError(f"QQ auth failed with status {status}: {reason}")

        if not isinstance(body, Mapping):
            raise RuntimeError("QQ auth failed: response body is not a JSON object")
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("QQ auth failed: response missing access_token")
        try:
            expires_in_seconds = int(expires_in)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("QQ auth failed: response missing expires_in") from exc

        self._access_token = access_token
        self._expires_at = now + expires_in_seconds
        return access_token

    def clear_cache(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    def _safe_reason(self, body: object) -> str:
        if isinstance(body, Mapping):
            for key in ("error_description", "error", "message", "msg"):
                value = body.get(key)
                if value:
                    return self._sanitize(str(value))[:200]
        return "request rejected"

    def _sanitize(self, message: str) -> str:
        if self._client_secret:
            message = message.replace(self._client_secret, "<redacted>")
        message = message.replace("Authorization", "<authorization>")
        message = message.replace("authorization", "<authorization>")
        return message


def _decode_json_response(data: bytes) -> object:
    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"message": data.decode("utf-8", errors="replace")[:200]}
