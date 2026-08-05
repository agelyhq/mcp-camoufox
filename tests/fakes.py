"""Test doubles for the page-side objects ``dom/`` and ``tools/`` talk to.

Three shapes, because there are three seams worth faking:

* :class:`FakePage` owns a REAL :class:`~camoufox_mcp.dom.registry.ElementRegistry`
  over scripted :class:`FakeHandle` objects, so the store's own behaviour (locking,
  retiring, disposing, error classification) is what runs;
* :class:`ScriptedStorePage` fakes the store itself, for the layering rule that says
  a ``dom/`` function talks to ``page.elements`` and to nothing else;
* :class:`RestlessTab` fakes a tab that keeps navigating, for the settling wait.

Specialise by composition: pass a ``respond`` callable (sync or async) rather than
subclassing, so every double in the suite answers to the same two classes.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.registry import ElementRegistry
from camoufox_mcp.sessions.errors import PLAYWRIGHT_TARGET_CLOSED_ERROR

if TYPE_CHECKING:
    from collections.abc import Callable

_DEFAULT_ANSWER = {"ok": True}


class FakeHandle:
    """One execution context's handle: scripted answers, counted disposals.

    ``respond`` receives the dispatched payload and returns the answer, an exception
    to raise, or an awaitable of either (which is how a handle that blocks or never
    answers is expressed). ``order`` is an optional shared log, so a test can assert
    WHEN the release ran relative to the operations around it instead of when a clock
    said it should have.
    """

    def __init__(
        self,
        respond: Callable[[dict[str, Any]], Any] | None = None,
        *,
        dispose_error: BaseException | None = None,
        hang_dispose: bool = False,
        order: list[str] | None = None,
    ) -> None:
        self._respond = respond or (lambda _payload: _DEFAULT_ANSWER)
        self._dispose_error = dispose_error
        self._hang_dispose = hang_dispose
        self._order = order
        self.ops: list[str] = []
        self.disposed = 0

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        payload = dict(arg or {})
        self.ops.append(str(payload.get("op")))
        outcome = self._respond(payload)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def dispose(self) -> None:
        self.disposed += 1
        if self._order is not None:
            self._order.append("released")
        if self._hang_dispose:
            await asyncio.sleep(3600)
        if self._dispose_error is not None:
            raise self._dispose_error


class FakeKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def press(self, key: str) -> None:
        self.events.append(("press", key))

    async def type(self, text: str) -> None:
        self.events.append(("type", text))


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []

    async def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))


class FakeRaw:
    """The Playwright-native escape hatch a page exposes as ``page.raw``."""

    def __init__(self) -> None:
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()


class FakePage:
    """An evaluatable page owning a real registry, over scripted handles.

    Each ``evaluate_handle`` stands for one execution context, so ``built`` counts
    exactly how many times the tab's uid namespace was thrown away and rebuilt.
    """

    def __init__(self, *handles: FakeHandle) -> None:
        self._handles = list(handles)
        self.built = 0
        self.raw = FakeRaw()
        self.elements = ElementRegistry(self, target_closed=PLAYWRIGHT_TARGET_CLOSED_ERROR)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return None

    async def evaluate_handle(self, expression: str, arg: Any = None) -> FakeHandle:
        self.built += 1
        return self._handles.pop(0)


class ScriptedStore:
    """The element store of one tab, answering one scripted payload per call."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, op: str, arg: dict[str, Any] | None = None, **_: Any) -> Any:
        self.calls.append((op, dict(arg or {})))
        return self._payload


class ScriptedStorePage:
    """A page whose store is scripted, for asserting what a ``dom/`` call sends it."""

    def __init__(self, payload: Any) -> None:
        self.elements = ScriptedStore(payload)


class RestlessTab:
    """A tab that has moved again every time a capture is read back from it.

    Mocked rather than staged in the browser: a redirect chain fast enough to move
    under 2 consecutive captures is a race, and a race makes a test that reports
    coverage it does not have.
    """

    def __init__(self) -> None:
        self.captures = 0
        # The 2 reporting fields the real Page carries for the settling wait.
        self.shown_url: str | None = None
        self.doc_mark: int | None = None

    @property
    def url(self) -> str:
        return f"http://tab.test/{self.captures}"

    @property
    def raw(self) -> RestlessTab:
        return self

    async def wait_for_load_state(self, state: str, timeout: float | None = None) -> None:
        """The Playwright lifecycle wait, satisfied at once by a tab already moving."""
