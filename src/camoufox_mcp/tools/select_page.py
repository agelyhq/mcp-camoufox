from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def select_page(profile: str, page_idx: int) -> str:
        """Make a tab the active one for subsequent tool calls.

        Subsequent tools (navigate, snapshot, click, ...) act on the active tab.
        Use `list_pages` to discover valid indices.

        Args:
            profile: An already-active session identifier.
            page_idx: Stable index of the tab to activate (from `list_pages`).

        Returns:
            "Selected tab [<page_idx>]: <title> (<url>)".

        Errors:
            Returns "Error: ValueError: ..." if no tab has the given index.
        """
        session = await get_session(deps, profile)
        session.select_page(page_idx)
        page = get_page(session)
        return f"Selected tab [{page_idx}]: {await page.title()} ({page.url})"
