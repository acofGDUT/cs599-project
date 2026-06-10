from xcode_cli.core.external_turn import ExternalTurnRunner, ToolScope
from xcode_cli.core.turn import UserTurnInput


READ_ONLY_SCOPE = ToolScope(
    source="qqchat",
    visible_tools=("read_file", "grep", "glob", "task_list"),
    execution_allowlist=("read_file", "grep", "glob", "task_list"),
    remote_approval=False,
)


class FakeSessionStore:
    def __init__(self):
        self.next_id = 0
        self.messages = {}
        self.user_history = []

    def new_session_id(self):
        self.next_id += 1
        return f"session-{self.next_id}"

    def append_message(self, session_id, message):
        self.messages.setdefault(session_id, []).append(message)

    def append_user_history(self, session_id, display):
        self.user_history.append((session_id, display))


class FakeLoop:
    def __init__(self):
        self.calls = []
        self.session_ids = []

    def __call__(self, *, history, system_prompt, tool_scope, session_id=None):
        self.calls.append((list(history), system_prompt, tool_scope))
        self.session_ids.append(session_id)
        return "assistant reply"


def test_different_conversation_keys_get_different_sessions():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(session_store=sessions, run_llm_loop=loop, build_system_prompt=lambda: "system")

    first = runner.run("qq:c2c:user-a", UserTurnInput("QQ user-a: hi", "hi"), tool_scope=READ_ONLY_SCOPE)
    second = runner.run("qq:c2c:user-b", UserTurnInput("QQ user-b: hi", "hi"), tool_scope=READ_ONLY_SCOPE)

    assert first.session_id == "session-1"
    assert second.session_id == "session-2"
    assert loop.session_ids == ["session-1", "session-2"]


def test_same_conversation_key_reuses_history():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(session_store=sessions, run_llm_loop=loop, build_system_prompt=lambda: "system")

    runner.run("qq:c2c:user-a", UserTurnInput("QQ: first", "first"), tool_scope=READ_ONLY_SCOPE)
    runner.run("qq:c2c:user-a", UserTurnInput("QQ: second", "second"), tool_scope=READ_ONLY_SCOPE)

    second_history = loop.calls[1][0]
    assert [m["content"] for m in second_history if m["role"] == "user"] == ["first", "second"]
    assert "assistant reply" in [m["content"] for m in second_history if m["role"] == "assistant"]


def test_tool_scope_is_passed_to_loop_and_dangerous_tools_absent():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(session_store=sessions, run_llm_loop=loop, build_system_prompt=lambda: "system")

    runner.run(
        "qq:c2c:user-a",
        UserTurnInput(
            display_content="QQ: inspect",
            model_content="inspect",
            metadata={"external_source": "qq"},
        ),
        tool_scope=READ_ONLY_SCOPE,
    )

    tool_scope = loop.calls[0][2]
    assert tool_scope.visible_tools == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.execution_allowlist == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.remote_approval is False
    assert "write_file" not in tool_scope.visible_tools
    assert "edit_file" not in tool_scope.execution_allowlist
    assert "run_shell" not in tool_scope.execution_allowlist


def test_tool_scope_visible_tools_are_intersected_with_execution_allowlist():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(session_store=sessions, run_llm_loop=loop, build_system_prompt=lambda: "system")
    unsafe_scope = ToolScope(
        source="qqchat",
        visible_tools=("read_file", "grep", "write_file"),
        execution_allowlist=("read_file", "run_shell"),
        remote_approval=True,
    )

    runner.run("qq:c2c:user-a", UserTurnInput("QQ: inspect", "inspect"), tool_scope=unsafe_scope)

    tool_scope = loop.calls[0][2]
    assert tool_scope.visible_tools == ("read_file",)
    assert tool_scope.execution_allowlist == ("read_file",)
    assert tool_scope.remote_approval is False


def test_qq_turn_never_allows_dangerous_tools_even_if_config_attempts_to_add_them():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(
        session_store=sessions,
        run_llm_loop=loop,
        build_system_prompt=lambda: "system",
        default_tool_scope=ToolScope(
            source="qqchat",
            visible_tools=("read_file", "grep", "glob", "task_list", "run_shell"),
            execution_allowlist=("read_file", "grep", "glob", "task_list", "run_shell"),
            remote_approval=True,
        ),
    )

    runner.run("qq:c2c:user-a", UserTurnInput("QQ: run command", "run command"))

    tool_scope = loop.calls[0][2]
    assert tool_scope.visible_tools == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.execution_allowlist == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.remote_approval is False


def test_qq_turn_falls_back_to_safe_tools_if_config_only_lists_dangerous_tools():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(
        session_store=sessions,
        run_llm_loop=loop,
        build_system_prompt=lambda: "system",
        default_tool_scope=ToolScope(
            source="qqchat",
            visible_tools=("run_shell", "write_file"),
            execution_allowlist=("run_shell", "write_file"),
            remote_approval=True,
        ),
    )

    runner.run("qq:c2c:user-a", UserTurnInput("QQ: run command", "run command"))

    tool_scope = loop.calls[0][2]
    assert tool_scope.visible_tools == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.execution_allowlist == ("read_file", "grep", "glob", "task_list")
    assert tool_scope.remote_approval is False


def test_group_member_conversation_keys_do_not_share_history():
    sessions = FakeSessionStore()
    loop = FakeLoop()
    runner = ExternalTurnRunner(session_store=sessions, run_llm_loop=loop, build_system_prompt=lambda: "system")

    runner.run("qq:group:group-a:member:user-a", UserTurnInput("QQ: user-a first", "user-a first"))
    runner.run("qq:group:group-a:member:user-b", UserTurnInput("QQ: user-b first", "user-b first"))
    runner.run("qq:group:group-a:member:user-a", UserTurnInput("QQ: user-a second", "user-a second"))

    third_history = loop.calls[2][0]
    user_messages = [m["content"] for m in third_history if m["role"] == "user"]
    assert user_messages == ["user-a first", "user-a second"]
    assert "user-b first" not in user_messages


def test_metadata_is_written_without_secret():
    sessions = FakeSessionStore()
    runner = ExternalTurnRunner(
        session_store=sessions,
        run_llm_loop=lambda **kwargs: "assistant reply",
        build_system_prompt=lambda: "system",
    )

    result = runner.run(
        "qq:c2c:user-a",
        UserTurnInput(
            display_content="QQ: hi",
            model_content="hi",
            metadata={
                "external_source": "qq",
                "access_token": "must-not-save",
                "client_secret": "must-not-save",
                "authorization": "must-not-save",
                "Authorization": "must-not-save",
                "app_secret": "must-not-save",
                "AppSecret": "must-not-save",
            },
        ),
        tool_scope=READ_ONLY_SCOPE,
    )

    user_message = sessions.messages[result.session_id][0]
    assert user_message["metadata"]["external_source"] == "qq"
    for key in ("access_token", "client_secret", "authorization", "Authorization", "app_secret", "AppSecret"):
        assert key not in user_message["metadata"]
