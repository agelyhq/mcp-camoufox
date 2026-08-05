from __future__ import annotations

from typing import Any, Protocol


class JsHandle(Protocol):
    """A remote handle on a page-side JS value."""

    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    async def dispose(self) -> None: ...


class EvaluatablePage(Protocol):
    """Minimal page surface the DOM layer needs: run JS in the page context.

    The sessions layer's ``Page`` satisfies this; keeping it a Protocol keeps the
    inner DOM layer free of any dependency on outer packages.
    """

    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    async def evaluate_handle(self, expression: str, arg: Any = None) -> JsHandle: ...


class RegistryPage(EvaluatablePage, Protocol):
    """A page that owns the element store of its tab.

    ``elements`` is typed ``Any`` on purpose: a boundary protocol that names its
    implementation is not a boundary.
    """

    @property
    def elements(self) -> Any: ...


class ActionablePage(RegistryPage, Protocol):
    """A page that also exposes the raw driver page for mouse/keyboard input."""

    @property
    def raw(self) -> Any: ...
