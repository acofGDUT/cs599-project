from __future__ import annotations

from dataclasses import dataclass, field


def _needs_rich_render(text: str) -> bool:
    return "```" in text or "\n|" in text or "\n#" in text or text.startswith("#")


@dataclass
class StreamingTurnResult:
    content: str
    reasoning_content: str
    printed_stream: bool
    needs_final_render: bool


@dataclass
class StreamingTurnRenderer:
    console: object
    render_mode: str
    render_markdown: object
    content_buffer: list[str] = field(default_factory=list)
    reasoning_buffer: list[str] = field(default_factory=list)
    printed_stream: bool = False
    _streaming_stopped_for_final_render: bool = False

    def on_text_token(self, token: str) -> None:
        self.content_buffer.append(token)

        if self.render_mode == "buffer_then_render":
            return

        if self._streaming_stopped_for_final_render:
            return

        accumulated = "".join(self.content_buffer)
        if _needs_rich_render(accumulated):
            self._streaming_stopped_for_final_render = True
            return

        self.console.print(token, end="", markup=False)
        self.printed_stream = True

    def on_reasoning_token(self, token: str) -> None:
        self.reasoning_buffer.append(token)

    def finish(self, final_text: str) -> StreamingTurnResult:
        reasoning_content = "".join(self.reasoning_buffer)

        if self.render_mode == "buffer_then_render":
            return StreamingTurnResult(
                content=final_text,
                reasoning_content=reasoning_content,
                printed_stream=False,
                needs_final_render=True,
            )

        if self._streaming_stopped_for_final_render:
            self.render_markdown(final_text)
            return StreamingTurnResult(
                content=final_text,
                reasoning_content=reasoning_content,
                printed_stream=self.printed_stream,
                needs_final_render=True,
            )

        return StreamingTurnResult(
            content=final_text,
            reasoning_content=reasoning_content,
            printed_stream=self.printed_stream,
            needs_final_render=False,
        )
