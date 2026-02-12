from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def new_page(ctx: Context, url: str | None = None) -> str:
        """Open a new browser tab, optionally navigating to a URL.

        Args:
            url: Optional URL to load immediately
        """
        try:
            manager = get_manager(ctx)
            idx = await manager.new_page()

            if url:
                page = manager.pages[idx].handle
                await page.navigate(url)
                return f"New page [{idx}]: {url}"

            return f"New page [{idx}] (blank)"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
