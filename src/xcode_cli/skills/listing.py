from __future__ import annotations

from xcode_cli.skills.model import Skill

SKILL_BUDGET_CONTEXT_PERCENT = 0.01
CHARS_PER_TOKEN = 4
DEFAULT_CHAR_BUDGET = 8_000
MAX_LISTING_DESC_CHARS = 250


def skill_listing_char_budget(context_window_tokens: int | None) -> int:
    if not isinstance(context_window_tokens, int) or context_window_tokens <= 0:
        return DEFAULT_CHAR_BUDGET
    return int(context_window_tokens * SKILL_BUDGET_CONTEXT_PERCENT * CHARS_PER_TOKEN)


class SkillListingFormatter:
    def format(self, skills: list[Skill], context_window_tokens: int | None) -> str:
        ordered = sorted(skills, key=lambda skill: skill.name.lower())
        budget = skill_listing_char_budget(context_window_tokens)

        for mode in ("full", "truncated", "name_only"):
            content = self._format_entries(ordered, mode=mode)
            if len(content) <= budget:
                return content
        return self._format_name_only_with_omissions(ordered, budget)

    def _format_entries(self, skills: list[Skill], *, mode: str) -> str:
        lines = ["Available skills:"]
        for skill in skills:
            if mode == "name_only":
                lines.append(f"- {skill.name}")
                continue
            summary = _summary(skill)
            if mode == "truncated":
                summary = _truncate(summary, MAX_LISTING_DESC_CHARS)
            lines.append(f"- {skill.name}: {summary}")
        return "\n".join(lines)

    def _format_name_only_with_omissions(self, skills: list[Skill], budget: int) -> str:
        lines = ["Available skills:"]
        omitted = 0
        for skill in skills:
            candidate = "\n".join([*lines, f"- {skill.name}"])
            if len(candidate) > budget:
                if len(lines) == 1:
                    lines.append(f"- {skill.name}")
                    continue
                omitted += 1
                continue
            lines.append(f"- {skill.name}")
        if omitted:
            suffix = f"- ... {omitted} skill(s) omitted due to context budget"
            if len("\n".join([*lines, suffix])) <= budget:
                lines.append(suffix)
        return "\n".join(lines)


def _summary(skill: Skill) -> str:
    parts = [skill.description.strip()]
    if skill.when_to_use:
        parts.append(f"when_to_use: {skill.when_to_use.strip()}")
    return " | ".join(part for part in parts if part)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = "...[truncated]"
    return text[: max(limit - len(suffix), 0)].rstrip() + suffix
