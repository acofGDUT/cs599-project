from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserTurnInput:
    display_content: str
    model_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def coerce_user_turn_input(value: str | UserTurnInput) -> UserTurnInput:
    if isinstance(value, UserTurnInput):
        return value
    return UserTurnInput(display_content=value, model_content=value)
