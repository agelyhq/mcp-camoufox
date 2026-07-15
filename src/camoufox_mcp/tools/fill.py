from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import fill_field
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def fill(profile: str, uid: str, value: str, clear_first: bool = True) -> str:
        """Type text into an input, textarea or contenteditable element by uid.

        The element is focused and the value is typed. Take a ``snapshot`` first to
        obtain uids.

        Parameters:
        - profile: session/profile name.
        - uid: uid of the field from the latest snapshot.
        - value: text to enter.
        - clear_first: when true (default) the existing content is cleared before
          typing; when false the value is appended after the current content.

        Returns a confirmation like ``Filled <input> with 12 chars``.

        Errors:
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          the uid is invalid or the page changed since the snapshot.
        - ``Error: ValueError: element <tag> is not editable; ...`` when the target is
          not an input, textarea, select or contenteditable element.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        return await fill_field(page, uid, value, clear_first)
