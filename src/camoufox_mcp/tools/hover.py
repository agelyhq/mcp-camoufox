from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import resolve_center
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def hover(profile: str, uid: str) -> str:
        """Move the mouse over an element identified by its snapshot uid.

        Useful to reveal hover menus, tooltips or lazy-loaded content. Take a
        ``snapshot`` first to obtain uids. The element is scrolled into view and the
        pointer is moved to its center.

        Parameters:
        - profile: session/profile name.
        - uid: element uid from the latest snapshot (e.g. ``e7``).

        Returns a confirmation like ``Hovered <a> at (x, y)``.

        Errors:
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          the uid is invalid or the page changed since the snapshot.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        x, y, tag = await resolve_center(page, uid)
        await page.raw.mouse.move(x, y)
        return f"Hovered <{tag}> at ({round(x)}, {round(y)})"
