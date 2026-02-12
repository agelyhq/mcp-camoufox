from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def select_page(page_idx: int, ctx: Context) -> str:
        """Switch the active browser tab.

        Args:
            page_idx: Page index from get_page_info
        """
        try:
            manager = get_manager(ctx)
            if page_idx not in manager.pages:
                available = sorted(manager.pages.keys())
                return f"Error: No page at index {page_idx}. Available: {available}"

            manager.active_page_idx = page_idx
            handle = manager.pages[page_idx].handle
            title = await handle.get_title()
            return f"Switched to page [{page_idx}]: {title} | {handle.url}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
