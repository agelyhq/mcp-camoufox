from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def get_html(profile: str, outer_html: bool = True) -> str:
        """Return the current HTML of the active tab.

        Useful for scraping content or inspecting exact markup that the a11y/UID
        snapshot omits. The HTML reflects the live, post-JavaScript DOM (not the
        original network response).

        Params:
            profile: The browser profile whose active tab is read.
            outer_html: When true (default), return the full document markup
                (``<html>...</html>`` via ``documentElement.outerHTML``). When
                false, return only the body's inner markup
                (``document.body.innerHTML``), i.e. page content without the outer
                ``<html>``/``<head>`` wrapper.

        Returns:
            The requested HTML as a string.

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        expr = (
            "document.documentElement.outerHTML"
            if outer_html
            else "document.body ? document.body.innerHTML : ''"
        )
        result = await page.evaluate(expr)
        return str(result)
