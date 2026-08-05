from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def close_page(profile: str, page_idx: int) -> str:
        """Close a tab. Closing the active one promotes another still-open tab.

        Args:
            page_idx: Stable tab index, from ``list_pages``.
        """
        session = await get_session(deps, profile)
        await session.close_page(page_idx)
        return f"Closed tab [{page_idx}] ({session.page_count} remaining)"
