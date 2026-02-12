from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def close_page(page_idx: int, ctx: Context) -> str:
        """Close a browser tab by index.

        Args:
            page_idx: Page index to close
        """
        try:
            manager = get_manager(ctx)
            await manager.close_page(page_idx)

            if manager.pages:
                return f"Closed [{page_idx}]. Active: [{manager.active_page_idx}]"
            return f"Closed [{page_idx}]. No pages open."
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
