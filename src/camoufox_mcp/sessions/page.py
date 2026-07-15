from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.sessions.console import ConsoleMonitor
from camoufox_mcp.sessions.network import NetworkMonitor

if TYPE_CHECKING:
    from playwright.async_api import Dialog
    from playwright.async_api import Page as PwPage


class Page:
    """A single browser tab: wraps a Playwright ``Page`` and its per-tab monitors.

    Tool authors reach the raw Playwright page via :pyattr:`raw` for any action not
    surfaced here (hover, drag, fill, keyboard, mouse, wait_for_selector, ...).
    """

    def __init__(self, page: PwPage) -> None:
        self._page = page
        self._pending_dialog: Dialog | None = None
        self._nav_history: list[str] = []
        self._nav_idx: int = -1
        self.network = NetworkMonitor()
        self.network.attach(page)
        self.console = ConsoleMonitor()
        self.console.attach(page)
        page.on("dialog", self._on_dialog)

    @property
    def raw(self) -> PwPage:
        """The underlying Playwright ``Page``. Never return this in tool output."""
        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    async def title(self) -> str:
        return await self._page.title()

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def screenshot(self, *, full_page: bool = False) -> bytes:
        return await self._page.screenshot(full_page=full_page, type="png")

    def get_dialog_info(self) -> dict[str, str] | None:
        if self._pending_dialog is None:
            return None
        return {
            "type": self._pending_dialog.type,
            "message": self._pending_dialog.message,
            "default_value": self._pending_dialog.default_value,
        }

    async def respond_to_dialog(self, action: str, prompt_text: str | None = None) -> None:
        if self._pending_dialog is None:
            raise RuntimeError("No dialog is pending")
        dialog = self._pending_dialog
        self._pending_dialog = None
        if action == "accept":
            await dialog.accept(prompt_text=prompt_text or "")
        else:
            await dialog.dismiss()

    async def close(self) -> None:
        await self._page.close()

    def record_navigation(self, url: str) -> None:
        """Push a URL onto the tool-maintained navigation stack.

        Camoufox/Firefox session history is not reliably navigable through
        Playwright, so back/forward is driven by this explicit stack instead. A
        forward branch (entries after the current index) is dropped on a new push,
        mirroring browser semantics.
        """
        del self._nav_history[self._nav_idx + 1 :]
        self._nav_history.append(url)
        self._nav_idx = len(self._nav_history) - 1

    def back_url(self) -> str | None:
        """Move the stack cursor back and return the target URL, or None."""
        if self._nav_idx <= 0:
            return None
        self._nav_idx -= 1
        return self._nav_history[self._nav_idx]

    def forward_url(self) -> str | None:
        """Move the stack cursor forward and return the target URL, or None."""
        if self._nav_idx >= len(self._nav_history) - 1:
            return None
        self._nav_idx += 1
        return self._nav_history[self._nav_idx]

    def _on_dialog(self, dialog: Dialog) -> None:
        self._pending_dialog = dialog
