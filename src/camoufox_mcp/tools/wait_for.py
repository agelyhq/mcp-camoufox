from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_VALID_CONDITIONS = ("load", "selector", "network_idle")


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def wait_for(
        profile: str,
        condition: str,
        selector: str | None = None,
        timeout: int = 30000,
    ) -> str:
        """Wait for a page condition on the profile's active tab.

        Args:
            profile: An already-active session identifier.
            condition: One of:
                - "load": wait for the document load event to fire.
                - "selector": wait for `selector` to appear in the DOM (requires
                  the `selector` argument, a CSS selector).
                - "network_idle": wait until there are no network connections for
                  at least 500 ms.
            selector: CSS selector to wait for. Required (and only used) when
                condition is "selector".
            timeout: Maximum wait in milliseconds (default 30000).

        Returns:
            "Condition met: <condition>" (with the selector appended for the
            "selector" case) once the wait resolves.

        Errors:
            Returns "Error: ValueError: ..." for an unknown condition or a missing
            selector, and "Timeout: ..." if the condition is not met in time.
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
            return f"Condition met: selector ({selector})"

        state = "load" if condition == "load" else "networkidle"
        await page.raw.wait_for_load_state(state, timeout=timeout)
        return f"Condition met: {condition}"
