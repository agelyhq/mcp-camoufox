from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from camoufox_mcp.sessions.log import PreservingLog, on_main_frame_navigation

if TYPE_CHECKING:
    from playwright.async_api import ConsoleMessage, Page


@dataclass
class ConsoleEntry:
    msgid: int
    level: str
    text: str
    url: str
    line_number: int


class ConsoleMonitor:
    """The console output of one tab, kept in a :class:`PreservingLog`."""

    def __init__(self) -> None:
        self._log: PreservingLog[ConsoleEntry] = PreservingLog()

    def attach(self, page: Page) -> None:
        """Subscribe to console output for one tab.

        Do not remove this subscription hoping to make the tab quieter: it does not.
        When page script logs a DOM node, the Firefox driver builds an element handle
        for that argument inside its own event handler, before any subscriber is
        consulted (``_onConsole`` -> ``createHandle3`` -> the ``ElementHandle``
        constructor, coreBundle.js:43478, :42843, :16039), and that constructor
        evaluates the driver's injected script into the world the node lives in. The
        arguments are built while calling ``addConsoleMessage`` (coreBundle.js:19925),
        which only then checks whether anyone is listening, so the artifact appears
        with or without this handler. Measured both ways; pinned by
        tests/test_no_markers.py. Only ``msg.type``, ``msg.text`` and ``msg.location``
        are read here, never ``msg.args``, which is the one thing on this object that
        would create further handles of our own accord.
        """
        page.on("console", self._on_console)
        # A message carries no evidence of the document it came from, so a navigation
        # retires the whole ring. It can afford to: console messages and the navigation
        # itself are both announced by the content process, in that order.
        on_main_frame_navigation(page, self._log.rotate)

    def _on_console(self, msg: ConsoleMessage) -> None:
        self._log.record(
            ConsoleEntry(
                msgid=self._log.next_id(),
                level=msg.type,
                text=msg.text,
                url=msg.location.get("url", ""),
                line_number=msg.location.get("lineNumber", 0),
            )
        )

    def list_entries(
        self,
        *,
        levels: list[str] | None = None,
        include_preserved: bool = False,
    ) -> tuple[list[ConsoleEntry], int]:
        """Captured messages, oldest first, and the total that matched.

        Unpaged, unlike the network listing: ``list_console_messages`` exposes no page
        parameters and keeps the TAIL of the match, since a console is read for what just
        happened. A page size and a page index here never had a caller.
        """
        wanted = {level.lower() for level in levels} if levels else None
        return self._log.select(
            keep=None if wanted is None else (lambda entry: entry.level in wanted),
            include_preserved=include_preserved,
        )
