from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def new_page(profile: str, url: str | None = None) -> str:
        """Open a new tab and make it active.

        Args:
            url: Absolute URL to load; the tab starts blank without it.
        """
        session = await get_session(deps, profile)
        index = await session.new_page(url)
        page = get_page(session)
        return f"Opened tab [{index}]: {await page.title()} ({page.url})"
