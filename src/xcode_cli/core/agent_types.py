from __future__ import annotations

from enum import Enum


class AgentType(str, Enum):
    EXPLORE = "explore"
    PLAN = "plan"
    GENERAL = "general"


__all__ = ["AgentType"]
