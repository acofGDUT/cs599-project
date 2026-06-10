from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable


def _friendly_llm_error(exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()

    if "401" in raw or "unauthorized" in lowered or "invalid api key" in lowered:
        return "认证失败（401）：API Key 无效或已过期，请检查 Key 是否正确。"
    if "403" in raw or "forbidden" in lowered or "permission" in lowered:
        return "权限不足（403）：当前 Key 没有访问该模型/接口的权限。"
    if "429" in raw or "rate limit" in lowered or "quota" in lowered or "insufficient_quota" in lowered:
        return "请求受限（429）：触发限流或额度不足，请稍后重试或检查套餐额度。"
    if "timeout" in lowered or "timed out" in lowered:
        return "请求超时：请检查网络连接、Base URL，或稍后重试。"

    return f"请求失败：{raw[:180]}"

from xcode_cli.core.config import ConfigStore


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    reasoning_content: str | None = None


class LLMClient:
    def __init__(self) -> None:
        # 配置在 complete() 时动态读取，确保 /env set 或 dashboard 修改立即生效
        pass

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict],
        on_text_token: Callable[[str], None] | None = None,
        on_reasoning_token: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        cfg = ConfigStore().load()
        model = os.getenv("XCODE_MODEL") or cfg.model or "gpt-4o-mini"
        base_url = os.getenv("XCODE_BASE_URL") or cfg.base_url or None
        api_key = os.getenv("XCODE_API_KEY") or cfg.api_key or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return LLMResponse(
                content=(
                    "[v0] Missing API key. Use /env set <key> to persist into ~/.xcode/config.json, "
                    "or set XCODE_API_KEY in your shell."
                ),
                tool_calls=[],
            )

        try:
            from openai import OpenAI
        except Exception:
            return LLMResponse(
                content="[v0] openai package not installed. Run: pip install openai",
                tool_calls=[],
            )

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                tools=tool_schemas,
                tool_choice="auto",
                temperature=0.2,
                stream=True,
            )
        except Exception as exc:
            friendly = _friendly_llm_error(exc)
            return LLMResponse(content=f"[v0] LLM request failed: {friendly}", tool_calls=[])

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    content_parts.append(delta.content)
                    if on_text_token:
                        on_text_token(delta.content)

                # Some OpenAI-compatible providers (e.g. DeepSeek reasoning models)
                # stream chain-of-thought in `reasoning_content` and require that it is
                # passed back verbatim in subsequent turns.
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_parts.append(rc)
                    if on_reasoning_token:
                        on_reasoning_token(rc)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index or 0
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "args": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["args"] += tc.function.arguments
        except Exception as exc:
            friendly = _friendly_llm_error(exc)
            return LLMResponse(content=f"[v0] LLM request failed: {friendly}", tool_calls=[])

        tool_calls: list[ToolCall] = []
        for tc_dict in tool_calls_acc.values():
            try:
                args = json.loads(tc_dict["args"]) if tc_dict["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc_dict["id"],
                    name=tc_dict["name"],
                    args=args,
                )
            )

        reasoning_content = "".join(reasoning_parts) if reasoning_parts else None
        return LLMResponse(content="".join(content_parts), tool_calls=tool_calls, reasoning_content=reasoning_content)
