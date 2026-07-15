from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import resolve_center
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def drag(profile: str, from_uid: str, to_uid: str) -> str:
        """Drag one element onto another using their snapshot uids.

        Performs a press-move-release gesture from the center of ``from_uid`` to the
        center of ``to_uid``. Take a ``snapshot`` first to obtain uids.

        Parameters:
        - profile: session/profile name.
        - from_uid: uid of the element to pick up.
        - to_uid: uid of the drop target.

        Returns a confirmation like ``Dragged <div> to <div>``.

        Errors:
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          either uid is invalid or the page changed since the snapshot.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        sx, sy, stag = await resolve_center(page, from_uid)
        await page.raw.mouse.move(sx, sy)
        await page.raw.mouse.down()
        tx, ty, ttag = await resolve_center(page, to_uid)
        await page.raw.mouse.move(tx, ty)
        await page.raw.mouse.up()
        return f"Dragged <{stag}> to <{ttag}>"
