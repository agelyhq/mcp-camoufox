from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import DEFAULT_TIMEOUT_MS, get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def go_back(profile: str, timeout: int = DEFAULT_TIMEOUT_MS) -> str:
        """Go back 1 entry in the active tab's history.

        History is a per-tab stack of the URLs ``navigate`` visited, not the browser's
        own history, so in-page link navigation is not on it.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        target = page.back_url()
        if target is None:
            return "No previous page in history"
        # record=False: back_url already popped the entry being left, so recording the
        # arrival would push the page the agent just returned to back onto the stack.
        await page.goto(target, timeout=timeout, record=False)
        return f"Went back to: {await page.title()}"
