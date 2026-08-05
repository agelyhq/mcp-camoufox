from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def press_key(profile: str, key: str) -> str:
        """Press a key or key combination on the focused element.

        Args:
            key: Playwright key name: Enter, Escape, Tab, ArrowDown, Backspace,
                Control+A, Shift+Tab.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.raw.keyboard.press(key)
        return f"Pressed {key}"
