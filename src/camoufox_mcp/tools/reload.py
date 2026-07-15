from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def reload(profile: str, timeout: int = 30000) -> str:
        """Reload the profile's active tab.

        Args:
            profile: An already-active session identifier.
            timeout: Reload timeout in milliseconds (default 30000).

        Implemented as a fresh navigation to the current URL: camoufox/Firefox does
        not fire the ``load`` lifecycle on a native ``reload``, so a re-``goto`` is
        used to reload deterministically.

        Returns:
            "Reloaded: <title> (<url>)".

        Errors:
            Returns "Error: RuntimeError: ..." if the session has no active page,
            and "Timeout: ..." if the reload does not complete in time.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.raw.goto(page.url, timeout=timeout, wait_until="load")
        return f"Reloaded: {await page.title()} ({page.url})"
