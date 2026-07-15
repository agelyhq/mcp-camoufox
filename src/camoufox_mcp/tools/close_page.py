from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def close_page(profile: str, page_idx: int) -> str:
        """Close a tab of the profile's session by its index.

        Closing the active tab promotes another open tab to active (if any remain).
        Use `list_pages` to discover valid indices.

        Args:
            profile: An already-active session identifier.
            page_idx: Stable index of the tab to close (from `list_pages`).

        Returns:
            "Closed tab [<page_idx>] (<remaining> remaining)".

        Errors:
            Returns "Error: ValueError: ..." if no tab has the given index.
        """
        session = await get_session(deps, profile)
        await session.close_page(page_idx)
        return f"Closed tab [{page_idx}] ({session.page_count} remaining)"
