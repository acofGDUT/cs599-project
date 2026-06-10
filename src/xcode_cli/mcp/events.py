from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Literal


MCPEventKind = Literal["list_changed", "refresh", "reconnect", "shutdown", "failed", "warning"]


@dataclass(frozen=True)
class MCPEvent:
    ts: float
    server_name: str
    kind: MCPEventKind
    message: str


class MCPEventLog:
    def __init__(self, maxlen: int = 100) -> None:
        self._events: deque[MCPEvent] = deque(maxlen=maxlen)

    def append(self, *, server_name: str, kind: MCPEventKind, message: str) -> MCPEvent:
        event = MCPEvent(ts=time.time(), server_name=server_name, kind=kind, message=message)
        self._events.append(event)
        return event

    def snapshot(self) -> list[MCPEvent]:
        return list(self._events)

    def drain(self) -> list[MCPEvent]:
        events = list(self._events)
        self._events.clear()
        return events
