from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.dom import resolve_uid, scroll_into_view
from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def click(uid: str, ctx: Context, double_click: bool = False) -> str:
        """Click an element identified by its UID from take_snapshot.

        Args:
            uid: Element UID (e.g., 'e0', 'e5')
            double_click: Double-click instead of single click
        """
        try:
            page = get_page(ctx)
            info = await resolve_uid(page, uid)
            if "error" in info:
                return f"Error: {info['error']}"

            await scroll_into_view(page, uid)
            info = await resolve_uid(page, uid)
            if "error" in info:
                return f"Error: {info['error']}"

            click_count = 2 if double_click else 1
            await page.click_at(info["x"], info["y"], click_count=click_count)
            return f"Clicked {info['tag']} at ({info['x']:.0f}, {info['y']:.0f})"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
