from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_session, tool
from camoufox_mcp.tools._tabs import format_tab_line

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_pages(profile: str) -> str:
        """List the open tabs of a session, 1 line each, the active one marked "*"."""
        session = await get_session(deps, profile)
        infos = session.list_pages()
        if not infos:
            return "No open tabs"
        return "\n".join([await format_tab_line(info) for info in infos])
