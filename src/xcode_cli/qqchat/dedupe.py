from __future__ import annotations


class QQMessageDedupe:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._seq: dict[str, int] = {}

    def reserve(self, message_id: str) -> int | None:
        if message_id in self._seen:
            return None
        self._seen.add(message_id)
        self._seq[message_id] = 1
        return 1
