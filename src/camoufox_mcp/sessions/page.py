from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from camoufox_mcp.deadlines import bounded
from camoufox_mcp.dom import ElementRegistry
from camoufox_mcp.sessions.console import ConsoleMonitor
from camoufox_mcp.sessions.errors import (
    PLAYWRIGHT_TARGET_CLOSED_ERROR,
    NoPendingDialogError,
    UnknownDialogActionError,
)
from camoufox_mcp.sessions.network import NetworkMonitor
from camoufox_mcp.sessions.teardown import TAB_CLOSE_TIMEOUT

if TYPE_CHECKING:
    from playwright.async_api import Dialog, JSHandle
    from playwright.async_api import Page as PwPage

# The 2 answers a dialog has. Exported so the tool that takes the word from an agent
# rejects it against this list rather than against a copy of it.
DialogAction = Literal["accept", "dismiss"]
DIALOG_ACTIONS: tuple[DialogAction, ...] = ("accept", "dismiss")


class Page:
    """A single browser tab: wraps a Playwright ``Page`` and its per-tab monitors.

    Tool authors reach the raw Playwright page via :pyattr:`raw` for mouse, keyboard,
    screenshot and navigation only. Element addressing goes through
    :pyattr:`elements`, never through a selector, a locator or an element handle.
    """

    def __init__(self, page: PwPage) -> None:
        self._page = page
        self._pending_dialog: Dialog | None = None
        self._nav_history: list[str] = []
        # Reporting state, not browser state: the last URL this tab showed the agent,
        # and the highest document-request id it had issued when the current action
        # started. Both are read by tools/_page_line.py to decide whether the tab
        # moved; neither may touch the navigation stack above.
        self.shown_url: str | None = None
        self.doc_mark: int | None = None
        self.network = NetworkMonitor()
        self.network.attach(page)
        self.console = ConsoleMonitor()
        self.console.attach(page)
        # A plain attribute, not a property: the tab owns exactly one element store
        # and it is created without any I/O.
        self.elements = ElementRegistry(self, target_closed=PLAYWRIGHT_TARGET_CLOSED_ERROR)
        page.on("dialog", self._on_dialog)
        # A new document means the old store is gone with its execution context.
        # Retiring the handle here saves the next operation one doomed round trip;
        # correctness still rests on the exception path inside the registry.
        page.on("domcontentloaded", self._on_loaded)

    @property
    def raw(self) -> PwPage:
        """The underlying Playwright ``Page``. Never return this in tool output."""
        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    async def title(self) -> str:
        return await self._page.title()

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return await self._page.evaluate(expression, arg)

    async def evaluate_handle(self, expression: str, arg: Any = None) -> JSHandle:
        return await self._page.evaluate_handle(expression, arg)

    async def screenshot(self, *, full_page: bool = False) -> bytes:
        # caret="initial" is mandatory: the default writes an inline
        # `caret-color: transparent !important` onto every input, textarea and
        # contenteditable before capturing, which a page observes as attribute
        # mutations.
        return await self._page.screenshot(full_page=full_page, type="png", caret="initial")

    async def respond_to_dialog(self, action: DialogAction, prompt_text: str | None = None) -> None:
        """Answer the pending dialog, or raise when there is none.

        The guard below is what makes the ``else`` safe. Without it, the dismissal was
        the fallback of the accept test, so a word this method does not know answered
        the dialog anyway, and answered it the destructive way.
        """
        if self._pending_dialog is None:
            raise NoPendingDialogError
        if action not in DIALOG_ACTIONS:
            raise UnknownDialogActionError(action)
        dialog = self._pending_dialog
        self._pending_dialog = None
        if action == "accept":
            await dialog.accept(prompt_text=prompt_text or "")
        else:
            await dialog.dismiss()

    async def close(self) -> None:
        # Release first, close second. A release sent after the target is closed can
        # only fail, so the other order made the disposal a formality that raised a
        # target-closed error on every single tab close. Both halves are bounded, so a
        # wedged content process cannot hold the tab, or the session shutdown behind
        # it, open forever.
        await self.elements.dispose()
        await bounded(self._page.close(), TAB_CLOSE_TIMEOUT)

    async def goto(self, url: str, *, timeout: float | None = None, record: bool = True) -> None:
        """Load ``url`` and, unless replaying history, push it onto the back stack.

        The 2 calls belong together: a navigation nobody recorded is a navigation
        ``go_back`` cannot return to. ``record=False`` is for the replays themselves
        (``go_back``, ``reload``), which must not stack a new entry on the one they
        are re-visiting.
        """
        await self._page.goto(url, timeout=timeout, wait_until="load")
        if record:
            self._record_navigation(self.url)

    def _record_navigation(self, url: str) -> None:
        """Push a URL onto the tool-maintained navigation stack.

        Camoufox/Firefox session history is not reliably navigable through
        Playwright, so back is driven by this explicit stack instead. There is no
        forward branch: ``back_url`` pops the entry it leaves behind, so the last
        element is always the current page and nothing is ever written to be read
        only by a truncation.
        """
        self._nav_history.append(url)

    def back_url(self) -> str | None:
        """Drop the current entry and return the previous URL, or None."""
        if len(self._nav_history) < 2:
            return None
        self._nav_history.pop()
        return self._nav_history[-1]

    def _on_dialog(self, dialog: Dialog) -> None:
        self._pending_dialog = dialog

    def _on_loaded(self, _page: PwPage) -> None:
        """Retire the element store: this event only ever announces a new document.

        The driver raises this on the page only for the main frame, so a sub-frame
        load never costs the tab its uid namespace.
        """
        self.elements.forget()
