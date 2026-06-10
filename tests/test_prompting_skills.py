from xcode_cli.core.config import Config
from xcode_cli.core.prompting import build_system_prompt


def test_system_prompt_includes_skill_listing_and_guidance():
    prompt = build_system_prompt(
        Config(max_tokens=128000),
        cwd="D:/Xcode",
        skill_listing="Available skills:\n- review: Review code changes",
    )

    assert "Available skills:" in prompt
    assert "- review: Review code changes" in prompt
    assert "call the skill tool" in prompt
    assert "Do not call the skill tool for weak or speculative matches." in prompt
    assert "Do not use the skill tool for built-in CLI commands." in prompt


def test_system_prompt_omits_skill_guidance_without_listing():
    prompt = build_system_prompt(Config(), cwd="D:/Xcode", skill_listing="")

    assert "call the skill tool" not in prompt
