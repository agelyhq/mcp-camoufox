from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import tool
from camoufox_mcp.tools._tabs import format_tab_line

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_sessions() -> str:
        """List every live session, its tab count, and each tab's index, title and URL."""
        sessions = deps.sessions.list_sessions()
        if not sessions:
            return "No active sessions."

        blocks = []
        for session in sessions:
            header = f"Session '{session.profile}' ({session.page_count} tab(s)):"
            tab_lines = [f"  {await format_tab_line(info)}" for info in session.list_pages()]
            blocks.append(header + "\n" + "\n".join(tab_lines))
        return "\n\n".join(blocks)
