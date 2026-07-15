from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def go_forward(profile: str, timeout: int = 30000) -> str:
        """Navigate forward one entry in the active tab's history.

        Args:
            profile: An already-active session identifier.
            timeout: Navigation timeout in milliseconds (default 30000).

        Back/forward is driven by a deterministic per-tab navigation stack fed by
        ``navigate`` (camoufox/Firefox native history is not reliably navigable),
        so it follows the URLs this session visited, not in-page link history.

        Returns:
            "Went forward to: <title> (<url>)", or "No next page in history" when
            there is nothing to go forward to.

        Errors:
            Returns "Error: RuntimeError: ..." if the session has no active page,
            and "Timeout: ..." if navigation does not complete in time.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        target = page.forward_url()
        if target is None:
            return "No next page in history"
        await page.raw.goto(target, timeout=timeout, wait_until="load")
        return f"Went forward to: {await page.title()} ({page.url})"
