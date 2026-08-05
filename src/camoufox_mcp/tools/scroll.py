from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import scroll_uid
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_DELTAS = {
    "down": (0, 1),
    "up": (0, -1),
    "left": (-1, 0),
    "right": (1, 0),
}


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def scroll(
        profile: str,
        direction: str = "down",
        amount: int | None = None,
        uid: str | None = None,
    ) -> str:
        """Scroll the viewport, or bring 1 element into view.

        Args:
            direction: down, up, left or right. Ignored when ``uid`` is given.
            amount: Pixels; 1 viewport length when omitted. Ignored with ``uid``.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid is not None:
            return f"Scrolled <{await scroll_uid(page, uid)}> into view"
        validate_choice("direction", direction, tuple(_DELTAS))
        dx_sign, dy_sign = _DELTAS[direction]
        if amount is None:
            axis = "innerWidth" if dx_sign else "innerHeight"
            amount = int(await page.evaluate(f"window.{axis}"))
        # ``mouse.wheel`` does not move the scroll position in headless
        # Camoufox/Firefox; scroll via the DOM so scrollY updates and the native
        # ``scroll`` event still fires (infinite-scroll listeners depend on it).
        await page.evaluate(f"window.scrollBy({dx_sign * amount}, {dy_sign * amount})")
        return f"Scrolled {direction} by {amount}px"
