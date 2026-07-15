from __future__ import annotations

from typing import Any, Protocol


class EvaluatablePage(Protocol):
    """Minimal page surface the DOM layer needs: run JS in the page context.

    The sessions layer's ``Page`` satisfies this; keeping it a Protocol keeps the
    inner DOM layer free of any dependency on outer packages.
    """

    async def evaluate(self, expression: str) -> Any: ...


class ActionablePage(EvaluatablePage, Protocol):
    """A page that also exposes the raw Playwright page for input actions (focus/type)."""

    @property
    def raw(self) -> Any: ...
