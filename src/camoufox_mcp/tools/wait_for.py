from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page

_VALID_CONDITIONS = frozenset({"load", "selector", "idle"})


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def wait_for(
        ctx: Context,
        condition: str = "load",
        selector: str | None = None,
        timeout: int = 10000,
    ) -> str:
        """Wait for a page condition before proceeding.

        Args:
            condition: 'load' | 'selector' | 'idle'
            selector: CSS selector (required when condition='selector')
            timeout: Max wait time in ms
        """
        try:
            if condition not in _VALID_CONDITIONS:
                return f"Error: condition must be one of: {', '.join(sorted(_VALID_CONDITIONS))}"

            page = get_page(ctx)

            if condition == "load":
                try:
                    await page.wait_for_load_state("load", timeout=timeout)
                    return "Page loaded"
                except TimeoutError:
                    return f"Timeout waiting for page load ({timeout}ms)"

            if condition == "selector":
                if not selector:
                    return "Error: selector param required when condition='selector'"
                try:
                    await page.wait_for_selector(selector, timeout=timeout)
                    return f"Element '{selector}' found"
                except TimeoutError:
                    return f"Timeout waiting for '{selector}' ({timeout}ms)"

            try:
                await page.wait_for_load_state("networkidle", timeout=timeout)
                return "Network idle"
            except TimeoutError:
                return f"Timeout waiting for network idle ({timeout}ms)"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
