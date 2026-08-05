from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import DEFAULT_TIMEOUT_MS, get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def reload(profile: str, timeout: int = DEFAULT_TIMEOUT_MS) -> str:
        """Reload the profile's active tab."""
        session = await get_session(deps, profile)
        page = get_page(session)
        # A fresh goto, not raw.reload(): camoufox/Firefox does not fire the ``load``
        # lifecycle on a native reload, so re-navigating is what reloads
        # deterministically. record=False: re-loading the current page is not a move,
        # and stacking it would make go_back return to where it already is.
        await page.goto(page.url, timeout=timeout, record=False)
        return f"Reloaded: {await page.title()}"
