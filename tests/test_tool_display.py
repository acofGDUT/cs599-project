from __future__ import annotations

from xcode_cli.core.llm import ToolCall
from xcode_cli.core.tooling.display import ToolCallDisplay, ToolDisplayState


def test_collapsed_tool_summary_lists_count_and_names() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=False))
    calls = [
        ToolCall(id="1", name="read_file", args={"path": "a.py"}),
        ToolCall(id="2", name="grep", args={"pattern": "foo"}),
        ToolCall(id="3", name="glob", args={"pattern": "*.py"}),
    ]

    lines = display.render_calls(calls)

    assert len(lines) == 1
    assert "3" in lines[0]
    assert "read_file" in lines[0]
    assert "grep" in lines[0]
    assert "glob" in lines[0]


def test_expanded_tool_display_includes_arguments() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=True))
    calls = [ToolCall(id="1", name="read_file", args={"path": "a.py"})]

    lines = display.render_calls(calls)

    assert any("## tool.read_file" in line for line in lines)
    assert any("path:" in line and "a.py" in line for line in lines)


def test_collapsed_summary_marks_dangerous_tools() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=False))
    calls = [ToolCall(id="1", name="write_file", args={"path": "a.py", "content": "x"})]

    lines = display.render_calls(calls)

    assert "write_file" in lines[0]
    assert "danger" in lines[0].lower()


def test_collapsed_summary_marks_edit_file_as_dangerous() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=False))
    calls = [ToolCall(id="1", name="edit_file", args={"path": "a.py", "old_string": "a", "new_string": "b"})]

    lines = display.render_calls(calls)

    assert "edit_file" in lines[0]
    assert "danger" in lines[0].lower()


def test_collapsed_summary_marks_run_shell_as_dangerous() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=False))
    calls = [ToolCall(id="1", name="run_shell", args={"command": "ls"})]

    lines = display.render_calls(calls)

    assert "run_shell" in lines[0]
    assert "danger" in lines[0].lower()


def test_expanded_dangerous_tools_show_full_detail() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=True))
    calls = [ToolCall(id="1", name="run_shell", args={"command": "rm -rf /"})]

    lines = display.render_calls(calls)

    assert any("## tool.run_shell" in line for line in lines)
    assert any("command:" in line and "rm -rf /" in line for line in lines)


def test_empty_tool_calls_list() -> None:
    display = ToolCallDisplay(ToolDisplayState(expanded=False))

    lines = display.render_calls([])

    assert len(lines) == 1
    assert "0" in lines[0]
