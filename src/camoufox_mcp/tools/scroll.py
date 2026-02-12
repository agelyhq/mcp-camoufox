from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.dom import scroll_into_view
from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def scroll(
        ctx: Context,
        direction: str = "down",
        amount: int = 3,
        uid: str | None = None,
    ) -> str:
        """Scroll the page or scroll an element into view.

        Args:
            direction: 'up', 'down', 'left', 'right'
            amount: Number of scroll steps (1 step ~ 100px)
            uid: If provided, scroll this element into view instead
        """
        try:
            page = get_page(ctx)

            if uid:
                result = await scroll_into_view(page, uid)
                if "error" in result:
                    return f"Error: {result['error']}"
                return f"Scrolled element {uid} into view"

            delta_map = {
                "down": (0, amount * 100),
                "up": (0, -(amount * 100)),
                "right": (amount * 100, 0),
                "left": (-(amount * 100), 0),
            }
            if direction not in delta_map:
                return f"Error: direction must be one of: {', '.join(delta_map)}"
            dx, dy = delta_map[direction]
            await page.evaluate(f"window.scrollBy({dx}, {dy})")
            return f"Scrolled {direction} by {amount} steps"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
