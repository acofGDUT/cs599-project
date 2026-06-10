from __future__ import annotations

from xcode_cli.core.ui.streaming import StreamingTurnRenderer


class _ConsoleSpy:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def print(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))


def test_plain_streaming_does_not_final_render_again() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="streaming_plus_final_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_text_token("hello")
    renderer.on_text_token(" world")
    result = renderer.finish("hello world")

    assert result.printed_stream is True
    assert result.needs_final_render is False
    assert not any(args and args[0] == "render" for args, _ in console.events)


def test_structured_markdown_stops_streaming_and_final_renders_once() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="streaming_plus_final_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_text_token("Here is code:\n")
    renderer.on_text_token("```python\n")
    renderer.on_text_token("print('hi')\n```")
    result = renderer.finish("Here is code:\n```python\nprint('hi')\n```")

    assert result.needs_final_render is True
    render_events = [args for args, _ in console.events if args and args[0] == "render"]
    assert len(render_events) == 1


def test_buffer_then_render_never_streams() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="buffer_then_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_text_token("hello")
    renderer.on_text_token(" world")
    result = renderer.finish("hello world")

    assert result.printed_stream is False
    assert result.needs_final_render is True


def test_table_detection_triggers_final_render() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="streaming_plus_final_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_text_token("Here is a table:\n")
    renderer.on_text_token("| a | b |\n")
    renderer.on_text_token("|---|---|\n")
    renderer.on_text_token("| 1 | 2 |")
    result = renderer.finish("Here is a table:\n| a | b |\n|---|---|\n| 1 | 2 |")

    assert result.needs_final_render is True


def test_heading_detection_triggers_final_render() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="streaming_plus_final_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_text_token("# Title\n")
    renderer.on_text_token("Some content")
    result = renderer.finish("# Title\nSome content")

    assert result.needs_final_render is True


def test_reasoning_tokens_buffered_not_streamed() -> None:
    console = _ConsoleSpy()
    renderer = StreamingTurnRenderer(
        console,
        render_mode="streaming_plus_final_render",
        render_markdown=lambda text: console.print("render", text),
    )

    renderer.on_reasoning_token("thinking...")
    renderer.on_reasoning_token(" more thinking")
    result = renderer.finish("")

    assert result.reasoning_content == "thinking... more thinking"
    assert result.printed_stream is False
