from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.utilities.types import Image

from camoufox_mcp.dom import resolve_uid_or_raise, scroll_into_view
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def screenshot(profile: str, full_page: bool = False, uid: str = "") -> Image:
        """Capture a PNG screenshot of the active tab.

        This is the only tool that returns an image rather than text. By default it
        captures the current viewport. Set ``full_page`` to capture the entire
        scrollable page, or pass a ``uid`` to crop to a single element's bounding
        box (from the most recent snapshot).

        Params:
            profile: The browser profile whose active tab is captured.
            full_page: When true, capture the full scrollable page height instead
                of just the visible viewport. Ignored when ``uid`` is given.
            uid: Optional ``eN`` element uid (from ``snapshot``) to crop the shot to
                that element only. The element is scrolled into view first. Leave
                empty to screenshot the page/viewport.

        Returns:
            A PNG image of the requested region.

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: ValueError: unknown or stale uid '<uid>'; take a new
              snapshot" if the uid is missing or stale.
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid:
            await scroll_into_view(page, uid)
            info = await resolve_uid_or_raise(page, uid)
            width = float(info["width"])
            height = float(info["height"])
            clip = {
                "x": float(info["x"]) - width / 2,
                "y": float(info["y"]) - height / 2,
                "width": width,
                "height": height,
            }
            png = await page.raw.screenshot(type="png", clip=clip)
        else:
            png = await page.screenshot(full_page=full_page)
        return Image(data=png, format="png")
