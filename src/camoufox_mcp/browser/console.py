from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import ConsoleMessage, Page

MAX_ENTRIES = 1000


@dataclass
class ConsoleEntry:
    msgid: int
    level: str
    text: str
    url: str
    line_number: int
    timestamp: float = field(default_factory=time.time)


class ConsoleMonitor:
    def __init__(self) -> None:
        self._entries: deque[ConsoleEntry] = deque(maxlen=MAX_ENTRIES)
        self._preserved: deque[ConsoleEntry] = deque(maxlen=MAX_ENTRIES)
        self._next_msgid: int = 0

    def attach(self, page: Page) -> None:
        page.on("console", self._on_console)
        page.on("framenavigated", self._on_navigation)

    def _on_navigation(self, _: Any) -> None:
        self._preserved.extend(self._entries)
        while len(self._preserved) > MAX_ENTRIES:
            self._preserved.popleft()
        self._entries.clear()

    def _on_console(self, msg: ConsoleMessage) -> None:
        msgid = self._next_msgid
        self._next_msgid += 1
        entry = ConsoleEntry(
            msgid=msgid,
            level=msg.type,
            text=msg.text,
            url=msg.location.get("url", ""),
            line_number=msg.location.get("lineNumber", 0),
        )
        self._entries.append(entry)

    def list_entries(
        self,
        *,
        levels: list[str] | None = None,
        limit: int = 50,
        include_preserved: bool = False,
    ) -> list[ConsoleEntry]:
        source: list[ConsoleEntry] = list(self._entries)
        if include_preserved:
            source = list(self._preserved) + source

        if levels:
            levels_set = {lv.lower() for lv in levels}
            source = [e for e in source if e.level in levels_set]

        return source[-limit:]
