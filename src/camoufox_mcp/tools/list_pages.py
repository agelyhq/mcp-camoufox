from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_pages(profile: str) -> str:
        """List the open tabs of a profile's session.

        Args:
            profile: An already-active session identifier.

        Returns:
            One line per tab: "[<index>]<active marker> <title> — <url>", where the
            active tab is marked with "*". Returns "No open tabs" if the session has
            none.

        Errors:
            Returns "Error: ProfileInUseError: ..." if the profile is locked by
            another process.
        """
        session = await get_session(deps, profile)
        infos = session.list_pages()
        if not infos:
            return "No open tabs"
        lines: list[str] = []
        for info in infos:
            marker = "*" if info.is_active else " "
            title = await info.page.title()
            lines.append(f"[{info.index}]{marker} {title} — {info.page.url}")
        return "\n".join(lines)
