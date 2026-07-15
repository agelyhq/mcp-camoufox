from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import fill_field
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def fill_form(profile: str, fields: list[dict[str, str]]) -> str:
        """Fill several form fields in one call.

        Each field is focused, cleared and filled in order. Take a ``snapshot`` first
        to obtain the uids.

        Parameters:
        - profile: session/profile name.
        - fields: list of objects ``{"uid": "<eN>", "value": "<text>"}``.

        Returns a confirmation like ``Filled 3 field(s)``.

        Errors:
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          any uid is invalid or the page changed since the snapshot.
        - ``Error: ValueError: element <tag> is not editable; ...`` when a target is
          not an input, textarea, select or contenteditable element.
        - ``Error: ValueError: each field needs 'uid' and 'value'`` when an entry is
          malformed.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        for field in fields:
            uid = field.get("uid")
            value = field.get("value")
            if not uid or value is None:
                raise ValueError("each field needs 'uid' and 'value'")
            await fill_field(page, uid, value)
        return f"Filled {len(fields)} field(s)"
