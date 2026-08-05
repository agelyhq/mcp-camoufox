from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def select_page(profile: str, page_idx: int) -> str:
        """Make a tab the active one, which every later call then acts on.

        Args:
            page_idx: Stable tab index, from ``list_pages``.
        """
        session = await get_session(deps, profile)
        session.select_page(page_idx)
        page = get_page(session)
        return f"Selected tab [{page_idx}]: {await page.title()} ({page.url})"
