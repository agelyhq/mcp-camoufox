from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import fill_field
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import ObserveMode, validate_observe
from camoufox_mcp.tools._target import resolve_target

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def fill(
        profile: str,
        uid: str | None = None,
        selector: str | None = None,
        *,
        value: str,
        clear_first: bool = True,
        observe: ObserveMode = "none",
    ) -> str:
        """Set a field's value: input, textarea, select, checkbox, radio, contenteditable.

        The field's kind decides what happens: a ``<select>`` picks the option matching
        ``value`` against option values then labels; a checkbox or radio is clicked to
        reach the state ``value`` asks for; anything else is typed into with real keys.

        Args:
            value: Text to enter, or "true"/"false" for a checkbox or radio.
            clear_first: Replace the existing content (default), or append to it.
        """
        validate_observe(observe)
        session = await get_session(deps, profile)
        page = get_page(session)
        target = await resolve_target(page, uid, selector)

        result = await fill_field(page, target, value, clear_first)
        if selector is not None:
            result += f" via {selector}"
        return result
