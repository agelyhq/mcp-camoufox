from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def type_text(profile: str, text: str, submit: bool = False) -> str:
        """Type text into whatever element currently has keyboard focus.

        Unlike ``fill`` this does not target a uid: it sends key events to the focused
        element. Focus an element first (e.g. with ``click``) if needed.

        Parameters:
        - profile: session/profile name.
        - text: characters to type.
        - submit: when true, presses Enter after typing (to submit a form/search).

        Returns a confirmation like ``Typed 8 chars`` (``+ Enter`` when submitted).
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.raw.keyboard.type(text)
        if submit:
            await page.raw.keyboard.press("Enter")
            return f"Typed {len(text)} chars + Enter"
        return f"Typed {len(text)} chars"
