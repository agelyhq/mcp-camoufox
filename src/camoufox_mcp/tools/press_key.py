from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def press_key(key: str, ctx: Context) -> str:
        """Press a keyboard key or key combination.

        Args:
            key: Key name. Examples: 'Enter', 'Tab', 'Escape', 'ArrowDown',
                 'Backspace', 'a'. For combinations: 'Control+a',
                 'Shift+Enter', 'Alt+Tab'.
        """
        try:
            page = get_page(ctx)
            await page.dispatch_key(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
