from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from xcode_cli.skills.model import Skill, SkillLoadNotice, SkillLoadResult


class SkillLoader:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)

    def load(self) -> SkillLoadResult:
        skills_root = self.project_root / ".xcode" / "skills"
        if not skills_root.exists():
            return SkillLoadResult(skills=[])

        skills: list[Skill] = []
        notices: list[SkillLoadNotice] = []
        for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                skills.append(self._load_skill(skill_dir, skill_md))
            except ValueError as exc:
                notices.append(SkillLoadNotice(path=skill_md, message=f"{skill_dir.name}: {exc}"))
        return SkillLoadResult(skills=skills, notices=notices)

    def _load_skill(self, skill_dir: Path, skill_md: Path) -> Skill:
        raw = skill_md.read_bytes()
        text = raw.decode("utf-8")
        frontmatter, body = _split_frontmatter(text)
        description = str(frontmatter.get("description") or _first_body_line(body))
        return Skill(
            name=skill_dir.name,
            display_name=_optional_string(frontmatter.get("name")),
            description=description,
            body=body,
            root=skill_dir,
            source_path=skill_md,
            source_hash=f"sha256:{hashlib.sha256(raw).hexdigest()}",
            allowed_tools=_string_list(frontmatter.get("allowed-tools")),
            argument_hint=_argument_hint(frontmatter.get("argument-hint")),
            argument_names=_string_list(frontmatter.get("arguments")),
            when_to_use=_optional_string(frontmatter.get("when_to_use")),
            model=_optional_string(frontmatter.get("model")),
            effort=_optional_string(frontmatter.get("effort")),
            disable_model_invocation=_bool(frontmatter.get("disable-model-invocation"), default=False),
            user_invocable=_bool(frontmatter.get("user-invocable"), default=True),
            context=_optional_string(frontmatter.get("context")),
            agent=_optional_string(frontmatter.get("agent")),
            paths=_string_list(frontmatter.get("paths")),
            hooks=_dict_or_none(frontmatter.get("hooks")),
            raw_frontmatter=frontmatter,
        )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, text

    end = normalized.find("\n---", 4)
    if end == -1:
        raise ValueError("invalid frontmatter: missing closing marker")

    raw = normalized[4:end]
    body = normalized[end + len("\n---"):].lstrip("\r\n")
    return _parse_simple_yaml(raw), body


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith((" ", "\t")):
            raise ValueError(f"invalid frontmatter line: {line}")
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line}")

        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError("invalid frontmatter: empty key")

        value = value.strip()
        if value:
            result[key] = _parse_scalar(value)
            i += 1
            continue

        block: list[str] = []
        i += 1
        while i < len(lines):
            child = lines[i]
            if not child.strip():
                i += 1
                continue
            if not child.startswith((" ", "\t")):
                break
            block.append(child)
            i += 1
        result[key] = _parse_block(block)
    return result


def _parse_block(lines: list[str]) -> Any:
    if not lines:
        return ""

    stripped = [line.strip() for line in lines]
    if all(line.startswith("- ") for line in stripped):
        return [_parse_scalar(line[2:].strip()) for line in stripped]

    mapping: dict[str, Any] = {}
    for line in stripped:
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError("invalid frontmatter: empty key")
        mapping[key] = _parse_scalar(value.strip()) if value.strip() else ""
    return mapping


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.startswith("["):
        if not value.endswith("]"):
            raise ValueError(f"invalid inline list: {value}")
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_unquote(part.strip()) for part in inner.split(",")]
    if "," in value:
        return [_unquote(part.strip()) for part in value.split(",")]
    return _unquote(value)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _argument_hint(value: Any) -> str | None:
    if isinstance(value, list):
        return f"[{', '.join(str(item) for item in value)}]"
    return _optional_string(value)


def _string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return default


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None
