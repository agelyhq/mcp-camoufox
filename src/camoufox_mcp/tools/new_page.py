from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def new_page(profile: str, url: str | None = None) -> str:
        """Open a new tab in the profile's session and make it active.

        Args:
            profile: A session identifier. Created on demand if not yet active.
            url: Optional absolute URL to load in the new tab.

        Returns:
            "Opened tab [<index>]: <title> (<url>)". When no url is given the tab
            starts blank.

        Errors:
            Returns "Error: ProfileInUseError: ..." if the profile is locked by
            another process, and "Timeout: ..." if the optional navigation stalls.
        """
        session = await get_session(deps, profile)
        index = await session.new_page(url)
        page = get_page(session)
        return f"Opened tab [{index}]: {await page.title()} ({page.url})"
