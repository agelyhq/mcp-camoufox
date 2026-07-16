from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._text import render_json

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_VALID_CONDITIONS = ("load", "selector", "network_idle", "predicate")


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def wait_for(
        profile: str,
        condition: str,
        selector: str | None = None,
        expression: str | None = None,
        return_expression: str | None = None,
        timeout: int = 30000,
    ) -> str:
        """Wait for a page condition on the profile's active tab.

        Prefer this over hand-rolled ``evaluate`` polling loops: it uses
        Playwright's native waiters (efficient, no busy-spin) and honors ``timeout``.

        Args:
            profile: An already-active session identifier.
            condition: One of (with a one-line example each):
                - "load": wait for the document load event to fire.
                  ``condition='load'``
                - "network_idle": wait until there are no network connections for
                  at least 500 ms. ``condition='network_idle'``
                - "selector": wait for `selector` (a CSS selector) to appear in the
                  DOM. ``condition='selector', selector='#results .item'``
                - "predicate": wait until `expression` — a JS expression or function
                  body evaluated in page context — returns truthy, re-checked on
                  each frame. ``condition='predicate',
                  expression="document.querySelectorAll('.row').length >= 10"``
            selector: CSS selector to wait for. Required (and only used) when
                condition is "selector".
            expression: JS expression/function that must become truthy. Required
                (and only used) when condition is "predicate"; e.g.
                ``"window.__appReady === true"`` or ``"() => !document.hidden"``.
            return_expression: Optional JS expression evaluated ONCE after the wait
                succeeds (any condition); its JSON-serialized result is appended to
                the success string. e.g. with condition "predicate" and
                ``return_expression="document.title"``.
            timeout: Maximum wait in milliseconds (default 30000).

        Returns:
            "Condition met: <condition>" (with the selector appended for the
            "selector" case), plus " => <result>" when `return_expression` is given.

        Errors:
            Returns "Error: ValueError: ..." for an unknown condition, a missing
            selector, or a missing predicate expression, and "Timeout: ..." if the
            condition is not met in time.
        """
        if condition not in _VALID_CONDITIONS:
            raise ValueError(
                f"invalid condition '{condition}'; must be one of {', '.join(_VALID_CONDITIONS)}"
            )

        session = await get_session(deps, profile)
        page = get_page(session)

        if condition == "selector":
            if not selector:
                raise ValueError("condition 'selector' requires a non-empty selector")
            await page.raw.wait_for_selector(selector, timeout=timeout)
            base = f"Condition met: selector ({selector})"
        elif condition == "predicate":
            if not expression:
                raise ValueError("condition 'predicate' requires a non-empty expression")
            await page.raw.wait_for_function(expression, timeout=timeout)
            base = "Condition met: predicate"
        else:
            state = "load" if condition == "load" else "networkidle"
            await page.raw.wait_for_load_state(state, timeout=timeout)
            base = f"Condition met: {condition}"

        if return_expression:
            value = await page.evaluate(return_expression)
            base += f" => {render_json(value)}"
        return base
