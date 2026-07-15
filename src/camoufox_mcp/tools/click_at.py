from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def click_at(profile: str, x: float, y: float, double_click: bool = False) -> str:
        """Click at raw viewport coordinates (bypasses the uid system).

        Use this for canvas, maps or any target that a snapshot cannot address with a
        uid. Coordinates are in CSS pixels relative to the visible viewport top-left.

        Parameters:
        - profile: session/profile name.
        - x, y: viewport coordinates in CSS pixels.
        - double_click: when true, performs a double click instead of a single click.

        Returns a confirmation like ``Clicked at (x, y)``.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.raw.mouse.click(x, y, click_count=2 if double_click else 1)
        verb = "Double-clicked" if double_click else "Clicked"
        return f"{verb} at ({round(x)}, {round(y)})"
