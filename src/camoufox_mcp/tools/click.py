from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import resolve
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import ObserveMode, validate_observe
from camoufox_mcp.tools._target import resolve_target

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def click(
        profile: str,
        uid: str | None = None,
        selector: str | None = None,
        double_click: bool = False,
        observe: ObserveMode = "none",
    ) -> str:
        """Click an element by snapshot uid or by selector.

        The element is scrolled into view, measured, then clicked at its centre.
        Anything covering it is an error rather than a click on the cover.

        Args:
            double_click: Double click instead of a single click.
        """
        validate_observe(observe)
        session = await get_session(deps, profile)
        page = get_page(session)
        target = await resolve_target(page, uid, selector)

        hit = await resolve(page, target, hit=True)
        await page.raw.mouse.click(hit.x, hit.y, click_count=2 if double_click else 1)

        verb = "Double-clicked" if double_click else "Clicked"
        result = f"{verb} <{hit.tag}> at ({round(hit.x)}, {round(hit.y)})"
        if selector is not None:
            result += f" via {selector}"
        return result
