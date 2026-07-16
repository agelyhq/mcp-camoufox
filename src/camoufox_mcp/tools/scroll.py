from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import resolve_uid_or_raise, scroll_into_view
from camoufox_mcp.tools._base import get_page, get_session, tool

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
        """Scroll the page, or bring a specific element into view.

        Two modes:
        - When ``uid`` is given, that element is scrolled into view (``direction`` and
          ``amount`` are ignored).
        - Otherwise the viewport is scrolled by ``amount`` pixels in ``direction``.

        Parameters:
        - profile: session/profile name.
        - direction: one of ``down``, ``up``, ``left``, ``right`` (default ``down``).
        - amount: pixels to scroll; defaults to one viewport length when omitted.
        - uid: optional element uid to scroll into view instead of a fixed distance.

        Returns a confirmation of what was scrolled.

        Errors:
        - ``Error: ValueError: invalid direction '<d>'; use down/up/left/right``.
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          a given uid is invalid or stale.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid is not None:
            info = await resolve_uid_or_raise(page, uid)
            await scroll_into_view(page, uid)
            return f"Scrolled <{info.get('tag', '?')}> into view"
        if direction not in _DELTAS:
            raise ValueError(f"invalid direction '{direction}'; use {'/'.join(_DELTAS)}")
        dx_sign, dy_sign = _DELTAS[direction]
        if amount is None:
            axis = "innerWidth" if dx_sign else "innerHeight"
            amount = int(await page.evaluate(f"window.{axis}"))
        # ``mouse.wheel`` does not move the scroll position in headless
        # Camoufox/Firefox; scroll via the DOM so scrollY updates and the native
        # ``scroll`` event still fires (infinite-scroll listeners depend on it).
        await page.evaluate(f"window.scrollBy({dx_sign * amount}, {dy_sign * amount})")
        return f"Scrolled {direction} by {amount}px"
