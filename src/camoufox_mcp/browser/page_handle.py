from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.browser.console import ConsoleMonitor
from camoufox_mcp.browser.network import NetworkMonitor

if TYPE_CHECKING:
    from playwright.async_api import Dialog, Page


class PageHandle:
    def __init__(self, page: Page) -> None:
        self._page = page
        self._pending_dialog: Dialog | None = None
        self.network = NetworkMonitor()
        self.network.attach(page)
        self.console = ConsoleMonitor()
        self.console.attach(page)
        self._page.on("dialog", self._on_dialog)

    def _on_dialog(self, dialog: Dialog) -> None:
        self._pending_dialog = dialog

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
            msg = "No dialog is pending"
            raise RuntimeError(msg)
        dialog = self._pending_dialog
        self._pending_dialog = None
        if action == "accept":
            await dialog.accept(prompt_text=prompt_text or "")
        else:
            await dialog.dismiss()

    @property
    def url(self) -> str:
        return self._page.url

    async def get_title(self) -> str:
        return await self._page.title()

    async def navigate(self, url: str, timeout: float = 30.0) -> dict[str, str]:
        timeout_ms = int(timeout * 1000)
        await self._page.goto(url, timeout=timeout_ms, wait_until="load")
        return {"url": self._page.url, "title": await self._page.title()}

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def screenshot(self, full_page: bool = False) -> bytes:
        return await self._page.screenshot(full_page=full_page, type="png")

    async def click_at(self, x: float, y: float, click_count: int = 1) -> None:
        await self._page.mouse.click(x, y, click_count=click_count)

    async def dispatch_key(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def insert_text(self, text: str) -> None:
        await self._page.keyboard.type(text)

    async def wait_for_load_state(self, state: str = "load", timeout: int = 30000) -> None:
        await self._page.wait_for_load_state(state, timeout=timeout)  # type: ignore[arg-type]

    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> None:
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def set_viewport(self, width: int, height: int) -> None:
        await self._page.set_viewport_size({"width": width, "height": height})

    async def select_option(self, selector: str, value: str) -> list[str]:
        return await self._page.select_option(selector, label=value)

    async def set_input_files(self, selector: str, file_path: str) -> None:
        await self._page.set_input_files(selector, file_path)

    async def close(self) -> None:
        await self._page.close()
