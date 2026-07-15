from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_sessions() -> str:
        """List all currently active browser sessions and their open tabs.

        A session is one live Camoufox browser bound to a persistent profile. This
        tool takes no profile argument and reports every active session: the profile
        name, its number of open tabs, and for each tab its stable index, active
        marker, URL and title.

        Returns a text listing, or "No active sessions." when none are running.

        Errors: exceptions are rendered as "Error: <Type>: <message>".
        """
        sessions = deps.sessions.list_sessions()
        if not sessions:
            return "No active sessions."

        blocks = []
        for session in sessions:
            header = f"Session '{session.profile}' ({session.page_count} tab(s)):"
            tab_lines = []
            for pi in session.list_pages():
                marker = "*" if pi.is_active else " "
                title = await pi.page.title()
                tab_lines.append(f"  {marker} [{pi.index}] {pi.page.url} — {title}")
            blocks.append(header + "\n" + "\n".join(tab_lines))
        return "\n\n".join(blocks)
